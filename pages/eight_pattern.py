"""
pages/eight_pattern.py
8パターン分析：季節（春夏秋冬）×平日/休日の組み合わせごとに、
同じ時間帯の実績を平均した「代表的な1日」の需給バランスを比較する。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import analyzer
import common
import financial_model
import supply_planner
import visualizer

st.title("📅 8パターン分析")
st.caption(
    "季節（春夏秋冬）×平日/休日の組み合わせごとに、同じ時間帯の実績を平均した"
    "「代表的な1日」の需給バランス（30分値）を並べて比較します。"
)

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

_uploaded = st.session_state.get("supply_df")
_supply_parts = []
if _uploaded is not None:
    _sel = st.session_state.get("selected_supply_names", [])
    _filtered_upload = _uploaded[_uploaded["source_name"].isin(_sel)] if _sel else _uploaded
    _supply_parts.append(_filtered_upload)
_sources = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

if not _supply_parts and not _sources:
    st.info(
        "供給データがありません。\n\n"
        "- **実データ**: 「データ読み込み」ページから Excel をアップロード\n"
        "- **推計値**: 「電源管理」ページでパラメータ設定"
    )
    st.stop()

_ts = pd.DatetimeIndex(filtered_base["datetime"].sort_values().unique())
_supply_parts_all = list(_supply_parts)
if _sources:
    _supply_parts_all.append(supply_planner.combine_supply_profiles(_sources, _ts))
supply_df = (
    pd.concat(_supply_parts_all, ignore_index=True) if _supply_parts_all
    else pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
)
source_names = sorted(supply_df["source_name"].unique().tolist()) if not supply_df.empty else []

# ── 季節・平日/休日の付与 ──────────────────────────────────────────────
_demand_total = filtered_base.groupby("datetime", as_index=False)["consumption_kwh"].sum()
_demand_total["season"] = analyzer.assign_season(_demand_total["datetime"])
_demand_total["day_type"] = analyzer.assign_day_type(_demand_total["datetime"])
_demand_total["hour"] = _demand_total["datetime"].dt.hour
_demand_total["minute"] = _demand_total["datetime"].dt.minute

_supply_work = supply_df.copy()
if not _supply_work.empty:
    _supply_work["season"] = analyzer.assign_season(_supply_work["datetime"])
    _supply_work["day_type"] = analyzer.assign_day_type(_supply_work["datetime"])
    _supply_work["hour"] = _supply_work["datetime"].dt.hour
    _supply_work["minute"] = _supply_work["datetime"].dt.minute

_SEASONS = ["春", "夏", "秋", "冬"]
_DAY_TYPES = ["平日", "休日"]
_BASE_DATE = pd.Timestamp("2000-01-01")


def _representative_day(season: str, day_type: str) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """季節×平日/休日に該当する実績を時刻ごとに平均し、代表的な1日分のdemand/supplyを作る。"""
    d = _demand_total[(_demand_total["season"] == season) & (_demand_total["day_type"] == day_type)]
    n_days = d["datetime"].dt.date.nunique()

    d_rep = d.groupby(["hour", "minute"], as_index=False)["consumption_kwh"].mean()
    d_rep["datetime"] = _BASE_DATE + pd.to_timedelta(d_rep["hour"], unit="h") + pd.to_timedelta(d_rep["minute"], unit="m")
    d_rep["facility_name"] = "代表日"
    d_rep = d_rep[["datetime", "facility_name", "consumption_kwh"]].sort_values("datetime").reset_index(drop=True)

    if _supply_work.empty:
        s_rep = pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
    else:
        s = _supply_work[(_supply_work["season"] == season) & (_supply_work["day_type"] == day_type)]
        s_rep = s.groupby(["source_name", "hour", "minute"], as_index=False)["supply_kwh"].mean()
        s_rep["datetime"] = _BASE_DATE + pd.to_timedelta(s_rep["hour"], unit="h") + pd.to_timedelta(s_rep["minute"], unit="m")
        s_rep = s_rep[["datetime", "source_name", "supply_kwh"]].sort_values("datetime").reset_index(drop=True)

    return d_rep, s_rep, n_days


for season in _SEASONS:
    st.markdown(f"### {season}")
    cols = st.columns(2)
    for day_type, col in zip(_DAY_TYPES, cols):
        d_rep, s_rep, n_days = _representative_day(season, day_type)
        with col:
            if d_rep.empty or d_rep["consumption_kwh"].isna().all():
                st.info(f"{season}・{day_type}：データがありません。")
                continue
            balance_df = financial_model.calc_balance(d_rep, s_rep)
            kpis = financial_model.calc_balance_kpis(balance_df)
            st.caption(f"{day_type}（{n_days}日の平均）")
            k1, k2, k3 = st.columns(3)
            k1.metric("総需要", f"{kpis['total_demand_kwh']:,.0f} kWh")
            k2.metric("自給率", f"{kpis['self_sufficiency_pct']:.1f} %")
            k3.metric("不足", f"{kpis['deficit_kwh']:,.0f} kWh")
            fig = visualizer.supply_demand_balance_chart(
                balance_df, source_names, title=f"{season}・{day_type}の代表的な1日",
            )
            fig.update_xaxes(tickformat="%H:%M", title="時刻")
            st.plotly_chart(fig, use_container_width=True)
    st.markdown("---")
