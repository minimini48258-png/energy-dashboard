"""
app.py
電力需給分析ダッシュボード（Streamlit）
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import analyzer
import cache_manager
import data_cleaner
import data_loader
import grouping
import visualizer

st.set_page_config(
    page_title="電力需給分析ダッシュボード",
    page_icon="⚡",
    layout="wide",
)


# ---------------------------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "df": None,
    "clean_report": None,
    "mapping_confirmed": False,
    "df_raw_unmapped": None,
    "loaded_file_ids": set(),
    "loaded_filenames": [],
    "nav_end_date": None,      # 日付ナビゲーション用の表示終了日
    "custom_groups": {},       # 手動編集されたグループ設定
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _fmt(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f} MWh"
    if v >= 1_000:
        return f"{v/1_000:.1f} MWh"
    return f"{v:.2f} kWh"


def _process_files(uploaded_files) -> None:
    current_ids = {f.file_id for f in uploaded_files}
    if current_ids == st.session_state["loaded_file_ids"] and st.session_state["df"] is not None:
        return

    all_dfs, errors = [], []
    prog = st.sidebar.progress(0, text="読み込み準備中...")

    for i, f in enumerate(uploaded_files):
        prog.progress(i / len(uploaded_files), text=f"読み込み中: {f.name}")
        try:
            buf = io.BytesIO(f.read())
            df_raw, mapping = data_loader.load_file(buf)
            missing = data_cleaner.validate_standard_columns(df_raw)
            if missing:
                st.session_state["df_raw_unmapped"] = df_raw
                prog.empty()
                return

            df_clean, _ = data_cleaner.clean(df_raw)
            df_clean["facility_name"] = df_clean["facility_name"].astype(object)
            all_dfs.append(df_clean)

            label = "横展開（1日1行×48列）" if mapping.get("format") == "wide_daily" else "標準形式"
            st.sidebar.caption(f"✅ {f.name}：{len(df_clean):,} 行 / {label}")
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    prog.progress(1.0, text="完了")
    prog.empty()
    for e in errors:
        st.sidebar.error(e)

    if all_dfs:
        merged = pd.concat(all_dfs, ignore_index=True)
        # ディスクキャッシュに保存
        cache_manager.save(merged, [f.name for f in uploaded_files])
        st.session_state["df"] = merged
        st.session_state["mapping_confirmed"] = True
        st.session_state["loaded_file_ids"] = current_ids
        st.session_state["loaded_filenames"] = [f.name for f in uploaded_files]
        st.session_state["nav_end_date"] = merged["datetime"].max().date()
        # グループ設定をロード
        st.session_state["custom_groups"] = grouping.load_custom_groups()


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚡ 電力需給分析")
    st.markdown("---")

    # ── ファイルアップロード ──────────────────────────────
    st.header("📂 データ読み込み")
    uploaded_files = st.file_uploader(
        "Excel / CSV をアップロード（複数可）",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        _process_files(uploaded_files)
    elif st.session_state["df"] is not None and st.session_state["loaded_file_ids"]:
        st.session_state["df"] = None
        st.session_state["mapping_confirmed"] = False
        st.session_state["loaded_file_ids"] = set()

    # ── 保存済みデータ ────────────────────────────────────
    entries = cache_manager.list_entries()
    if entries:
        st.markdown("---")
        st.header("🗂 保存済みデータ")
        for meta in entries:
            fac_preview = "、".join(meta["facilities"][:3])
            if len(meta["facilities"]) > 3:
                fac_preview += f" 他{len(meta['facilities'])-3}施設"
            label = f"{meta['date_min']} 〜 {meta['date_max']}  |  {meta['rows']:,}行"
            with st.expander(f"📁 {', '.join(meta['filenames'][:2])}", expanded=False):
                st.caption(label)
                st.caption(f"施設: {fac_preview}")
                col_a, col_b = st.columns(2)
                if col_a.button("読み込む", key=f"load_{meta['cache_id']}"):
                    df_cached = cache_manager.load(meta["cache_id"])
                    st.session_state["df"] = df_cached
                    st.session_state["mapping_confirmed"] = True
                    st.session_state["loaded_file_ids"] = set()
                    st.session_state["loaded_filenames"] = meta["filenames"]
                    st.session_state["nav_end_date"] = pd.Timestamp(meta["date_max"]).date()
                    st.session_state["custom_groups"] = grouping.load_custom_groups()
                    st.rerun()
                if col_b.button("削除", key=f"del_{meta['cache_id']}"):
                    cache_manager.delete(meta["cache_id"])
                    st.rerun()

    # ── 手動列マッピング ──────────────────────────────────
    if st.session_state.get("df_raw_unmapped") is not None and not st.session_state["mapping_confirmed"]:
        st.markdown("---")
        st.subheader("🔧 列マッピング")
        raw = st.session_state["df_raw_unmapped"]
        cols = list(raw.columns)
        sel_dt  = st.selectbox("日時列",   options=cols, index=0)
        sel_fac = st.selectbox("施設名列", options=cols, index=min(1, len(cols)-1))
        sel_kwh = st.selectbox("使用量列", options=cols, index=min(2, len(cols)-1))
        if st.button("マッピングを確定", type="primary"):
            renamed = raw.rename(columns={sel_dt: "datetime", sel_fac: "facility_name", sel_kwh: "consumption_kwh"})
            df_clean, report = data_cleaner.clean(renamed)
            df_clean["facility_name"] = df_clean["facility_name"].astype(object)
            st.session_state["df"] = df_clean
            st.session_state["clean_report"] = report
            st.session_state["mapping_confirmed"] = True
            st.session_state["df_raw_unmapped"] = None
            st.session_state["nav_end_date"] = df_clean["datetime"].max().date()
            st.rerun()

    # ── サンプルデータ ────────────────────────────────────
    st.markdown("---")
    if st.button("🔬 サンプルデータで試す"):
        try:
            sample_df, _ = data_loader.load_file("data/sample/sample_data.csv")
            df_clean, report = data_cleaner.clean(sample_df)
            df_clean["facility_name"] = df_clean["facility_name"].astype(object)
            st.session_state["df"] = df_clean
            st.session_state["clean_report"] = report
            st.session_state["mapping_confirmed"] = True
            st.session_state["loaded_file_ids"] = set()
            st.session_state["nav_end_date"] = df_clean["datetime"].max().date()
            st.session_state["custom_groups"] = grouping.load_custom_groups()
            st.rerun()
        except FileNotFoundError:
            st.error("サンプルデータが見つかりません。generate_sample.py を実行してください。")


# ---------------------------------------------------------------------------
# メインエリア：データなし時
# ---------------------------------------------------------------------------

df: pd.DataFrame | None = st.session_state.get("df")

if df is None:
    st.title("⚡ 電力需給分析ダッシュボード")
    st.info("👈 サイドバーからExcel / CSVをアップロードするか、保存済みデータを読み込んでください。")
    st.markdown("""
    ### 対応データ形式
    **① 縦展開形式（標準）**
    | 列名 | 内容 | 例 |
    |------|------|----|
    | `datetime` | 日時（30分刻み） | `2024-04-01 00:00` |
    | `facility_name` | 施設名 | `市民会館` |
    | `consumption_kwh` | 使用電力量 (kWh) | `12.5` |

    **② 横展開形式（東北電力等のダウンロード形式）**
    1行＝1日・30分値48列（`0:00～0:30` … `23:30～24:00`）を自動検出します。
    """)
    st.stop()

report = st.session_state.get("clean_report")
if report and report.has_issues:
    with st.expander("⚠️ データ品質レポート", expanded=False):
        c = st.columns(4)
        c[0].metric("総行数",   f"{report.total_rows:,}")
        c[1].metric("クリーン後", f"{report.rows_after:,}")
        c[2].metric("重複削除",  f"{report.duplicate_rows:,}")
        c[3].metric("欠損値",    f"{report.missing_consumption:,}")
        if report.datetime_gaps:
            st.warning("\n".join(f"- {g}" for g in report.datetime_gaps))


# ---------------------------------------------------------------------------
# グループ管理
# ---------------------------------------------------------------------------

facility_names = sorted(df["facility_name"].unique().tolist())
custom_groups  = st.session_state.get("custom_groups", {})
group_df       = grouping.build_group_df(facility_names, custom_groups)

with st.expander("🏷 グループ管理（施設の地域・機能種別を編集）", expanded=False):
    st.caption("自動検出した地域・機能種別を編集できます。変更後は「保存」を押してください。")
    edited = st.data_editor(
        group_df,
        column_config={
            "facility_name": st.column_config.TextColumn("施設名", disabled=True),
            "region":        st.column_config.TextColumn("地域"),
            "function_type": st.column_config.SelectboxColumn(
                "機能種別",
                options=["行政", "学校", "文化・図書", "スポーツ", "保育・幼稚",
                         "医療・福祉", "集会施設", "その他"],
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="group_editor",
    )
    if st.button("💾 グループ設定を保存"):
        grouping.save_custom_groups(edited)
        st.session_state["custom_groups"] = grouping.load_custom_groups()
        group_df = grouping.build_group_df(facility_names, st.session_state["custom_groups"])
        st.success("保存しました")


# ---------------------------------------------------------------------------
# フィルタ UI
# ---------------------------------------------------------------------------

st.title("⚡ 電力需給分析ダッシュボード")

date_min: date = df["datetime"].min().date()
date_max: date = df["datetime"].max().date()

# ── グルーピングモード ──
col_gm, col_gs = st.columns([1, 3])
with col_gm:
    group_mode = st.selectbox(
        "グルーピング",
        options=["施設個別", "地域別", "機能種別別"],
        index=0,
    )

with col_gs:
    if group_mode == "地域別":
        all_opts = sorted(group_df["region"].unique().tolist())
        selected_groups = st.multiselect("地域を選択", options=all_opts, default=all_opts)
        filtered_fac = group_df[group_df["region"].isin(selected_groups)]["facility_name"].tolist()
    elif group_mode == "機能種別別":
        all_opts = sorted(group_df["function_type"].unique().tolist())
        selected_groups = st.multiselect("機能種別を選択", options=all_opts, default=all_opts)
        filtered_fac = group_df[group_df["function_type"].isin(selected_groups)]["facility_name"].tolist()
    else:
        filtered_fac = st.multiselect("施設を選択", options=facility_names, default=facility_names)

# ── 期間選択 + 日付ナビゲーション ──
col_p, col_nav = st.columns([2, 3])
with col_p:
    period_option = st.selectbox(
        "表示期間",
        options=["1日", "1週間", "1か月", "3か月", "1年", "カスタム"],
        index=2,
    )

period_delta_map = {
    "1日":   timedelta(days=1),
    "1週間": timedelta(weeks=1),
    "1か月": timedelta(days=30),
    "3か月": timedelta(days=90),
    "1年":   timedelta(days=365),
}

if period_option == "カスタム":
    with col_nav:
        date_range = st.date_input(
            "期間を指定",
            value=(date_min, date_max),
            min_value=date_min,
            max_value=date_max,
        )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_dt = pd.Timestamp(date_range[0])
        end_dt   = pd.Timestamp(date_range[1]) + timedelta(days=1) - timedelta(seconds=1)
    else:
        start_dt = pd.Timestamp(date_min)
        end_dt   = pd.Timestamp(date_max)
else:
    delta = period_delta_map[period_option]

    # セッション状態の nav_end_date が有効範囲に収まるよう補正
    nav_end = st.session_state.get("nav_end_date") or date_max
    nav_end = max(date_min + delta, min(nav_end, date_max))

    with col_nav:
        c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
        with c1:
            if st.button("◀◀", help="データの先頭へ"):
                nav_end = date_min + delta
                st.session_state["nav_end_date"] = nav_end
        with c2:
            if st.button("◀", help="前の期間へ"):
                nav_end = max(date_min + delta, nav_end - delta)
                st.session_state["nav_end_date"] = nav_end
        with c3:
            nav_end = st.date_input(
                "表示終了日",
                value=nav_end,
                min_value=date_min + delta,
                max_value=date_max,
                label_visibility="collapsed",
                key="nav_date_input",
            )
            st.session_state["nav_end_date"] = nav_end
        with c4:
            if st.button("▶", help="次の期間へ"):
                nav_end = min(date_max, nav_end + delta)
                st.session_state["nav_end_date"] = nav_end

    end_dt   = pd.Timestamp(nav_end)
    start_dt = end_dt - delta

# ── 集計単位 ──
agg_options = ["施設別", "グループ合計", "全施設合計"]
agg_mode = st.radio(
    "集計単位",
    options=agg_options,
    index=0,
    horizontal=True,
)

# ── フィルタ適用 ──
if not filtered_fac:
    st.warning("施設を1つ以上選択してください。")
    st.stop()

filtered = analyzer.filter_by_period(
    analyzer.filter_by_facilities(df, filtered_fac),
    start_dt, end_dt,
)

if filtered.empty:
    st.warning("選択した期間・施設にデータがありません。")
    st.stop()

# グループ列を付与（グループ合計モード用）
if agg_mode == "グループ合計" and group_mode != "施設個別":
    group_col = "region" if group_mode == "地域別" else "function_type"
    filtered = grouping.add_group_column(filtered, group_df, group_col)


# ---------------------------------------------------------------------------
# KPI
# ---------------------------------------------------------------------------

stats = analyzer.summary_stats(filtered)
m1, m2, m3, m4 = st.columns(4)
m1.metric("積算使用量",         _fmt(stats["total_kwh"]))
m2.metric("最大 (30min)",       f"{stats['max_kwh']:.2f} kWh")
m3.metric("平均 (30min)",       f"{stats['mean_kwh']:.2f} kWh")
m4.metric("表示期間",
          f"{start_dt.strftime('%Y/%m/%d')} 〜 {end_dt.strftime('%Y/%m/%d')}")

st.markdown("---")


# ---------------------------------------------------------------------------
# タブ
# ---------------------------------------------------------------------------

tab_demand, tab_pattern, tab_supply = st.tabs(
    ["📈 需要カーブ", "📊 需要パターン分析", "⚡ 需給バランス（準備中）"]
)


# ── 共通：timeseries データの選択 ──
def _ts_data(filt: pd.DataFrame) -> pd.DataFrame:
    if agg_mode == "グループ合計" and "group_label" in filt.columns:
        return analyzer.aggregate_30min_by_group(filt)
    elif agg_mode == "施設別":
        return analyzer.aggregate_30min(filt, by_facility=True)
    else:
        return analyzer.aggregate_30min(filt, by_facility=False)


def _by_fac(filt: pd.DataFrame) -> bool:
    """パターン分析: 施設別表示にするか。"""
    return agg_mode == "施設別"


with tab_demand:
    period_label = f"{start_dt.strftime('%Y/%m/%d')} 〜 {end_dt.strftime('%Y/%m/%d')}"
    st.plotly_chart(
        visualizer.demand_timeseries(_ts_data(filtered), title=f"電力使用量（30分値）— {period_label}"),
        use_container_width=True,
    )


with tab_pattern:
    by_fac = _by_fac(filtered)

    # パターン分析では facility_name を使う（グループ合計モードでも group_label → facility_name として扱う）
    pat_df = filtered.copy()
    if "group_label" in pat_df.columns:
        pat_df["facility_name"] = pat_df["group_label"]

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


with tab_supply:
    st.info("""
    **このタブは次フェーズで実装します。**

    追加予定：太陽光・蓄電池・市場調達の入力 → 需給バランス・電源構成比グラフ
    """)
