"""
scenario_manager.py
小売FS（retail_fs.py）の前提条件一式（fs_design）を
名前付きシナリオとして保存・読込・比較実行する。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

import financial_model
import retail_fs
import supply_planner

SCENARIOS_FILE = Path("/tmp/energy_dashboard/scenarios.json")


@dataclass
class Scenario:
    name: str
    fs_design: dict = field(default_factory=dict)      # pages/fs_scenario_design.py が組み立てる設計一式
    supply_sources: list = field(default_factory=list)  # list[asdict(SupplySource)]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def save_scenario(scenario: Scenario) -> None:
    scenarios = [s for s in load_scenarios() if s.name != scenario.name]
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


def run_scenario(scenario: Scenario, demand_df: pd.DataFrame) -> dict:
    """シナリオの前提条件で retail_fs.run_fs を実行し、その戻り値（{"monthly","annual"}）を返す。"""
    design = scenario.fs_design

    tariff_plans = [retail_fs.TariffPlan(**p) for p in design.get("tariff_plans", [])] or retail_fs.default_tariff_plans()
    facility_configs = [retail_fs.FacilityConfig(**c) for c in design.get("facility_configs", [])]
    transmission_rates = {
        vc: retail_fs.TransmissionRate(**r) for vc, r in design.get("transmission_rates", {}).items()
    } or retail_fs.default_transmission_rates()

    jepx_by_month_hour = {
        tuple(int(x) for x in k.split("-")): v
        for k, v in design.get("jepx_by_month_hour", {}).items()
    } or financial_model.DEFAULT_JEPX_PRICE_BY_MONTH_HOUR

    sources = [supply_planner.SupplySource(**s) for s in scenario.supply_sources]
    ts = pd.DatetimeIndex(demand_df["datetime"].sort_values().unique())
    supply_df = supply_planner.combine_supply_profiles(sources, ts)
    balance_df = financial_model.calc_balance(demand_df, supply_df)

    return retail_fs.run_fs(
        demand_df=demand_df,
        balance_df=balance_df,
        supply_df=supply_df,
        facility_configs=facility_configs,
        tariff_plans=tariff_plans,
        transmission_rates=transmission_rates,
        source_costs=design.get("source_costs", {}),
        jepx_price_by_month_hour=jepx_by_month_hour,
        fuel_adjustment_yen_per_kwh=design.get("fuel_adjustment_yen_per_kwh", 0.0),
        renewable_levy_yen_per_kwh=design.get("renewable_levy_yen_per_kwh", 4.18),
        capacity_unit_yen_per_kw_year=design.get("capacity_unit_yen_per_kw_year", 0.0),
        reserve_margin_pct=design.get("reserve_margin_pct", 3.0),
    )


def annual_summary(fs_result: dict) -> dict:
    """run_fs()/run_scenario() の結果から 売上高／売上原価／粗利益 の年間累計を返す。"""
    annual = fs_result.get("annual", {}) if fs_result else {}
    return {
        "revenue": float(annual.get("sales_revenue", 0.0)),
        "cost_of_sales": float(annual.get("cost_of_sales", 0.0)),
        "gross_profit": float(annual.get("gross_profit", 0.0)),
    }
