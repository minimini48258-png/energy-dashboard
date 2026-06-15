"""
app.py
電力需給分析ダッシュボード（Streamlit）
"""

from __future__ import annotations

import io
from datetime import timedelta

import pandas as pd
import streamlit as st

import analyzer
import data_cleaner
import data_loader
import visualizer

st.set_page_config(
    page_title="電力需給分析ダッシュボード",
    page_icon="⚡",
    layout="wide",
)


# ---------------------------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults: dict = {
        "df": None,
        "clean_report": None,
        "mapping_confirmed": False,
        "df_raw_unmapped": None,
        "loaded_file_ids": set(),   # 処理済みファイルIDのセット
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _format_kwh(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f} MWh"
    if v >= 1_000:
        return f"{v/1_000:.2f} MWh"
    return f"{v:.2f} kWh"


def _process_files(uploaded_files) -> None:
    """アップロードされたファイルを処理してセッション状態に保存する。"""
    current_ids = {f.file_id for f in uploaded_files}
    already_loaded = st.session_state["loaded_file_ids"]

    # 前回と同じファイルセットなら再処理しない
    if current_ids == already_loaded and st.session_state["df"] is not None:
        return

    all_dfs: list[pd.DataFrame] = []
    all_mappings: list[dict] = []
    errors: list[str] = []

    progress = st.sidebar.progress(0, text="読み込み準備中...")

    for i, f in enumerate(uploaded_files):
        progress.progress((i) / len(uploaded_files), text=f"読み込み中: {f.name}")
        try:
            raw_bytes = f.read()
            buf = io.BytesIO(raw_bytes)
            df_raw, mapping = data_loader.load_file(buf)

            missing = data_cleaner.validate_standard_columns(df_raw)
            if missing:
                st.session_state["df_raw_unmapped"] = df_raw
                progress.empty()
                return

            df_clean, report = data_cleaner.clean(df_raw)
            # Arrow 文字列型を通常の object 型に変換（シリアライズ安定化）
            df_clean["facility_name"] = df_clean["facility_name"].astype(object)

            all_dfs.append(df_clean)
            all_mappings.append(mapping)

            fmt = mapping.get("format", "standard")
            label = "横展開（1日1行×48列）" if fmt == "wide_daily" else "標準形式"
            st.sidebar.caption(f"✅ {f.name}：{len(df_clean):,} 行 / {label}")

        except Exception as e:
            errors.append(f"{f.name}: {e}")

    progress.progress(1.0, text="処理完了")
    progress.empty()

    for e in errors:
        st.sidebar.error(e)

    if all_dfs:
        merged = pd.concat(all_dfs, ignore_index=True)
        st.session_state["df"] = merged
        st.session_state["clean_report"] = report
        st.session_state["mapping_confirmed"] = True
        st.session_state["loaded_file_ids"] = current_ids


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚡ 電力需給分析")
    st.markdown("---")

    st.header("📂 データ読み込み")
    uploaded_files = st.file_uploader(
        "Excel または CSV をアップロード（複数可）",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        _process_files(uploaded_files)
    else:
        # ファイルが削除されたらリセット
        if st.session_state["df"] is not None and st.session_state["loaded_file_ids"]:
            st.session_state["df"] = None
            st.session_state["clean_report"] = None
            st.session_state["mapping_confirmed"] = False
            st.session_state["loaded_file_ids"] = set()

    # 手動列マッピング
    if st.session_state.get("df_raw_unmapped") is not None and not st.session_state["mapping_confirmed"]:
        st.markdown("---")
        st.subheader("🔧 列マッピング")
        raw = st.session_state["df_raw_unmapped"]
        cols = list(raw.columns)

        sel_dt = st.selectbox("日時列", options=cols, index=0)
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
            st.success(f"✅ {len(df_clean):,} 行を読み込みました。")

    # サンプルデータ
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
            st.success(f"✅ サンプルデータ（{len(df_clean):,} 行）")
        except FileNotFoundError:
            st.error("サンプルデータが見つかりません。generate_sample.py を実行してください。")


# ---------------------------------------------------------------------------
# メインエリア
# ---------------------------------------------------------------------------

df: pd.DataFrame | None = st.session_state.get("df")
report = st.session_state.get("clean_report")

if df is None:
    st.title("⚡ 電力需給分析ダッシュボード")
    st.info("👈 サイドバーからExcel / CSVをアップロードしてください。")
    st.markdown("""
    ### 対応データ形式

    **① 縦展開形式（標準）**

    | 列名 | 内容 | 例 |
    |------|------|----|
    | `datetime` | 日時（30分刻み） | `2024-04-01 00:00` |
    | `facility_name` | 施設名 | `市民会館` |
    | `consumption_kwh` | 使用電力量 (kWh) | `12.5` |

    **② 横展開形式（東北電力等のダウンロード形式）**

    1行＝1日分・30分値が48列（`0:00～0:30` … `23:30～24:00`）に並ぶ形式を自動検出します。
    """)
    st.stop()

if report and report.has_issues:
    with st.expander("⚠️ データ品質レポート", expanded=False):
        c = st.columns(4)
        c[0].metric("総行数", f"{report.total_rows:,}")
        c[1].metric("クリーン後", f"{report.rows_after:,}")
        c[2].metric("重複削除", f"{report.duplicate_rows:,}")
        c[3].metric("欠損値", f"{report.missing_consumption:,}")
        if report.datetime_gaps:
            st.warning("**タイムスタンプの欠落:**\n" + "\n".join(f"- {g}" for g in report.datetime_gaps))


# ---------------------------------------------------------------------------
# フィルタ UI
# ---------------------------------------------------------------------------

st.title("⚡ 電力需給分析ダッシュボード")

facilities = sorted(df["facility_name"].unique().tolist())
date_min = df["datetime"].min().date()
date_max = df["datetime"].max().date()

col_f, col_p, col_agg = st.columns([2, 2, 1])

with col_f:
    selected_facilities = st.multiselect("施設を選択", options=facilities, default=facilities)

with col_p:
    period_option = st.selectbox(
        "表示期間",
        options=["24時間", "1週間", "1か月", "1年", "カスタム"],
        index=2,
    )
    if period_option == "24時間":
        end_dt = pd.Timestamp(date_max)
        start_dt = end_dt - timedelta(hours=24)
    elif period_option == "1週間":
        end_dt = pd.Timestamp(date_max)
        start_dt = end_dt - timedelta(weeks=1)
    elif period_option == "1か月":
        end_dt = pd.Timestamp(date_max)
        start_dt = end_dt - timedelta(days=30)
    elif period_option == "1年":
        end_dt = pd.Timestamp(date_max)
        start_dt = end_dt - timedelta(days=365)
    else:
        start_dt = pd.Timestamp(
            st.date_input("開始日", value=date_min, min_value=date_min, max_value=date_max)
        )
        end_dt = pd.Timestamp(
            st.date_input("終了日", value=date_max, min_value=date_min, max_value=date_max)
        ) + timedelta(days=1) - timedelta(seconds=1)

with col_agg:
    agg_mode = st.radio("集計単位", options=["施設別", "全施設合計"], index=0)

if not selected_facilities:
    st.warning("施設を1つ以上選択してください。")
    st.stop()

filtered = analyzer.filter_by_period(
    analyzer.filter_by_facilities(df, selected_facilities),
    start_dt, end_dt,
)

if filtered.empty:
    st.warning("選択した条件にデータがありません。")
    st.stop()


# ---------------------------------------------------------------------------
# KPI
# ---------------------------------------------------------------------------

stats = analyzer.summary_stats(filtered)
m1, m2, m3, m4 = st.columns(4)
m1.metric("積算使用量", _format_kwh(stats["total_kwh"]))
m2.metric("最大使用量 (30min)", f"{stats['max_kwh']:.2f} kWh")
m3.metric("平均使用量 (30min)", f"{stats['mean_kwh']:.2f} kWh")
m4.metric("最小使用量 (30min)", f"{stats['min_kwh']:.2f} kWh")

st.markdown("---")


# ---------------------------------------------------------------------------
# タブ
# ---------------------------------------------------------------------------

tab_demand, tab_pattern, tab_supply = st.tabs(["📈 需要カーブ", "📊 需要パターン分析", "⚡ 需給バランス（準備中）"])

with tab_demand:
    by_fac = agg_mode == "施設別"
    st.plotly_chart(
        visualizer.demand_timeseries(
            analyzer.aggregate_30min(filtered, by_facility=by_fac),
            title=f"電力使用量（30分値）— {period_option}",
        ),
        use_container_width=True,
    )

with tab_pattern:
    by_fac_pat = agg_mode == "施設別"
    col_l, col_r = st.columns(2)
    with col_l:
        st.plotly_chart(
            visualizer.monthly_bar(analyzer.aggregate_monthly(filtered, by_facility=by_fac_pat), by_facility=by_fac_pat),
            use_container_width=True,
        )
    with col_r:
        st.plotly_chart(
            visualizer.hourly_avg_bar(analyzer.aggregate_hourly_avg(filtered, by_facility=by_fac_pat), by_facility=by_fac_pat),
            use_container_width=True,
        )
    col_l2, col_r2 = st.columns(2)
    with col_l2:
        st.plotly_chart(visualizer.weekday_holiday_line(analyzer.weekday_vs_holiday(filtered)), use_container_width=True)
    with col_r2:
        st.plotly_chart(visualizer.facility_ranking_bar(analyzer.facility_annual_ranking(filtered)), use_container_width=True)
    st.plotly_chart(
        visualizer.daily_bar(analyzer.aggregate_daily(filtered, by_facility=by_fac_pat), by_facility=by_fac_pat),
        use_container_width=True,
    )

with tab_supply:
    st.info("""
    **このタブは次フェーズで実装します。**

    追加予定：太陽光・蓄電池・市場調達の入力 → 需給バランス・電源構成比グラフ
    """)
