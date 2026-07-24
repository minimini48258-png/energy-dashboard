"""
pages/demand_pattern.py
需要パターン分析（月別・時間帯別・平日休日・施設ランキング）。
"""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

import analyzer
import common
import visualizer

st.title("📊 需要パターン分析")

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)
filtered, filtered_base, start_dt, end_dt, agg_mode = common.render_period_and_kpis(
    filtered_base, group_mode, group_df,
)


def _by_fac() -> bool:
    return agg_mode == "施設別"


# ── 分析期間セレクタ（需要カーブの表示期間とは独立） ──
p_col1, p_col2 = st.columns([2, 4])
with p_col1:
    pat_period = st.selectbox(
        "分析期間",
        options=["全データ期間", "直近1年", "直近6か月", "直近3か月", "表示期間と同じ"],
        index=0, key="pat_period",
    )
_bmax = filtered_base["datetime"].max()
_bmin = filtered_base["datetime"].min()
if pat_period == "全データ期間":
    pat_df = filtered_base.copy()
elif pat_period == "直近1年":
    pat_df = analyzer.filter_by_period(filtered_base, _bmax - timedelta(days=365), _bmax)
elif pat_period == "直近6か月":
    pat_df = analyzer.filter_by_period(filtered_base, _bmax - timedelta(days=180), _bmax)
elif pat_period == "直近3か月":
    pat_df = analyzer.filter_by_period(filtered_base, _bmax - timedelta(days=90), _bmax)
else:  # 表示期間と同じ
    pat_df = filtered.copy()

with p_col2:
    st.caption(
        f"分析対象: {pat_df['datetime'].min().strftime('%Y/%m/%d')} 〜 "
        f"{pat_df['datetime'].max().strftime('%Y/%m/%d')}  "
        f"（{len(pat_df):,} 行）"
    )

if pat_df.empty:
    st.warning("選択した分析期間にデータがありません。")
    st.stop()

if "group_label" in pat_df.columns:
    pat_df = pat_df.copy()
    pat_df["facility_name"] = pat_df["group_label"]

by_fac = _by_fac()

col_l, col_r = st.columns(2)
with col_l:
    st.plotly_chart(
        visualizer.monthly_bar(analyzer.aggregate_monthly(pat_df, by_facility=by_fac), by_facility=by_fac),
        use_container_width=True,
    )
with col_r:
    st.plotly_chart(
        visualizer.hourly_avg_bar(analyzer.aggregate_hourly_avg(pat_df, by_facility=by_fac), by_facility=by_fac),
        use_container_width=True,
    )

col_l2, col_r2 = st.columns(2)
with col_l2:
    st.plotly_chart(
        visualizer.weekday_holiday_line(analyzer.weekday_vs_holiday(pat_df)),
        use_container_width=True,
    )
with col_r2:
    st.plotly_chart(
        visualizer.facility_ranking_bar(analyzer.facility_annual_ranking(pat_df)),
        use_container_width=True,
    )

st.plotly_chart(
    visualizer.daily_bar(analyzer.aggregate_daily(pat_df, by_facility=by_fac), by_facility=by_fac),
    use_container_width=True,
)
