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
# キャッシュ付きファイル読み込み
# ファイルの中身（bytes）をキーにキャッシュするので、同じファイルを再アップロードしても再処理しない
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_and_clean(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, object, dict]:
    buf = io.BytesIO(file_bytes)
    df_raw, mapping = data_loader.load_file(buf)
    missing = data_cleaner.validate_standard_columns(df_raw)
    if missing:
        return df_raw, None, mapping  # 手動マッピングが必要
    df_clean, report = data_cleaner.clean(df_raw)
    return df_clean, report, mapping


# ---------------------------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults: dict = {
        "df": None,
        "clean_report": None,
        "mapping_confirmed": False,
        "df_raw_unmapped": None,
        "unmapped_filename": None,
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


# ---------------------------------------------------------------------------
# サイドバー：ファイルアップロード
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

    # ファイルがアップロードされたら即時処理（ボタン不要）
    if uploaded_files:
        all_dfs: list[pd.DataFrame] = []
        all_mappings: list[dict] = []
        errors: list[str] = []
        needs_manual_mapping = False

        for f in uploaded_files:
            try:
                file_bytes = f.read()
                with st.spinner(f"読み込み中: {f.name}"):
                    df_result, report_result, mapping = _load_and_clean(file_bytes, f.name)

                if report_result is None:
                    # 標準列が見つからず手動マッピングが必要
                    st.session_state["df_raw_unmapped"] = df_result
                    st.session_state["unmapped_filename"] = f.name
                    needs_manual_mapping = True
                else:
                    all_dfs.append(df_result)
                    all_mappings.append(mapping)

                    fmt = mapping.get("format", "standard")
                    if fmt == "wide_daily":
                        st.caption(f"📋 {f.name}：横展開形式（1日1行×48列）")
                    else:
                        st.caption(f"✅ {f.name}：{len(df_result):,} 行")

            except Exception as e:
                errors.append(f"{f.name}: {e}")

        for e in errors:
            st.error(e)

        if all_dfs and not needs_manual_mapping:
            merged = pd.concat(all_dfs, ignore_index=True)
            st.session_state["df"] = merged
            st.session_state["clean_report"] = report_result
            st.session_state["mapping_confirmed"] = True
            st.success(f"✅ 合計 {len(merged):,} 行を読み込みました")

    # アップロードがクリアされたらリセット
    if not uploaded_files and st.session_state.get("df") is not None:
        if st.button("データをクリア"):
            st.session_state["df"] = None
            st.session_state["clean_report"] = None
            st.session_state["mapping_confirmed"] = False
            st.rerun()

    # 手動列マッピング（自動マッピング失敗時）
    if st.session_state.get("df_raw_unmapped") is not None and not st.session_state["mapping_confirmed"]:
        st.markdown("---")
        st.subheader("🔧 列マッピング")
        raw = st.session_state["df_raw_unmapped"]
        cols = list(raw.columns)

        sel_dt = st.selectbox("日時列 (datetime)", options=cols, index=0)
        sel_fac = st.selectbox("施設名列 (facility_name)", options=cols, index=min(1, len(cols)-1))
        sel_kwh = st.selectbox("使用量列 (consumption_kwh)", options=cols, index=min(2, len(cols)-1))

        if st.button("マッピングを確定", type="primary"):
            renamed = raw.rename(columns={sel_dt: "datetime", sel_fac: "facility_name", sel_kwh: "consumption_kwh"})
            df_clean, report = data_cleaner.clean(renamed)
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
            st.session_state["df"] = df_clean
            st.session_state["clean_report"] = report
            st.session_state["mapping_confirmed"] = True
            st.success(f"✅ サンプルデータを読み込みました（{len(df_clean):,} 行）")
        except FileNotFoundError:
            st.error("サンプルデータが見つかりません。generate_sample.py を実行してください。")


# ---------------------------------------------------------------------------
# データ品質レポート
# ---------------------------------------------------------------------------

df: pd.DataFrame | None = st.session_state.get("df")
report = st.session_state.get("clean_report")

if df is None:
    st.title("⚡ 電力需給分析ダッシュボード")
    st.info("👈 サイドバーからExcel / CSVをアップロードしてください。サンプルデータで動作確認もできます。")
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
# KPI メトリクス
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
    ts_data = analyzer.aggregate_30min(filtered, by_facility=by_fac)
    st.plotly_chart(
        visualizer.demand_timeseries(ts_data, title=f"電力使用量（30分値）— {period_option}"),
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
    （`analyzer.py` の `calc_supply_demand_balance()` / `visualizer.py` の `supply_demand_chart()` は実装済み）
    """)
