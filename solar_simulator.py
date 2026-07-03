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

# 充放電モードの表示名
BATTERY_MODE_LABELS: dict[str, str] = {
    "basic":     "🔋 自家消費優先（基本）",
    "reserve":   "🚨 防災バッファ付き",
    "peak_cut":  "⚡ ピークカット",
}


def _solar_kwh_per_kwp(hour_float: float, month: int) -> float:
    """kWp あたりの発電量（kWh/30分枠）を返す。正弦波近似＋月別PSHで正規化。"""
    sr = _SUNRISE[month]
    ss = _SUNSET[month]
    if hour_float < sr or hour_float >= ss:
        return 0.0
    daylight_h = ss - sr
    peak_kw = _DAILY_PSH[month] * np.pi / (2.0 * daylight_h)
    progress = (hour_float - sr) / daylight_h
    return float(peak_kw * np.sin(np.pi * progress) * 0.5)


def auto_peak_threshold_kw(df: pd.DataFrame) -> float:
    """需要の80パーセンタイルをデマンド閾値（kW）として返す。"""
    agg = df.groupby("datetime", as_index=False)["consumption_kwh"].sum()
    return round(float(agg["consumption_kwh"].quantile(0.80)) * 2, 1)


def run_simulation(
    df: pd.DataFrame,
    solar_capacity_kw: float,
    battery_capacity_kwh: float,
    battery_efficiency: float = 0.95,
    panel_pr: float = 0.85,
    mode: str = "basic",
    min_soc_pct: float = 30.0,
    peak_threshold_kw: float | None = None,
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
    mode : 充放電モード
        "basic"    — 余剰太陽光で充電・不足時に自動放電（デフォルト）
        "reserve"  — 防災バッファ付き。min_soc_pct 以上を常時確保。
        "peak_cut" — デマンドが peak_threshold_kw を超えたときのみ放電。
    min_soc_pct : reserve モードで確保する最低残量 (%)
    peak_threshold_kw : peak_cut モードのデマンド閾値 (kW)。None で自動計算。

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

    eta = float(battery_efficiency) ** 0.5  # 片道効率

    # モード別の事前計算
    reserve_floor_kwh = (
        battery_capacity_kwh * min_soc_pct / 100.0 if mode == "reserve" else 0.0
    )
    if mode == "peak_cut":
        if peak_threshold_kw is None:
            peak_threshold_kw = auto_peak_threshold_kw(df)
        # kW → kWh/30min スロット
        peak_threshold_slot = peak_threshold_kw / 2.0
    else:
        peak_threshold_slot = 0.0

    soc = 0.0
    records: list[dict] = []

    for _, row in agg.iterrows():
        dt = row["datetime"]
        demand = float(row["consumption_kwh"])
        hour_f = dt.hour + dt.minute / 60.0
        month = int(dt.month)

        solar = solar_capacity_kw * _solar_kwh_per_kwp(hour_f, month) * panel_pr

        # ── 自家消費（太陽光直接使用）──────────────────────────────────────
        direct_use = min(solar, demand)
        surplus = solar - direct_use   # 余剰太陽光 (kWh)
        deficit = demand - direct_use  # 残需要 (kWh)

        # ── 余剰 → 蓄電池チャージ（全モード共通：太陽光余剰のみ充電）──────
        if battery_capacity_kwh > 0 and surplus > 0:
            space = battery_capacity_kwh - soc
            max_ac_in = space / eta if eta > 0 else 0.0
            charge_ac = min(surplus, max_ac_in)
            charge_stored = charge_ac * eta
            soc = min(soc + charge_stored, battery_capacity_kwh)
            grid_export = surplus - charge_ac
        else:
            charge_stored = 0.0
            grid_export = surplus

        # ── 不足 → 蓄電池放電（モード別）──────────────────────────────────
        if battery_capacity_kwh > 0 and deficit > 0:
            # 放電可能な SOC（reserve モード: フロアを除いた分のみ使用可）
            usable_soc = max(0.0, soc - reserve_floor_kwh)

            # 放電量の目標（peak_cut: 閾値超過分のみ / その他: deficit 全量）
            if mode == "peak_cut":
                discharge_needed = max(0.0, deficit - peak_threshold_slot)
            else:
                discharge_needed = deficit

            max_ac_out = usable_soc * eta
            discharge_ac = min(discharge_needed, max_ac_out)
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


def sweep_battery_capacity(
    df: pd.DataFrame,
    solar_capacity_kw: float,
    battery_efficiency: float = 0.95,
    panel_pr: float = 0.85,
    mode: str = "basic",
    min_soc_pct: float = 30.0,
    peak_threshold_kw: float | None = None,
    n_steps: int = 12,
) -> tuple[pd.DataFrame, float]:
    """
    蓄電池容量を変えてシミュレーションし、自家消費率・自給率の変化を返す。

    peak_cut モードのとき peak_threshold_kw が None なら自動計算し固定値として使用。

    Returns
    -------
    sweep_df : battery_kwh, self_consumption_rate, self_sufficiency_rate の DataFrame
    recommended_kwh : 推奨蓄電池容量 (kWh)
    """
    # peak_cut の閾値を先に確定（全ステップで同じ値を使う）
    if mode == "peak_cut" and peak_threshold_kw is None:
        peak_threshold_kw = auto_peak_threshold_kw(df)

    # 蓄電池なしで1回シミュレーションし、日次余剰電力を推定
    sim0 = run_simulation(
        df, solar_capacity_kw, 0, battery_efficiency, panel_pr,
        mode, min_soc_pct, peak_threshold_kw,
    )
    n_days = max(1, (sim0["datetime"].max() - sim0["datetime"].min()).days)
    daily_surplus = (
        float(sim0["solar_kwh"].sum()) - float(sim0["direct_use_kwh"].sum())
    ) / n_days

    if daily_surplus <= 0:
        # 太陽光が需要より少ない場合は単純スイープ（solar容量ベース）
        daily_surplus = solar_capacity_kw * 3.0 / n_steps

    # テスト容量リスト: 0 から 日次余剰 × 2.5 まで
    max_cap = daily_surplus * 2.5
    step_vals = np.linspace(daily_surplus * 0.15, max_cap, n_steps - 1)
    capacities = [0.0] + [round(float(v), 1) for v in step_vals]

    results = []
    for cap in capacities:
        sim = run_simulation(
            df, solar_capacity_kw, cap, battery_efficiency, panel_pr,
            mode, min_soc_pct, peak_threshold_kw,
        )
        kpis = calc_kpis(sim)
        results.append({
            "battery_kwh": cap,
            "self_consumption_rate": kpis["self_consumption_rate"],
            "self_sufficiency_rate": kpis["self_sufficiency_rate"],
        })

    sweep_df = pd.DataFrame(results)
    recommended_kwh = _find_elbow(sweep_df)
    return sweep_df, recommended_kwh


def _find_elbow(sweep_df: pd.DataFrame) -> float:
    """
    自給率カーブの肘（限界効果逓減点）を探す。
    10 kWh あたりの自給率改善が 0.5% 未満になった最初の手前の容量を返す。
    """
    for i in range(1, len(sweep_df)):
        delta_rate = (
            sweep_df["self_sufficiency_rate"].iloc[i]
            - sweep_df["self_sufficiency_rate"].iloc[i - 1]
        )
        delta_cap = (
            sweep_df["battery_kwh"].iloc[i] - sweep_df["battery_kwh"].iloc[i - 1]
        )
        if delta_cap > 0 and (delta_rate / delta_cap * 10) < 0.5:
            return float(sweep_df["battery_kwh"].iloc[i - 1])
    return float(sweep_df["battery_kwh"].iloc[-1])
