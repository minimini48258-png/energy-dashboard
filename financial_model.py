"""
financial_model.py
需給バランス（30分コマ単位）を計算する。
収支（P&L）試算は retail_fs.py に統合されている。
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# JEPX スポット市場のデフォルト単価（月×時間帯）
#
# 出典・前提（※要確認。実際の分析には実績CSVアップロードを推奨）:
#   - 時間帯形状: 深夜安・朝夕ピークという典型的な日内カーブ（旧デフォルト値を正規化）
#   - 月別水準: 2026年7月時点のJEPXシステムプライス週平均 約19.09円/kWh
#     （新電力ネット pps-net.org 調べ、2026/7/19週）を7月の水準として採用し、
#     一般的に知られる季節傾向（冬季1〜2月・夏季7〜8月が高め、春秋の中間期が
#     安め）に沿って他月の水準を按分した目安値。中部エリア固有の値ではなく
#     全国システムプライス感の推計であり、精緻な分析には実績データを使うこと。
# ---------------------------------------------------------------------------

_HOURLY_SHAPE_RAW: dict[int, float] = {
    0: 10.0, 1: 9.5, 2: 9.0, 3: 8.5, 4: 8.5, 5: 9.0,
    6: 12.0, 7: 18.0, 8: 22.0, 9: 20.0, 10: 16.0, 11: 15.0,
    12: 14.0, 13: 13.5, 14: 13.0, 15: 14.0, 16: 17.0, 17: 20.0,
    18: 23.0, 19: 22.0, 20: 20.0, 21: 16.0, 22: 13.0, 23: 11.0,
}
_HOURLY_SHAPE_MEAN = sum(_HOURLY_SHAPE_RAW.values()) / 24
_HOURLY_RELATIVE: dict[int, float] = {h: v / _HOURLY_SHAPE_MEAN for h, v in _HOURLY_SHAPE_RAW.items()}

# 月別の平均価格水準（円/kWh）※要確認・目安値
_MONTHLY_LEVEL_YEN: dict[int, float] = {
    1: 24.0, 2: 20.0, 3: 16.0, 4: 12.0, 5: 11.0, 6: 13.0,
    7: 19.0, 8: 20.0, 9: 15.0, 10: 12.0, 11: 13.0, 12: 22.0,
}

DEFAULT_JEPX_PRICE_BY_MONTH_HOUR: dict[tuple[int, int], float] = {
    (m, h): round(level * _HOURLY_RELATIVE[h], 2)
    for m, level in _MONTHLY_LEVEL_YEN.items()
    for h in range(24)
}


def calc_balance(
    demand_df: pd.DataFrame,
    supply_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    需給バランスを 30 分コマ単位で計算する。

    Parameters
    ----------
    demand_df : datetime / facility_name / consumption_kwh
    supply_df : datetime / source_name / supply_kwh

    Returns
    -------
    DataFrame: datetime, demand_kwh, <電源別列>, total_supply_kwh, surplus_kwh, deficit_kwh
    """
    demand_total = (
        demand_df.groupby("datetime", as_index=False)["consumption_kwh"]
        .sum()
        .rename(columns={"consumption_kwh": "demand_kwh"})
    )

    if supply_df.empty:
        demand_total["total_supply_kwh"] = 0.0
        demand_total["surplus_kwh"]      = 0.0
        demand_total["deficit_kwh"]      = demand_total["demand_kwh"]
        return demand_total

    supply_pivot = (
        supply_df.pivot_table(
            index="datetime", columns="source_name",
            values="supply_kwh", aggfunc="sum",
        )
        .fillna(0)
        .reset_index()
    )

    merged = pd.merge(demand_total, supply_pivot, on="datetime", how="left")
    source_cols = [c for c in merged.columns if c not in ("datetime", "demand_kwh")]
    merged[source_cols] = merged[source_cols].fillna(0)

    merged["total_supply_kwh"] = merged[source_cols].sum(axis=1)
    merged["surplus_kwh"]  = (merged["total_supply_kwh"] - merged["demand_kwh"]).clip(lower=0)
    merged["deficit_kwh"]  = (merged["demand_kwh"] - merged["total_supply_kwh"]).clip(lower=0)

    return merged.sort_values("datetime").reset_index(drop=True)


def calc_balance_kpis(balance_df: pd.DataFrame) -> dict:
    """需給バランスの主要 KPI を返す。"""
    demand  = float(balance_df["demand_kwh"].sum())
    supply  = float(balance_df["total_supply_kwh"].sum())
    surplus = float(balance_df["surplus_kwh"].sum())
    deficit = float(balance_df["deficit_kwh"].sum())
    return {
        "total_demand_kwh":    round(demand, 1),
        "total_supply_kwh":    round(min(supply, demand), 1),
        "self_sufficiency_pct": round(min(supply, demand) / demand * 100, 1) if demand > 0 else 0.0,
        "surplus_kwh":         round(surplus, 1),
        "deficit_kwh":         round(deficit, 1),
        "deficit_pct":         round(deficit / demand * 100, 1) if demand > 0 else 0.0,
    }
