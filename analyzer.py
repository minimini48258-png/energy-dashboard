"""
analyzer.py
クリーン済みの標準 DataFrame から各種集計・分析を行う。
"""

from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------------------
# フィルタリング
# ---------------------------------------------------------------------------

def filter_by_period(
    df: pd.DataFrame,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
) -> pd.DataFrame:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    return df[(df["datetime"] >= start) & (df["datetime"] <= end)].copy()


def filter_by_facilities(df: pd.DataFrame, facilities: list[str]) -> pd.DataFrame:
    return df[df["facility_name"].isin(facilities)].copy()


# ---------------------------------------------------------------------------
# 基本統計
# ---------------------------------------------------------------------------

def summary_stats(df: pd.DataFrame) -> dict[str, float]:
    """表示期間内の積算・最大・平均・最小を返す。"""
    s = df["consumption_kwh"]
    return {
        "total_kwh": round(float(s.sum()), 2),
        "max_kwh": round(float(s.max()), 4),
        "mean_kwh": round(float(s.mean()), 4),
        "min_kwh": round(float(s.min()), 4),
    }


# ---------------------------------------------------------------------------
# 時系列集計
# ---------------------------------------------------------------------------

def aggregate_30min(df: pd.DataFrame, by_facility: bool = True) -> pd.DataFrame:
    """30 分値のまま、施設別または全施設合算で返す。"""
    if by_facility:
        return (
            df.groupby(["datetime", "facility_name"], as_index=False)["consumption_kwh"]
            .sum()
            .sort_values("datetime")
        )
    return (
        df.groupby("datetime", as_index=False)["consumption_kwh"]
        .sum()
        .sort_values("datetime")
        .assign(facility_name="全施設合計")
    )


def aggregate_30min_by_group(df: pd.DataFrame) -> pd.DataFrame:
    """group_label 列でグループ集計した 30 分値を返す（visualizer 互換: facility_name 列に変換）。"""
    if "group_label" not in df.columns:
        return aggregate_30min(df, by_facility=False)
    return (
        df.groupby(["datetime", "group_label"], as_index=False)["consumption_kwh"]
        .sum()
        .rename(columns={"group_label": "facility_name"})
        .sort_values("datetime")
    )


def aggregate_daily(df: pd.DataFrame, by_facility: bool = False) -> pd.DataFrame:
    """日別使用量（kWh/日）。"""
    df = df.copy()
    df["date"] = df["datetime"].dt.date
    group_cols = ["date", "facility_name"] if by_facility else ["date"]
    agg = df.groupby(group_cols, as_index=False)["consumption_kwh"].sum()
    agg["date"] = pd.to_datetime(agg["date"])
    return agg.sort_values("date")


def aggregate_monthly(df: pd.DataFrame, by_facility: bool = False) -> pd.DataFrame:
    """月別使用量（kWh/月）。"""
    df = df.copy()
    df["month"] = df["datetime"].dt.to_period("M").dt.to_timestamp()
    group_cols = ["month", "facility_name"] if by_facility else ["month"]
    return df.groupby(group_cols, as_index=False)["consumption_kwh"].sum().sort_values("month")


def aggregate_hourly_avg(df: pd.DataFrame, by_facility: bool = False) -> pd.DataFrame:
    """時間帯別平均使用量（kWh/30分）。0〜23 時。"""
    df = df.copy()
    df["hour"] = df["datetime"].dt.hour
    group_cols = ["hour", "facility_name"] if by_facility else ["hour"]
    return (
        df.groupby(group_cols, as_index=False)["consumption_kwh"]
        .mean()
        .sort_values("hour")
    )


# ---------------------------------------------------------------------------
# パターン分析
# ---------------------------------------------------------------------------

def weekday_vs_holiday(df: pd.DataFrame) -> pd.DataFrame:
    """平日・休日別の時間帯平均を返す。"""
    df = df.copy()
    df["hour"] = df["datetime"].dt.hour
    df["day_type"] = df["datetime"].dt.dayofweek.apply(
        lambda d: "休日" if d >= 5 else "平日"
    )
    return (
        df.groupby(["hour", "day_type"], as_index=False)["consumption_kwh"]
        .mean()
        .sort_values(["hour", "day_type"])
    )


def facility_annual_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """施設ごとの年間使用量ランキング。"""
    return (
        df.groupby("facility_name", as_index=False)["consumption_kwh"]
        .sum()
        .rename(columns={"consumption_kwh": "annual_kwh"})
        .sort_values("annual_kwh", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 需給バランス
# ---------------------------------------------------------------------------

def calc_supply_demand_balance(
    demand_df: pd.DataFrame,
    supply_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    demand_df: datetime, consumption_kwh（需要側 30 分値合計）
    supply_df: datetime, solar_kwh, battery_kwh, market_kwh, other_kwh

    Returns merged DataFrame with surplus/deficit columns.
    """
    demand = (
        demand_df.groupby("datetime", as_index=False)["consumption_kwh"]
        .sum()
        .rename(columns={"consumption_kwh": "demand_kwh"})
    )
    merged = pd.merge(demand, supply_df, on="datetime", how="outer").sort_values("datetime")

    supply_cols = [c for c in ["solar_kwh", "battery_kwh", "market_kwh", "other_kwh"] if c in merged.columns]
    merged[supply_cols] = merged[supply_cols].fillna(0)
    merged["demand_kwh"] = merged["demand_kwh"].fillna(0)

    merged["total_supply_kwh"] = merged[supply_cols].sum(axis=1)
    merged["surplus_kwh"] = (merged["total_supply_kwh"] - merged["demand_kwh"]).clip(lower=0)
    merged["deficit_kwh"] = (merged["demand_kwh"] - merged["total_supply_kwh"]).clip(lower=0)
    return merged


def supply_mix_summary(balance_df: pd.DataFrame) -> pd.DataFrame:
    """電源構成比（kWh・割合）を返す。"""
    supply_cols = [c for c in ["solar_kwh", "battery_kwh", "market_kwh", "other_kwh"] if c in balance_df.columns]
    label_map = {
        "solar_kwh": "太陽光",
        "battery_kwh": "蓄電池",
        "market_kwh": "市場調達",
        "other_kwh": "その他",
    }
    totals = balance_df[supply_cols].sum()
    total_sum = totals.sum()
    rows = []
    for col in supply_cols:
        kwh = float(totals[col])
        rows.append({
            "source": label_map.get(col, col),
            "kwh": round(kwh, 2),
            "ratio": round(kwh / total_sum * 100, 1) if total_sum > 0 else 0.0,
        })
    return pd.DataFrame(rows)
