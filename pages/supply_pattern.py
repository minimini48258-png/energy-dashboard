"""
pages/supply_pattern.py
供給パターン分析（月別・時間帯別・季節別・電源ランキング・日別）。
需要分析の「需要パターン分析」と同じ構成。平日・休日比較の代わりに、
発電量の変動要因として大きい「季節別の時間帯平均」を表示する。
"""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

import analyzer
import common
import visualizer

st.title("📊 供給パターン分析")

sdf = common.require_supply_data()
filtered_base, group_mode = common.render_source_filter(sdf)
filtered, start_dt, end_dt, agg_mode = common.render_supply_period_and_kpis(filtered_base, group_mode)

# ── 分析期間セレクタ（供給カーブの表示期間とは独立） ──
p_col1, p_col2 = st.columns([2, 4])
with p_col1:
    pat_period = st.selectbox(
        "分析期間",
        options=["全データ期間", "直近1年", "直近6か月", "直近3か月", "表示期間と同じ"],
        index=0, key="supply_pat_period",
    )
_bmax = filtered_base["datetime"].max()
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
        f"分析対象: {common.format_date_range(pat_df['datetime'].min(), pat_df['datetime'].max())}  "
        f"（{len(pat_df):,} 行）"
    )

if pat_df.empty:
    st.warning("選択した分析期間にデータがありません。")
    st.stop()

# 集計単位に合わせて facility_name を読み替える（グループ合計なら電源種別名・地域名になる）
rank_df = pat_df if agg_mode == "全電源合計" else common.supply_series_for(pat_df, agg_mode)
pat_df = common.supply_series_for(pat_df, agg_mode)
by_src = agg_mode != "全電源合計"
M = "発電量"
E = "グループ" if agg_mode == "グループ合計" else "電源"

col_l, col_r = st.columns(2)
with col_l:
    st.plotly_chart(
        visualizer.monthly_bar(
            analyzer.aggregate_monthly(pat_df, by_facility=by_src), by_facility=by_src, metric=M, entity=E,
        ),
        use_container_width=True,
    )
with col_r:
    st.plotly_chart(
        visualizer.hourly_avg_bar(
            analyzer.aggregate_hourly_avg(pat_df, by_facility=by_src), by_facility=by_src, metric=M, entity=E,
        ),
        use_container_width=True,
    )

# 季節別の時間帯平均は電源ごとに形が違う（太陽光と水力を合算すると読みにくい）ため、対象を選んで表示する
col_l2, col_r2 = st.columns(2)
with col_l2:
    _srcs = sorted(rank_df["facility_name"].unique().tolist())
    _opts = ["選択中の全電源合計"] + _srcs if len(_srcs) > 1 else _srcs
    season_target = st.selectbox("季節別グラフの対象", _opts, key="supply_season_target")
    season_df = rank_df if season_target == "選択中の全電源合計" else rank_df[rank_df["facility_name"] == season_target]
    season_df = season_df.groupby("datetime", as_index=False)["consumption_kwh"].sum()
    st.plotly_chart(
        visualizer.season_hourly_line(analyzer.season_hourly_avg(season_df), metric=M),
        use_container_width=True,
    )
with col_r2:
    st.plotly_chart(
        visualizer.facility_ranking_bar(
            analyzer.facility_annual_ranking(rank_df), metric=M, entity=E if by_src else "電源",
            title=f"{E if by_src else '電源'}別発電量ランキング（分析期間合計）",
        ),
        use_container_width=True,
    )

st.plotly_chart(
    visualizer.daily_bar(
        analyzer.aggregate_daily(pat_df, by_facility=by_src), by_facility=by_src, metric=M, entity=E,
    ),
    use_container_width=True,
)
