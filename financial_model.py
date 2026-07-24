"""
financial_model.py
需給バランスと収支（P&L）を 30 分コマ単位で計算する。

小売収入は tariff.py の中部電力型料金設計（施設別・月次）で計算し、
本モジュールでは JEPX調達コスト・自社発電コスト・インバランスコスト・
余剰売電収入を 30 分コマ単位で積み上げる。
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


def calc_pnl(
    balance_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    source_costs: dict[str, float],
    jepx_price_by_month_hour: dict[tuple[int, int], float] | None = None,
    jepx_actual_series: pd.Series | None = None,
    surplus_sell_price_yen: float = 7.0,
    inbalance_factor_pct: float = 10.0,
    inbalance_premium_yen: float = 3.0,
) -> pd.DataFrame:
    """
    30 分コマ単位のコスト・余剰売電収入を計算する（小売収入は含まない。
    小売収入は tariff.calc_facility_revenue_monthly で月次・施設別に計算し、
    monthly_pnl_summary で合算する）。

    Parameters
    ----------
    source_costs            : {電源名: 円/kWh}（相対電源は相対契約単価として扱う）
    jepx_price_by_month_hour: {(月, 時): 円/kWh}（省略時はデフォルト値）
    jepx_actual_series      : 実績JEPX価格（datetime→円/kWh）。値がある30分コマは
                              こちらを優先し、欠損コマはデフォルト/手動設定値を使う
    surplus_sell_price_yen  : 余剰売電単価（円/kWh）
    inbalance_factor_pct    : 調達量のうちインバランスになる割合（%）
    inbalance_premium_yen   : インバランスの追加コスト（円/kWh）
    """
    jepx_table = jepx_price_by_month_hour or DEFAULT_JEPX_PRICE_BY_MONTH_HOUR
    df = balance_df.copy()
    df["month"] = df["datetime"].dt.month
    df["hour"]  = df["datetime"].dt.hour
    df["jepx_price"] = [
        jepx_table.get((m, h), 15.0) for m, h in zip(df["month"], df["hour"])
    ]

    if jepx_actual_series is not None and not jepx_actual_series.empty:
        actual_vals = df["datetime"].map(jepx_actual_series)
        df["jepx_price"] = actual_vals.combine_first(df["jepx_price"])

    # ── 余剰売電収入 ──────────────────────────────────────
    df["surplus_revenue"] = df["surplus_kwh"] * surplus_sell_price_yen

    # ── 自社発電・相対電源コスト ────────────────────────────
    if not supply_df.empty and source_costs:
        gen_cost = (
            supply_df.assign(
                cost=lambda x: x.apply(
                    lambda r: r["supply_kwh"] * source_costs.get(r["source_name"], 0.0),
                    axis=1,
                )
            )
            .groupby("datetime", as_index=False)["cost"]
            .sum()
            .rename(columns={"cost": "gen_cost"})
        )
        df = pd.merge(df, gen_cost, on="datetime", how="left")
        df["gen_cost"] = df["gen_cost"].fillna(0)
    else:
        df["gen_cost"] = 0.0

    # ── JEPX 調達コスト ───────────────────────────────────
    df["procurement_cost"] = df["deficit_kwh"] * df["jepx_price"]

    # ── インバランスコスト ─────────────────────────────────
    df["inbalance_kwh"]  = df["deficit_kwh"] * (inbalance_factor_pct / 100.0)
    df["inbalance_cost"] = df["inbalance_kwh"] * inbalance_premium_yen

    return df.drop(columns=["month", "hour", "jepx_price"]).reset_index(drop=True)


def monthly_pnl_summary(
    pnl_df: pd.DataFrame,
    facility_revenue_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    月別 P&L サマリー。facility_revenue_monthly（tariff.calc_facility_revenue_monthly の
    出力）を渡すと、小売収入（売上高）・再エネ賦課金・売上原価・粗利益を合算する。
    """
    df = pnl_df.copy()
    df["month"] = df["datetime"].dt.to_period("M").dt.to_timestamp()
    cost_cols = [
        "gen_cost", "procurement_cost", "inbalance_cost", "surplus_revenue",
        "demand_kwh", "total_supply_kwh", "surplus_kwh", "deficit_kwh",
    ]
    monthly = df.groupby("month", as_index=False)[[c for c in cost_cols if c in df.columns]].sum()
    monthly["cost_of_sales"] = (
        monthly["gen_cost"] + monthly["procurement_cost"] + monthly["inbalance_cost"]
        - monthly.get("surplus_revenue", 0.0)
    )

    if facility_revenue_monthly is not None and not facility_revenue_monthly.empty:
        rev = (
            facility_revenue_monthly.groupby("month", as_index=False)[["revenue_excl_levy", "renewable_levy"]]
            .sum()
            .rename(columns={"revenue_excl_levy": "revenue"})
        )
        monthly = pd.merge(monthly, rev, on="month", how="outer")
        monthly[["revenue", "renewable_levy"]] = monthly[["revenue", "renewable_levy"]].fillna(0.0)
        for c in cost_cols:
            if c in monthly.columns:
                monthly[c] = monthly[c].fillna(0.0)
        monthly["cost_of_sales"] = monthly["cost_of_sales"].fillna(0.0)
    else:
        monthly["revenue"] = 0.0
        monthly["renewable_levy"] = 0.0

    monthly["gross_profit"] = monthly["revenue"] - monthly["cost_of_sales"]
    monthly["profit"] = monthly["gross_profit"]  # 既存UI互換（事業利益表示）

    return monthly.sort_values("month").reset_index(drop=True)


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
