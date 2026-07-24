"""
common.py
マルチページ化に伴い、各ページで共通して使う
「データ有無チェック」「グループ設定」「施設フィルタ・グルーピング」
「表示期間・日付ナビ・KPI」を関数化したもの。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import analyzer
import grouping

PERIOD_OPTIONS = ["全データ期間", "直近1年", "直近6か月", "直近3か月"]


def require_data() -> pd.DataFrame:
    """需要データが読み込まれていなければ案内を出して停止し、読み込まれていればdfを返す。"""
    df = st.session_state.get("df")
    if df is None:
        st.info("👈 サイドバーの「データ読み込み」ページからデータを読み込んでください。")
        st.stop()
    return df


def get_group_context(df: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    """施設名一覧とグループDataFrame（地域・機能種別）を返す。"""
    facility_names = sorted(df["facility_name"].unique().tolist())
    custom_groups = st.session_state.get("custom_groups", {})
    group_df = grouping.build_group_df(facility_names, custom_groups)
    return facility_names, group_df


def render_facility_filter(
    df: pd.DataFrame,
    facility_names: list[str],
    group_df: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    """グルーピングモード選択＋施設フィルタ。日付レンジは適用しない filtered_base を返す。"""
    col_gm, col_gs = st.columns([1, 3])
    with col_gm:
        group_mode = st.selectbox(
            "グルーピング",
            options=["施設個別", "地域別", "機能種別別"],
            index=0,
            key="common_group_mode",
        )
    with col_gs:
        if group_mode == "地域別":
            all_opts = sorted(group_df["region"].unique().tolist())
            selected_groups = st.multiselect("地域を選択", options=all_opts, default=all_opts, key="common_group_sel_region")
            filtered_fac = group_df[group_df["region"].isin(selected_groups)]["facility_name"].tolist()
        elif group_mode == "機能種別別":
            all_opts = sorted(group_df["function_type"].unique().tolist())
            selected_groups = st.multiselect("機能種別を選択", options=all_opts, default=all_opts, key="common_group_sel_func")
            filtered_fac = group_df[group_df["function_type"].isin(selected_groups)]["facility_name"].tolist()
        else:
            filtered_fac = st.multiselect("施設を選択", options=facility_names, default=facility_names, key="common_group_sel_fac")

    if not filtered_fac:
        st.warning("施設を1つ以上選択してください。")
        st.stop()

    filtered_base = analyzer.filter_by_facilities(df, filtered_fac)
    return filtered_base, group_mode


def filter_by_period_option(base_df: pd.DataFrame, period_option: str) -> pd.DataFrame:
    """「全データ期間／直近1年／直近6か月／直近3か月」の簡易期間セレクタを適用する。"""
    pmax = base_df["datetime"].max()
    if period_option == "直近1年":
        return analyzer.filter_by_period(base_df, pmax - timedelta(days=365), pmax)
    if period_option == "直近6か月":
        return analyzer.filter_by_period(base_df, pmax - timedelta(days=180), pmax)
    if period_option == "直近3か月":
        return analyzer.filter_by_period(base_df, pmax - timedelta(days=90), pmax)
    return base_df


def render_period_and_kpis(
    filtered_base: pd.DataFrame,
    group_mode: str,
    group_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Timestamp, str]:
    """
    需要カーブ・需要パターン分析専用：表示期間・日付ナビ・集計単位・KPI表示。
    Returns: (filtered, filtered_base, start_dt, end_dt, agg_mode)
    filtered / filtered_base は、集計単位が「グループ合計」の場合 group_label 列が付与された状態で返る。
    """
    dt_min: date = filtered_base["datetime"].dropna().min().date()
    dt_max: date = filtered_base["datetime"].dropna().max().date()

    col_p, col_nav = st.columns([2, 3])
    with col_p:
        period_option = st.selectbox(
            "表示期間",
            options=["1日", "1週間", "1か月", "3か月", "1年", "カスタム"],
            index=2, key="common_period_option",
        )

    period_delta_map = {
        "1日": timedelta(days=1), "1週間": timedelta(weeks=1), "1か月": timedelta(days=30),
        "3か月": timedelta(days=90), "1年": timedelta(days=365),
    }

    if period_option == "カスタム":
        with col_nav:
            date_range = st.date_input(
                "期間を指定", value=(dt_min, dt_max), min_value=dt_min, max_value=dt_max,
                key="common_date_range",
            )
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            start_dt = pd.Timestamp(date_range[0])
            end_dt = pd.Timestamp(date_range[1]) + timedelta(days=1) - timedelta(seconds=1)
        else:
            start_dt = pd.Timestamp(dt_min)
            end_dt = pd.Timestamp(dt_max)
    else:
        delta = period_delta_map[period_option]
        nav_min = min(dt_min + delta, dt_max)
        nav_end = st.session_state.get("nav_end_date") or dt_max
        nav_end = max(nav_min, min(nav_end, dt_max))

        with col_nav:
            c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
            with c1:
                if st.button("◀◀", help="データの先頭へ", key="common_nav_first"):
                    nav_end = nav_min
                    st.session_state["nav_end_date"] = nav_end
            with c2:
                if st.button("◀", help="前の期間へ", key="common_nav_prev"):
                    nav_end = max(nav_min, nav_end - delta)
                    st.session_state["nav_end_date"] = nav_end
            with c3:
                nav_end = st.date_input(
                    "表示終了日", value=nav_end, min_value=nav_min, max_value=dt_max,
                    label_visibility="collapsed", key="common_nav_date_input",
                )
                st.session_state["nav_end_date"] = nav_end
            with c4:
                if st.button("▶", help="次の期間へ", key="common_nav_next"):
                    nav_end = min(dt_max, nav_end + delta)
                    st.session_state["nav_end_date"] = nav_end

        end_dt = pd.Timestamp(nav_end)
        start_dt = end_dt - delta

    agg_mode = st.radio(
        "集計単位", options=["施設別", "グループ合計", "全施設合計"],
        index=0, horizontal=True, key="common_agg_mode",
    )

    filtered = analyzer.filter_by_period(filtered_base, start_dt, end_dt)
    if filtered.empty:
        st.warning("選択した期間・施設にデータがありません。")
        st.stop()

    if agg_mode == "グループ合計" and group_mode != "施設個別":
        group_col = "region" if group_mode == "地域別" else "function_type"
        filtered = grouping.add_group_column(filtered, group_df, group_col)
        filtered_base = grouping.add_group_column(filtered_base, group_df, group_col)

    stats = analyzer.summary_stats(filtered)

    def _fmt(v: float) -> str:
        if v >= 1_000_000:
            return f"{v/1_000_000:.2f} MWh"
        if v >= 1_000:
            return f"{v/1_000:.1f} MWh"
        return f"{v:.2f} kWh"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("積算使用量", _fmt(stats["total_kwh"]))
    m2.metric("最大 (30min)", f"{stats['max_kwh']:.2f} kWh")
    m3.metric("平均 (30min)", f"{stats['mean_kwh']:.2f} kWh")
    m4.metric("表示期間", f"{start_dt.strftime('%Y/%m/%d')} 〜 {end_dt.strftime('%Y/%m/%d')}")
    st.markdown("---")

    return filtered, filtered_base, start_dt, end_dt, agg_mode
