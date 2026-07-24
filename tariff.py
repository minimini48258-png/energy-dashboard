"""
tariff.py
中部電力ミライズの料金設計をベースにした小売単価モデル。
施設ごとに高圧（業務用電力）／低圧（従量電灯B）を選択し、
基本料金・電力量料金・燃料費調整・再エネ発電促進賦課金を月次で計算する。

出典（2026年7月 Web調査、いずれも※要確認。実際の契約単価は
中部電力ミライズ公式サイトの最新料金表・燃料費調整単価PDFで都度確認すること）:
  - 高圧業務用電力(FRプラン相当)
    https://miraiz.chuden.co.jp/business/electric/menu/pricelist/office/hi_under/
    基本料金 約1,716.26〜2,002.26円/kW、電力量料金 夏季 約18.97〜20.30円/kWh、
    その他季 約18.00〜19.21円/kWh（メニューにより幅あり。ここでは代表値=中間値を採用）
  - 従量電灯B
    （enegent.jp 等の料金表まとめ記事、2026年5月時点）
    基本料金 32.114円/A（30A=963.42円、40A=1,284.56円）
    電力量料金 第1段階(〜120kWh)21.20円/kWh、第2段階(120〜300kWh)25.67円/kWh、
    第3段階(300kWh超)28.62円/kWh
  - 再エネ発電促進賦課金
    経済産業省公表、2026年5月〜2027年4月適用: 4.18円/kWh
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

VOLTAGE_CLASSES = ["高圧", "低圧"]

# 高圧の夏季判定月（中部電力の標準的な夏季区分: 7〜9月）
SUMMER_MONTHS = {7, 8, 9}


@dataclass
class TariffPlan:
    """中部電力型の料金メニュー1本分の単価設定。"""

    voltage_class: str  # "高圧" | "低圧"
    plan_name: str = ""

    # 高圧（業務用電力）
    basic_charge_per_kw: float = 1860.0        # 円/kW/月 ※要確認
    energy_charge_summer: float = 19.6         # 円/kWh（夏季 7-9月）※要確認
    energy_charge_other: float = 18.6          # 円/kWh（その他季）※要確認

    # 低圧（従量電灯B）
    basic_charge_per_amp: float = 32.114       # 円/A/月 ※要確認
    tiered_rates: list[tuple[Optional[float], float]] = field(
        default_factory=lambda: [(120.0, 21.20), (300.0, 25.67), (None, 28.62)]
    )  # (上限kWh, 単価円/kWh) を段階順に。最終段は上限None（それ以上すべて）

    # 共通
    fuel_cost_adjustment: float = 0.0          # 円/kWh、月毎に変動するためユーザー入力（デフォルト0）※要確認
    renewable_levy: float = 4.18               # 円/kWh、2026年度（経産省公表）


def CHUBU_HIGH_VOLTAGE_DEFAULT() -> TariffPlan:
    return TariffPlan(voltage_class="高圧", plan_name="高圧業務用電力(FR相当)")


def CHUBU_LOW_VOLTAGE_DEFAULT() -> TariffPlan:
    return TariffPlan(voltage_class="低圧", plan_name="従量電灯B")


@dataclass
class FacilityTariffAssignment:
    facility_name: str
    voltage_class: str = "高圧"     # "高圧" | "低圧"
    contract_kw: float = 50.0       # 高圧の場合の契約電力
    contract_amp: float = 50.0      # 低圧の場合の契約アンペア


def _tiered_energy_charge(total_kwh: float, tiered_rates: list[tuple[Optional[float], float]]) -> float:
    """低圧・月間累積kWhに対する3段階料金を適用した電力量料金（円）を計算する。"""
    remaining = total_kwh
    lower = 0.0
    charge = 0.0
    for upper, price in tiered_rates:
        if remaining <= 0:
            break
        band = (upper - lower) if upper is not None else remaining
        used = min(remaining, band)
        charge += used * price
        remaining -= used
        if upper is not None:
            lower = upper
    return charge


def calc_facility_revenue_monthly(
    demand_df: pd.DataFrame,
    assignments: dict[str, FacilityTariffAssignment],
    plan_high: TariffPlan,
    plan_low: TariffPlan,
) -> pd.DataFrame:
    """
    施設×月ごとの小売収入を、中部電力型の料金設計で計算する。

    Parameters
    ----------
    demand_df : datetime, facility_name, consumption_kwh
    assignments : {facility_name: FacilityTariffAssignment}
    plan_high, plan_low : 高圧/低圧の単価設定

    Returns
    -------
    DataFrame: month, facility_name, voltage_class, kwh,
               basic_charge, energy_charge, fuel_adjustment, renewable_levy,
               revenue_excl_levy（売上高相当＝基本料金＋電力量料金＋燃料費調整。賦課金は含まない）
    """
    df = demand_df.copy()
    df["month"] = df["datetime"].dt.to_period("M").dt.to_timestamp()
    df["cal_month"] = df["datetime"].dt.month

    rows = []
    for facility, monthly_df in df.groupby("facility_name"):
        asg = assignments.get(
            facility, FacilityTariffAssignment(facility_name=facility)
        )
        for month, mdf in monthly_df.groupby("month"):
            kwh = float(mdf["consumption_kwh"].sum())

            if asg.voltage_class == "高圧":
                basic_charge = plan_high.basic_charge_per_kw * asg.contract_kw
                is_summer = mdf["cal_month"].isin(SUMMER_MONTHS)
                energy_charge = (
                    mdf.loc[is_summer, "consumption_kwh"].sum() * plan_high.energy_charge_summer
                    + mdf.loc[~is_summer, "consumption_kwh"].sum() * plan_high.energy_charge_other
                )
                fuel_adj = kwh * plan_high.fuel_cost_adjustment
                levy = kwh * plan_high.renewable_levy
            else:
                basic_charge = plan_low.basic_charge_per_amp * asg.contract_amp
                energy_charge = _tiered_energy_charge(kwh, plan_low.tiered_rates)
                fuel_adj = kwh * plan_low.fuel_cost_adjustment
                levy = kwh * plan_low.renewable_levy

            rows.append({
                "month": month,
                "facility_name": facility,
                "voltage_class": asg.voltage_class,
                "kwh": kwh,
                "basic_charge": basic_charge,
                "energy_charge": energy_charge,
                "fuel_adjustment": fuel_adj,
                "renewable_levy": levy,
                "revenue_excl_levy": basic_charge + energy_charge + fuel_adj,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "month", "facility_name", "voltage_class", "kwh", "basic_charge",
            "energy_charge", "fuel_adjustment", "renewable_levy", "revenue_excl_levy",
        ])
    return pd.DataFrame(rows).sort_values(["month", "facility_name"]).reset_index(drop=True)


def suggest_contract_capacity(demand_df: pd.DataFrame, facility_name: str, voltage_class: str) -> float:
    """施設の実績最大需要(30分値kWh→kW換算)から契約電力/契約アンペアの目安値を提案する。"""
    fac_df = demand_df[demand_df["facility_name"] == facility_name]
    if fac_df.empty:
        return 50.0 if voltage_class == "高圧" else 30.0
    peak_kw = float(fac_df["consumption_kwh"].max()) * 2.0  # 30分値kWh → kW
    if voltage_class == "高圧":
        return float(max(round(peak_kw * 1.1), 5))
    # 低圧は契約アンペアの一般的な刻み（10A単位）に丸める
    est_amp = peak_kw * 1000 / 100.0  # 100V換算の簡易目安
    return float(max(round(est_amp / 10) * 10, 20))
