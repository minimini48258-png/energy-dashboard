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


def format_date_range(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """開始日と終了日が同じ日なら単日表記、異なれば「開始〜終了」表記にする。"""
    start_label = pd.Timestamp(start).strftime("%Y/%m/%d")
    end_label = pd.Timestamp(end).strftime("%Y/%m/%d")
    if start_label == end_label:
        return start_label
    return f"{start_label} 〜 {end_label}"


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


def _fiscal_year_of(ts: pd.Timestamp, start_month: int) -> int:
    """ある日時が属する年度（開始月基準）を返す。例: start_month=4なら2026-03は2025年度。"""
    return ts.year if ts.month >= start_month else ts.year - 1


def available_fiscal_years(base_df: pd.DataFrame, start_month: int) -> list[int]:
    """データ期間に含まれる年度（開始月基準）の一覧を返す。"""
    dt_min, dt_max = base_df["datetime"].min(), base_df["datetime"].max()
    return list(range(_fiscal_year_of(dt_min, start_month), _fiscal_year_of(dt_max, start_month) + 1))


def fiscal_year_range(start_month: int, fiscal_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """年度（開始月基準）の開始・終了日時を返す。"""
    start = pd.Timestamp(year=fiscal_year, month=start_month, day=1)
    end = start + pd.DateOffset(years=1) - pd.Timedelta(seconds=1)
    return start, end


def render_period_selector(base_df: pd.DataFrame, key_prefix: str, default_index: int = 1) -> pd.DataFrame:
    """
    「全データ期間／直近1年／直近6か月／直近3か月／年度で指定」の期間セレクタを描画し、
    フィルタ後のDataFrameを返す。「年度で指定」では開始月（例: 4月〜）と対象年度を選べる。
    """
    options = PERIOD_OPTIONS + ["年度で指定"]
    choice = st.selectbox("分析期間", options, index=default_index, key=f"{key_prefix}_period_mode")
    if choice != "年度で指定":
        return filter_by_period_option(base_df, choice)

    col1, col2 = st.columns(2)
    start_month = col1.selectbox(
        "年度の開始月", list(range(1, 13)), index=3, format_func=lambda m: f"{m}月",
        key=f"{key_prefix}_fy_start_month",
    )
    years = available_fiscal_years(base_df, start_month)
    if not years:
        return base_df.iloc[0:0]
    end_month = start_month - 1 if start_month > 1 else 12
    end_month_label = f"{end_month}月" if start_month == 1 else f"翌{end_month}月"
    year_labels = [f"{y}年度（{start_month}月〜{end_month_label}）" for y in years]
    sel_idx = col2.selectbox(
        "対象年度", list(range(len(years))), format_func=lambda i: year_labels[i],
        index=len(years) - 1, key=f"{key_prefix}_fy_year",
    )
    start, end = fiscal_year_range(start_month, years[sel_idx])
    return analyzer.filter_by_period(base_df, start, end)


def render_flexible_period(
    base_df: pd.DataFrame,
    key_prefix: str,
    options: list[str] | None = None,
    default_index: int = 2,
    nav_end_state_key: str | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """
    「1日／1週間／1か月／3か月／1年／全データ期間／カスタム」の期間セレクタと
    前後ナビゲーション（◀◀／◀／日付指定／▶）を描画し、(start_dt, end_dt, period_option) を返す。
    key_prefix はウィジェットキーの衝突を避けるためページごとに変える。
    """
    if options is None:
        options = ["1日", "1週間", "1か月", "3か月", "1年", "カスタム"]
    if nav_end_state_key is None:
        nav_end_state_key = f"{key_prefix}_nav_end_date"

    dt_min: date = base_df["datetime"].dropna().min().date()
    dt_max: date = base_df["datetime"].dropna().max().date()

    col_p, col_nav = st.columns([2, 3])
    with col_p:
        period_option = st.selectbox(
            "表示期間", options=options, index=default_index, key=f"{key_prefix}_period_option",
        )

    if period_option == "全データ期間":
        return pd.Timestamp(dt_min), pd.Timestamp(dt_max) + timedelta(days=1) - timedelta(seconds=1), period_option

    period_delta_map = {
        "1日": timedelta(days=1), "1週間": timedelta(weeks=1), "1か月": timedelta(days=30),
        "3か月": timedelta(days=90), "1年": timedelta(days=365),
    }

    if period_option == "カスタム":
        with col_nav:
            date_range = st.date_input(
                "期間を指定", value=(dt_min, dt_max), min_value=dt_min, max_value=dt_max,
                key=f"{key_prefix}_date_range",
            )
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            start_dt = pd.Timestamp(date_range[0])
            end_dt = pd.Timestamp(date_range[1]) + timedelta(days=1) - timedelta(seconds=1)
        else:
            start_dt = pd.Timestamp(dt_min)
            end_dt = pd.Timestamp(dt_max)
        return start_dt, end_dt, period_option

    delta = period_delta_map[period_option]
    # 終了日を選択日の23:59:59までを含むフル1日として扱う分、最速到達日は
    # 従来の dt_min+delta ではなく dt_min+delta-1日（= start_dt が dt_min に一致する最小値）。
    nav_min = min(dt_min + delta - timedelta(days=1), dt_max)
    date_input_key = f"{key_prefix}_nav_date_input"

    # st.date_input に key を渡すと、2回目以降のレンダリングでは value引数は無視され、
    # ウィジェット自身が保持する st.session_state[date_input_key] の値がそのまま使われる。
    # そのため「現在値」はこのキーを優先して読む（無ければ nav_end_state_key→dt_max）。
    nav_end = st.session_state.get(date_input_key) or st.session_state.get(nav_end_state_key) or dt_max
    nav_end = max(nav_min, min(nav_end, dt_max))

    with col_nav:
        c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
        # ボタンのクリック判定は、日付入力ウィジェット（c3, key=date_input_key）が
        # インスタンス化される前にすべて済ませる必要がある。st.session_state[key]は
        # 同一実行内でそのキーのウィジェットが生成された後には書き換えられないため
        # （StreamlitWidgetAlreadyInstantiatedError）。▶ボタン（c4）は見た目上は
        # date_inputより右だが、コード上は先に判定することで見た目の列順は変えずに
        # この制約を回避する。
        with c1:
            clicked_first = st.button("◀◀", help="データの先頭へ", key=f"{key_prefix}_nav_first")
        with c2:
            clicked_prev = st.button("◀", help="前の期間へ", key=f"{key_prefix}_nav_prev")
        with c4:
            clicked_next = st.button("▶", help="次の期間へ", key=f"{key_prefix}_nav_next")

        if clicked_first:
            nav_end = nav_min
            st.session_state[date_input_key] = nav_end
            st.session_state[nav_end_state_key] = nav_end
            st.rerun()
        elif clicked_prev:
            nav_end = max(nav_min, nav_end - delta)
            st.session_state[date_input_key] = nav_end
            st.session_state[nav_end_state_key] = nav_end
            st.rerun()
        elif clicked_next:
            nav_end = min(dt_max, nav_end + delta)
            st.session_state[date_input_key] = nav_end
            st.session_state[nav_end_state_key] = nav_end
            st.rerun()

        with c3:
            nav_end = st.date_input(
                "表示終了日", value=nav_end, min_value=nav_min, max_value=dt_max,
                label_visibility="collapsed", key=date_input_key,
            )
            st.session_state[nav_end_state_key] = nav_end

    # 「表示終了日」は選択した日を含む1日として扱う（例: 1日指定で9/28を選べば
    # 9/28 00:00〜23:59:59。以前はnav_endをそのまま終了端として使っていたため、
    # 選択日の前日しか表示されない不具合があった）。
    end_dt = pd.Timestamp(nav_end) + timedelta(days=1) - timedelta(seconds=1)
    start_dt = end_dt - delta + timedelta(seconds=1)
    return start_dt, end_dt, period_option


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
    start_dt, end_dt, _period_option = render_flexible_period(
        filtered_base, key_prefix="common", default_index=2, nav_end_state_key="nav_end_date",
    )

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
    m4.metric("表示期間", format_date_range(start_dt, end_dt))
    st.markdown("---")

    return filtered, filtered_base, start_dt, end_dt, agg_mode


# ---------------------------------------------------------------------------
# 供給分析（供給カーブ・供給パターン分析）用
# ---------------------------------------------------------------------------

def require_supply_data() -> pd.DataFrame:
    """
    供給データが読み込まれていなければ案内を出して停止する。
    読み込まれていれば、需要データと同じ列名（datetime / facility_name / consumption_kwh）に
    読み替えたDataFrameを返す（facility_name=電源名, consumption_kwh=発電量kWh/30分）。
    """
    sdf = st.session_state.get("supply_df")
    if sdf is None or sdf.empty:
        st.info(
            "👈 サイドバーの「データ読み込み」ページで供給データ（発電所の30分値）を読み込むか、"
            "サンプル供給データを生成してください。"
        )
        st.stop()
    return analyzer.supply_to_standard(sdf)


def render_source_filter(sdf: pd.DataFrame) -> pd.DataFrame:
    """電源の選択（初期値は「データ読み込み」ページで選んだ表示対象の電源）。"""
    all_sources = sorted(sdf["facility_name"].unique().tolist())
    default = [s for s in st.session_state.get("selected_supply_names", []) if s in all_sources] or all_sources
    selected = st.multiselect("電源を選択", options=all_sources, default=default, key="supply_sel_sources")
    if not selected:
        st.warning("電源を1つ以上選択してください。")
        st.stop()
    return analyzer.filter_by_facilities(sdf, selected)


def render_supply_period_and_kpis(
    filtered_base: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, str]:
    """
    供給カーブ・供給パターン分析専用：表示期間・日付ナビ・集計単位・KPI表示。
    需要側とは別のキーで表示期間を持つ（需要と供給でデータ期間が異なることがあるため）。
    Returns: (filtered, start_dt, end_dt, agg_mode)  agg_mode は「電源別」または「全電源合計」。
    """
    start_dt, end_dt, _period_option = render_flexible_period(
        filtered_base, key_prefix="supply", default_index=2, nav_end_state_key="supply_nav_end_date",
    )

    agg_mode = st.radio(
        "集計単位", options=["電源別", "全電源合計"], index=0, horizontal=True, key="supply_agg_mode",
    )

    filtered = analyzer.filter_by_period(filtered_base, start_dt, end_dt)
    if filtered.empty:
        st.warning("選択した期間・電源にデータがありません。")
        st.stop()

    total = filtered.groupby("datetime")["consumption_kwh"].sum()
    total_kwh = float(total.sum())

    def _fmt(v: float) -> str:
        if v >= 1_000:
            return f"{v/1_000:,.1f} MWh"
        return f"{v:.2f} kWh"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("積算発電量", _fmt(total_kwh))
    # 30分値(kWh) × 2 = その30分の平均出力(kW)
    m2.metric("最大出力", f"{float(total.max()) * 2:,.1f} kW", help="選択電源合計の30分値の最大 × 2（30分平均出力）")
    m3.metric("平均 (30min)", f"{float(total.mean()):,.2f} kWh")
    m4.metric("表示期間", format_date_range(start_dt, end_dt))
    st.markdown("---")

    return filtered, start_dt, end_dt, agg_mode
