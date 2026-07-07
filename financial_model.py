"""
financial_model.py
需給バランスと収支（P&L）を 30 分コマ単位で計算する。
"""

from __future__ import annotations

import pandas as pd

# JEPX スポット市場の時間帯別デフォルト単価（円/kWh）
# 2023〜24 年の目安値（実際の分析には CSV アップロードを推奨）
DEFAULT_JEPX_PRICE_BY_HOUR: dict[int, float] = {
    0: 10.0,  1: 9.5,  2: 9.0,  3: 8.5,  4: 8.5,  5: 9.0,
    6: 12.0,  7: 18.0, 8: 22.0, 9: 20.0, 10: 16.0, 11: 15.0,
    12: 14.0, 13: 13.5, 14: 13.0, 15: 14.0, 16: 17.0, 17: 20.0,
    18: 23.0, 19: 22.0, 20: 20.0, 21: 16.0, 22: 13.0, 23: 11.0,
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
    retail_price_yen: float = 25.0,
    jepx_price_by_hour: dict[int, float] | None = None,
    surplus_sell_price_yen: float = 7.0,
    inbalance_factor_pct: float = 10.0,
    inbalance_premium_yen: float = 3.0,
) -> pd.DataFrame:
    """
    30 分コマ単位の収支を計算する。

    Parameters
    ----------
    source_costs         : {電源名: 円/kWh}
    retail_price_yen     : 小売単価（円/kWh）
    jepx_price_by_hour   : 時間帯別 JEPX 単価（省略時はデフォルト値）
    surplus_sell_price_yen : 余剰売電単価（円/kWh）
    inbalance_factor_pct : 調達量のうちインバランスになる割合（%）
    inbalance_premium_yen: インバランスの追加コスト（円/kWh）
    """
    jepx = jepx_price_by_hour or DEFAULT_JEPX_PRICE_BY_HOUR
    df   = balance_df.copy()
    df["hour"]       = df["datetime"].dt.hour
    df["jepx_price"] = df["hour"].map(jepx)

    # ── 収入 ──────────────────────────────────────────────
    df["retail_revenue"]  = df["demand_kwh"] * retail_price_yen
    df["surplus_revenue"] = df["surplus_kwh"] * surplus_sell_price_yen

    # ── 自社発電コスト ────────────────────────────────────
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

    # ── 利益 ─────────────────────────────────────────────
    df["profit"] = (
        df["retail_revenue"] + df["surplus_revenue"]
        - df["gen_cost"] - df["procurement_cost"] - df["inbalance_cost"]
    )

    return df.drop(columns=["hour", "jepx_price"]).reset_index(drop=True)


def monthly_pnl_summary(pnl_df: pd.DataFrame) -> pd.DataFrame:
    """月別 P&L サマリー。"""
    df = pnl_df.copy()
    df["month"] = df["datetime"].dt.to_period("M").dt.to_timestamp()
    cols = [
        "retail_revenue", "surplus_revenue", "gen_cost",
        "procurement_cost", "inbalance_cost", "profit",
        "demand_kwh", "total_supply_kwh", "surplus_kwh", "deficit_kwh",
    ]
    return (
        df.groupby("month", as_index=False)[[c for c in cols if c in df.columns]]
        .sum()
    )


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
