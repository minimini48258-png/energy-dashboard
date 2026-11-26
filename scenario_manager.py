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

from typing import Optional

import pandas as pd

import storage

import financial_model
import retail_fs
import supply_cache_manager
import supply_planner

SCENARIOS_FILE = storage.DATA_DIR / "scenarios.json"


@dataclass
class Scenario:
    name: str
    fs_design: dict = field(default_factory=dict)      # pages/fs_scenario_design.py が組み立てる設計一式
    supply_sources: list = field(default_factory=list)  # list[asdict(SupplySource)]（電源管理のパラメータ設定電源）
    supply_data_cache_id: Optional[str] = None          # アップロード済み供給データのキャッシュID（supply_cache_manager）
    selected_supply_names: list = field(default_factory=list)  # キャッシュ供給データのうち使用する電源名
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


SURPLUS_MODES: dict[str, str] = {
    "buy_and_sell": "余剰も全量買い取り、JEPXで売却する（従来の標準動作）",
    "self_consumption_only": "自家消費できる分だけ調達する（余剰は買い取らず・売らない）",
}


def apply_jepx_shift(
    jepx_by_month_hour: dict,
    jepx_actual_series: Optional[pd.Series],
    shift_yen_per_kwh: float,
) -> tuple[dict, Optional[pd.Series]]:
    """JEPX想定単価（月×時間帯の目安値・実績の両方）に一律の加減額（円/kWh）を加える。価格は0円未満にしない。"""
    if not shift_yen_per_kwh:
        return jepx_by_month_hour, jepx_actual_series
    shifted = {k: max(v + shift_yen_per_kwh, 0.0) for k, v in jepx_by_month_hour.items()}
    actual = None if jepx_actual_series is None else (jepx_actual_series + shift_yen_per_kwh).clip(lower=0.0)
    return shifted, actual


def build_supply_and_balance(
    design: dict,
    demand_df: pd.DataFrame,
    uploaded_df: Optional[pd.DataFrame] = None,
    sources: Optional[list] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    供給データ（アップロード分＋パラメータ設定電源）から、調達比率・余剰の扱い（surplus_mode）を反映した
    供給DataFrameと、30分コマの需給バランスを作る。試算結果ページとシナリオ比較で共通に使う。
    """
    ts = pd.DatetimeIndex(demand_df["datetime"].sort_values().unique())
    parts = []
    if uploaded_df is not None and not uploaded_df.empty:
        parts.append(uploaded_df)
    if sources:
        parts.append(supply_planner.combine_supply_profiles(sources, ts))
    supply_df = (
        pd.concat(parts, ignore_index=True) if parts
        else pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
    )
    supply_df = supply_planner.apply_procurement_ratios(supply_df, design.get("procurement_ratios", {}))
    if design.get("surplus_mode", "buy_and_sell") == "self_consumption_only":
        supply_df = supply_planner.cap_supply_to_demand(supply_df, demand_df)
    return supply_df, financial_model.calc_balance(demand_df, supply_df)


def run_scenario(
    scenario: Scenario,
    demand_df: pd.DataFrame,
    jepx_actual_series: Optional[pd.Series] = None,
    fallback_supply_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    シナリオの前提条件で retail_fs.run_fs を実行し、その戻り値（{"monthly","annual",...,"warnings"}）を返す。

    jepx_actual_series  : 読み込み済みJEPX実績（datetime→円/kWh）。試算結果ページと同じ条件にするため渡す
    fallback_supply_df  : シナリオに保存した供給データのキャッシュが無い（再起動で消えた等）場合に使う、
                          現在読み込み中の供給データ。selected_supply_names があればその電源だけを使う
    施設設定（facility_configs）に無い施設の需要は、売上・託送だけでなく需給バランスからも除く。
    """
    design = scenario.fs_design
    warnings: list[str] = []

    tariff_plans = [retail_fs.TariffPlan(**p) for p in design.get("tariff_plans", [])] or retail_fs.default_tariff_plans()
    facility_configs = [retail_fs.FacilityConfig(**c) for c in design.get("facility_configs", [])]
    transmission_rates = {
        vc: retail_fs.TransmissionRate(**r) for vc, r in design.get("transmission_rates", {}).items()
    } or retail_fs.default_transmission_rates()

    jepx_by_month_hour = {
        tuple(int(x) for x in k.split("-")): v
        for k, v in design.get("jepx_by_month_hour", {}).items()
    } or financial_model.DEFAULT_JEPX_PRICE_BY_MONTH_HOUR
    jepx_by_month_hour, jepx_actual_series = apply_jepx_shift(
        jepx_by_month_hour, jepx_actual_series, float(design.get("jepx_shift_yen_per_kwh", 0.0) or 0.0)
    )

    if facility_configs:
        names = {c.facility_name for c in facility_configs}
        scoped = demand_df[demand_df["facility_name"].isin(names)]
        if scoped.empty:
            warnings.append("施設設定に含まれる施設の需要データが現在のデータにありません。")
        else:
            demand_df = scoped

    uploaded_df = None
    if scenario.supply_data_cache_id:
        try:
            uploaded_df = supply_cache_manager.load(scenario.supply_data_cache_id)
        except Exception:
            uploaded_df = None
    if uploaded_df is None and fallback_supply_df is not None:
        uploaded_df = fallback_supply_df
        if scenario.supply_data_cache_id:
            warnings.append("保存済みの供給データが見つからないため、現在読み込み中の供給データを使いました。")
    if uploaded_df is not None and scenario.selected_supply_names:
        uploaded_df = uploaded_df[uploaded_df["source_name"].isin(scenario.selected_supply_names)]
    if uploaded_df is None and not scenario.supply_sources and (
        scenario.supply_data_cache_id or scenario.selected_supply_names
    ):
        warnings.append("供給データが読み込まれていないため、全量をJEPXから調達する前提で計算しました。")

    sources = [supply_planner.SupplySource(**s) for s in scenario.supply_sources]
    supply_df, balance_df = build_supply_and_balance(design, demand_df, uploaded_df, sources)

    result = retail_fs.run_fs(
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
        jepx_actual_series=jepx_actual_series,
        sga_items=design.get("sga_items", {}),
        corporate_tax_rate_pct=design.get("corporate_tax_rate_pct", retail_fs.DEFAULT_CORPORATE_TAX_RATE_PCT),
        market_indexed_sources=design.get("market_indexed_sources", {}),
    )
    if not design.get("sga_items") or sum(design.get("sga_items", {}).values()) == 0:
        warnings.append("販管費が0円のため、営業利益・純利益は過大です（粗利益で比較してください）。")
    if not design.get("capacity_unit_yen_per_kw_year"):
        warnings.append("容量拠出金の単価が0円のため、売上原価が過小です。")
    result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# JSONバックアップ（書き出し／読み込み）
# Community Cloud等は再起動で /tmp が消えるため、シナリオを手元に退避・復元できるようにする。
# ---------------------------------------------------------------------------

def scenarios_to_json(scenarios: list[Scenario]) -> str:
    return json.dumps([asdict(s) for s in scenarios], ensure_ascii=False, indent=2)


def scenarios_from_json(text: str) -> list[Scenario]:
    """バックアップJSONからシナリオを復元する。形式が違う場合は ValueError。"""
    try:
        data = json.loads(text)
        return [Scenario(**d) for d in data]
    except Exception as e:
        raise ValueError(f"シナリオのJSONを読み込めませんでした: {e}") from e


def import_scenarios(scenarios: list[Scenario]) -> int:
    """同名は上書きしてまとめて保存する。保存した件数を返す。"""
    for sc in scenarios:
        save_scenario(sc)
    return len(scenarios)


def annual_summary(fs_result: dict) -> dict:
    """run_fs()/run_scenario() の結果から 売上高／売上原価／粗利益／当期純利益 の年間累計を返す。"""
    annual = fs_result.get("annual", {}) if fs_result else {}
    return {
        "revenue": float(annual.get("sales_revenue", 0.0)),
        "cost_of_sales": float(annual.get("cost_of_sales", 0.0)),
        "gross_profit": float(annual.get("gross_profit", 0.0)),
        "net_income": float(annual.get("net_income", 0.0)),
        "gross_margin_pct": float(annual.get("gross_margin_pct", 0.0)),
        "market_sale_revenue": float(annual.get("market_sale_revenue", 0.0)),
    }
