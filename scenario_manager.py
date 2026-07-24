"""
scenario_manager.py
収支シミュレーションの前提条件（料金設計・JEPX単価・電源構成等）を
名前付きシナリオとして保存・読込・比較実行する。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

import financial_model
import supply_planner
import tariff

SCENARIOS_FILE = Path("/tmp/energy_dashboard/scenarios.json")


@dataclass
class Scenario:
    name: str
    facility_assignments: dict = field(default_factory=dict)   # {facility_name: asdict(FacilityTariffAssignment)}
    tariff_high: dict = field(default_factory=dict)             # asdict(TariffPlan)
    tariff_low: dict = field(default_factory=dict)              # asdict(TariffPlan)
    jepx_by_month_hour: dict = field(default_factory=dict)      # {"month-hour": price} (JSON key must be str)
    source_costs: dict = field(default_factory=dict)            # {source_name: cost_per_kwh}
    supply_sources: list = field(default_factory=list)          # list[asdict(SupplySource)]
    surplus_price: float = 7.0
    imb_factor: float = 10.0
    imb_premium: float = 3.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def save_scenario(scenario: Scenario) -> None:
    scenarios = load_scenarios()
    scenarios = [s for s in scenarios if s.name != scenario.name]
    scenarios.append(scenario)
    SCENARIOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCENARIOS_FILE.write_text(
        json.dumps([asdict(s) for s in scenarios], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_scenarios() -> list[Scenario]:
    if not SCENARIOS_FILE.exists():
        return []
    try:
        return [Scenario(**d) for d in json.loads(SCENARIOS_FILE.read_text("utf-8"))]
    except Exception:
        return []


def delete_scenario(name: str) -> None:
    scenarios = [s for s in load_scenarios() if s.name != name]
    SCENARIOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCENARIOS_FILE.write_text(
        json.dumps([asdict(s) for s in scenarios], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_scenario(scenario: Scenario, demand_df: pd.DataFrame) -> pd.DataFrame:
    """シナリオの前提条件でP&Lを計算し、月次サマリー（visualizer.monthly_pnl_chart互換）を返す。"""
    assignments = {
        name: tariff.FacilityTariffAssignment(**a)
        for name, a in scenario.facility_assignments.items()
    }
    plan_high = tariff.TariffPlan(**scenario.tariff_high) if scenario.tariff_high else tariff.CHUBU_HIGH_VOLTAGE_DEFAULT()
    plan_low = tariff.TariffPlan(**scenario.tariff_low) if scenario.tariff_low else tariff.CHUBU_LOW_VOLTAGE_DEFAULT()

    sources = [supply_planner.SupplySource(**s) for s in scenario.supply_sources]
    ts = pd.DatetimeIndex(demand_df["datetime"].sort_values().unique())
    supply_df = supply_planner.combine_supply_profiles(sources, ts)

    balance_df = financial_model.calc_balance(demand_df, supply_df)

    jepx_by_month_hour = {
        tuple(int(x) for x in k.split("-")): v
        for k, v in scenario.jepx_by_month_hour.items()
    } if scenario.jepx_by_month_hour else None

    pnl_df = financial_model.calc_pnl(
        balance_df, supply_df, scenario.source_costs,
        jepx_price_by_month_hour=jepx_by_month_hour,
        surplus_sell_price_yen=scenario.surplus_price,
        inbalance_factor_pct=scenario.imb_factor,
        inbalance_premium_yen=scenario.imb_premium,
    )
    facility_revenue = tariff.calc_facility_revenue_monthly(demand_df, assignments, plan_high, plan_low)
    return financial_model.monthly_pnl_summary(pnl_df, facility_revenue_monthly=facility_revenue)


def annual_summary(monthly_df: pd.DataFrame) -> dict:
    """月次サマリーから年間累計の 売上高／売上原価／粗利益 を返す。"""
    if monthly_df is None or monthly_df.empty:
        return {"revenue": 0.0, "cost_of_sales": 0.0, "gross_profit": 0.0}
    return {
        "revenue": float(monthly_df["revenue"].sum()),
        "cost_of_sales": float(monthly_df["cost_of_sales"].sum()),
        "gross_profit": float(monthly_df["gross_profit"].sum()),
    }
