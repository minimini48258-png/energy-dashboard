"""
solar_simulator.py
太陽光 + 蓄電池 PPA シミュレーション
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 月別ピーク日射時間（h/日）— 上田市（長野県, 36°N）付近の NEDO 概算値
_DAILY_PSH: dict[int, float] = {
    1: 3.5, 2: 4.0, 3: 4.5, 4: 4.8, 5: 5.0, 6: 4.5,
    7: 4.2, 8: 4.8, 9: 4.2, 10: 4.0, 11: 3.5, 12: 3.2,
}

# 月別の日の出・日の入り時刻（概算、上田市 36°N）
_SUNRISE: dict[int, float] = {
    1: 7.0, 2: 6.5, 3: 5.8, 4: 5.0, 5: 4.5, 6: 4.3,
    7: 4.5, 8: 5.2, 9: 5.8, 10: 6.2, 11: 6.8, 12: 7.0,
}
_SUNSET: dict[int, float] = {
    1: 16.8, 2: 17.5, 3: 18.0, 4: 18.5, 5: 19.0, 6: 19.3,
    7: 19.2, 8: 18.7, 9: 17.8, 10: 17.0, 11: 16.5, 12: 16.5,
}


def _solar_kwh_per_kwp(hour_float: float, month: int) -> float:
    """
    kWp あたりの発電量（kWh/30分枠）を返す。
    正弦波近似で日照時間内を配分し、月別 PSH で正規化。
    """
    sr = _SUNRISE[month]
    ss = _SUNSET[month]
    if hour_float < sr or hour_float >= ss:
        return 0.0
    daylight_h = ss - sr
    # 正弦波の積分 = daylight_h * 2/π → ピーク係数を逆算
    peak_kw = _DAILY_PSH[month] * np.pi / (2.0 * daylight_h)
    progress = (hour_float - sr) / daylight_h
    # 0.5h 分の発電量 (kWh) を返す
    return float(peak_kw * np.sin(np.pi * progress) * 0.5)


def run_simulation(
    df: pd.DataFrame,
    solar_capacity_kw: float,
    battery_capacity_kwh: float,
    battery_efficiency: float = 0.95,
    panel_pr: float = 0.85,
) -> pd.DataFrame:
    """
    太陽光 + 蓄電池シミュレーションを実行する。

    Parameters
    ----------
    df : 30分値の需要データ（datetime, consumption_kwh 列が必須）
    solar_capacity_kw : 太陽光パネル容量 (kWp)
    battery_capacity_kwh : 蓄電池容量 (kWh)。0 の場合は蓄電池なし。
    battery_efficiency : 充放電往復効率（デフォルト 0.95）
    panel_pr : パネル性能比（温度・配線損失等、デフォルト 0.85）

    Returns
    -------
    DataFrame with columns:
        datetime, demand_kwh, solar_kwh,
        direct_use_kwh, battery_charge_kwh, battery_discharge_kwh,
        battery_soc_kwh, grid_import_kwh, grid_export_kwh
    """
    agg = (
        df.groupby("datetime", as_index=False)["consumption_kwh"]
        .sum()
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    # 片道効率（往復効率の平方根）
    eta = float(battery_efficiency) ** 0.5

    soc = 0.0
    records: list[dict] = []

    for _, row in agg.iterrows():
        dt = row["datetime"]
        demand = float(row["consumption_kwh"])
        hour_f = dt.hour + dt.minute / 60.0
        month = int(dt.month)

        solar = solar_capacity_kw * _solar_kwh_per_kwp(hour_f, month) * panel_pr

        # 自家消費（太陽光直接使用）
        direct_use = min(solar, demand)
        surplus = solar - direct_use   # 余剰太陽光 (kWh)
        deficit = demand - direct_use  # 残需要 (kWh)

        # 余剰 → 蓄電池チャージ
        if battery_capacity_kwh > 0 and surplus > 0:
            space = battery_capacity_kwh - soc
            # 空き容量に格納するために必要な AC 入力量
            max_ac_in = space / eta if eta > 0 else 0.0
            charge_ac = min(surplus, max_ac_in)
            charge_stored = charge_ac * eta
            soc = min(soc + charge_stored, battery_capacity_kwh)
            grid_export = surplus - charge_ac
        else:
            charge_stored = 0.0
            grid_export = surplus

        # 不足 → 蓄電池放電
        if battery_capacity_kwh > 0 and deficit > 0:
            max_ac_out = soc * eta
            discharge_ac = min(deficit, max_ac_out)
            discharge_stored = discharge_ac / eta if eta > 0 else 0.0
            soc = max(0.0, soc - discharge_stored)
            grid_import = deficit - discharge_ac
        else:
            discharge_ac = 0.0
            grid_import = deficit

        records.append({
            "datetime": dt,
            "demand_kwh": demand,
            "solar_kwh": solar,
            "direct_use_kwh": direct_use,
            "battery_charge_kwh": charge_stored,
            "battery_discharge_kwh": discharge_ac,
            "battery_soc_kwh": soc,
            "grid_import_kwh": grid_import,
            "grid_export_kwh": grid_export,
        })

    return pd.DataFrame(records)


def calc_kpis(sim_df: pd.DataFrame) -> dict:
    """シミュレーション結果から主要 KPI を計算する。"""
    total_solar = float(sim_df["solar_kwh"].sum())
    total_demand = float(sim_df["demand_kwh"].sum())
    total_direct = float(sim_df["direct_use_kwh"].sum())
    total_discharge = float(sim_df["battery_discharge_kwh"].sum())
    total_charge = float(sim_df["battery_charge_kwh"].sum())
    total_grid_import = float(sim_df["grid_import_kwh"].sum())
    total_grid_export = float(sim_df["grid_export_kwh"].sum())

    solar_consumed = total_direct + total_discharge
    self_consumption_rate = solar_consumed / total_solar if total_solar > 0 else 0.0
    self_sufficiency_rate = solar_consumed / total_demand if total_demand > 0 else 0.0
    grid_reduction_kwh = total_demand - total_grid_import
    grid_reduction_rate = grid_reduction_kwh / total_demand if total_demand > 0 else 0.0

    return {
        "total_solar_kwh": round(total_solar, 1),
        "total_demand_kwh": round(total_demand, 1),
        "total_direct_kwh": round(total_direct, 1),
        "total_discharge_kwh": round(total_discharge, 1),
        "total_charge_kwh": round(total_charge, 1),
        "total_grid_import_kwh": round(total_grid_import, 1),
        "total_grid_export_kwh": round(total_grid_export, 1),
        "solar_consumed_kwh": round(solar_consumed, 1),
        "self_consumption_rate": round(self_consumption_rate * 100, 1),
        "self_sufficiency_rate": round(self_sufficiency_rate * 100, 1),
        "grid_reduction_kwh": round(grid_reduction_kwh, 1),
        "grid_reduction_rate": round(grid_reduction_rate * 100, 1),
    }
