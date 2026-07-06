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
import solar_simulator
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
            df_raw, mapping = data_loader.load_file(buf, filename=f.name)
            missing = data_cleaner.validate_standard_columns(df_raw)
            if missing:
                st.session_state["df_raw_unmapped"] = df_raw
                prog.empty()
                return

            df_clean, _ = data_cleaner.clean(df_raw)
            df_clean["facility_name"] = df_clean["facility_name"].astype(object)
            all_dfs.append(df_clean)

            fmt = mapping.get("format", "")
            label = (
                "横展開（東北電力等）" if fmt == "wide_daily"
                else "エナリス形式" if fmt == "enaris"
                else "標準形式"
            )
            st.sidebar.caption(f"✅ {f.name}：{len(df_clean):,} 行 / {label}")
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    prog.progress(1.0, text="完了")
    prog.empty()
    for e in errors:
        st.sidebar.error(e)

    if all_dfs:
        merged = pd.concat(all_dfs, ignore_index=True)
        try:
            cache_manager.save(merged, [f.name for f in uploaded_files])
        except Exception:
            pass  # Cloud環境等でキャッシュ保存失敗しても処理継続
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

_dt_min = df["datetime"].dropna().min()
_dt_max = df["datetime"].dropna().max()
if pd.isna(_dt_min) or pd.isna(_dt_max):
    st.error("日時データが読み取れませんでした。ファイル形式を確認してください。")
    st.stop()
date_min: date = _dt_min.date()
date_max: date = _dt_max.date()

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

    # データ期間が delta より短い場合でも min_value <= max_value になるようクランプ
    _nav_min = min(date_min + delta, date_max)

    # セッション状態の nav_end_date が有効範囲に収まるよう補正
    nav_end = st.session_state.get("nav_end_date") or date_max
    nav_end = max(_nav_min, min(nav_end, date_max))

    with col_nav:
        c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
        with c1:
            if st.button("◀◀", help="データの先頭へ"):
                nav_end = _nav_min
                st.session_state["nav_end_date"] = nav_end
        with c2:
            if st.button("◀", help="前の期間へ"):
                nav_end = max(_nav_min, nav_end - delta)
                st.session_state["nav_end_date"] = nav_end
        with c3:
            nav_end = st.date_input(
                "表示終了日",
                value=nav_end,
                min_value=_nav_min,
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

# 施設フィルタのみ（日付フィルタなし）→ パターン分析の分析期間選択に使う
filtered_base = analyzer.filter_by_facilities(df, filtered_fac)

# 需要カーブ用：施設 + 表示期間フィルタ
filtered = analyzer.filter_by_period(filtered_base, start_dt, end_dt)

if filtered.empty:
    st.warning("選択した期間・施設にデータがありません。")
    st.stop()

# グループ列を付与（グループ合計モード用）
if agg_mode == "グループ合計" and group_mode != "施設個別":
    group_col = "region" if group_mode == "地域別" else "function_type"
    filtered      = grouping.add_group_column(filtered,      group_df, group_col)
    filtered_base = grouping.add_group_column(filtered_base, group_df, group_col)


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
    ["📈 需要カーブ", "📊 需要パターン分析", "☀️ PPAシミュレーション"]
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
    # ── 分析期間セレクタ（需要カーブの表示期間とは独立） ──
    p_col1, p_col2 = st.columns([2, 4])
    with p_col1:
        pat_period = st.selectbox(
            "分析期間",
            options=["全データ期間", "直近1年", "直近6か月", "直近3か月", "表示期間と同じ"],
            index=0,
            key="pat_period",
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

    # グループ合計モード時は group_label を facility_name として扱う
    if "group_label" in pat_df.columns:
        pat_df = pat_df.copy()
        pat_df["facility_name"] = pat_df["group_label"]

    by_fac = _by_fac(pat_df)

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
    st.subheader("☀️ 太陽光＋蓄電池 PPA シミュレーション")
    st.caption(
        "実際の需要データを使い、太陽光・蓄電池を導入した場合の自家消費率と蓄電池稼働を試算します。"
        "（日射量モデル：上田市周辺 NEDO 概算値）"
    )

    # ── ① 基本パラメータ ────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**① 導入容量・分析期間**")
        col_p1, col_p2, col_p3, col_p4 = st.columns(4)
        with col_p1:
            sim_solar_kw = st.number_input(
                "太陽光容量 (kWp)", min_value=1.0, max_value=5000.0,
                value=100.0, step=10.0, key="sim_solar_kw",
                help="パネルの定格出力。100 kWp 程度から試してください。",
            )
        with col_p2:
            sim_battery_kwh = st.number_input(
                "蓄電池容量 (kWh)", min_value=0.0, max_value=50000.0,
                value=0.0, step=10.0, key="sim_battery_kwh_input",
                help="0 の場合は蓄電池なし（太陽光のみ）のシミュレーションになります。",
            )
        with col_p3:
            sim_battery_eff = st.slider(
                "充放電往復効率 (%)", min_value=70, max_value=99,
                value=95, key="sim_battery_eff",
                help="充電→放電の往復効率。リチウムイオンは 90〜97 % 程度。",
            ) / 100.0
        with col_p4:
            sim_period = st.selectbox(
                "分析期間", ["全データ期間", "直近1年", "直近6か月", "直近3か月"],
                key="sim_period",
                help="KPI・月別グラフの集計範囲（需要カーブの表示期間とは独立）。",
            )

    # ── ② 充放電モード ───────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**② 充放電モード**")
        sim_mode = st.radio(
            "モードを選択",
            options=list(solar_simulator.BATTERY_MODE_LABELS.keys()),
            format_func=lambda x: {
                "basic":
                    "🔋 自家消費優先（基本） — 余剰太陽光で充電し、太陽光が足りない時に自動放電",
                "reserve":
                    "🚨 防災バッファ付き — 最低残量を常時確保しつつ自家消費優先",
                "peak_cut":
                    "⚡ ピークカット — デマンドが閾値を超えた時のみ放電（需要ピーク抑制）",
            }[x],
            key="sim_mode",
            horizontal=False,
        )

        # モード別オプション
        if sim_mode == "reserve":
            col_r1, col_r2 = st.columns([1, 3])
            with col_r1:
                sim_min_soc = st.slider(
                    "最低残量 (%)", min_value=10, max_value=70, value=30, step=5,
                    key="sim_min_soc",
                    help="常時確保しておく蓄電池残量。30% = 蓄電池容量の30%を常に備蓄。",
                )
            with col_r2:
                if sim_battery_kwh > 0:
                    reserve_kwh = sim_battery_kwh * sim_min_soc / 100
                    st.info(
                        f"蓄電池 {sim_battery_kwh:.0f} kWh の場合、"
                        f"**{reserve_kwh:.0f} kWh** を防災用に確保。"
                        f"日常使用できるのは **{sim_battery_kwh - reserve_kwh:.0f} kWh**。"
                    )
            sim_min_soc_f = float(sim_min_soc)
            sim_peak_kw = None
        elif sim_mode == "peak_cut":
            _bmax_sim_pre = filtered_base["datetime"].max()
            _auto_thresh = solar_simulator.auto_peak_threshold_kw(filtered_base)
            col_k1, col_k2 = st.columns([1, 3])
            with col_k1:
                sim_peak_kw = st.number_input(
                    "デマンド閾値 (kW)", min_value=1.0,
                    value=float(_auto_thresh), step=5.0,
                    key="sim_peak_kw",
                    help="この値を超える需要が発生したときのみ蓄電池が放電します。",
                )
            with col_k2:
                st.info(
                    f"自動計算値（需要の 80 パーセンタイル）= **{_auto_thresh:.1f} kW**。"
                    " 値を下げると蓄電池の放電機会が増え、自給率が向上します。"
                )
            sim_min_soc_f = 0.0
        else:
            sim_min_soc_f = 0.0
            sim_peak_kw = None

    # ── 分析期間データの選択 ────────────────────────────────────────────────
    _bmax_sim = filtered_base["datetime"].max()
    _sim_period_map = {
        "全データ期間": filtered_base,
        "直近1年":   analyzer.filter_by_period(filtered_base, _bmax_sim - timedelta(days=365), _bmax_sim),
        "直近6か月": analyzer.filter_by_period(filtered_base, _bmax_sim - timedelta(days=180), _bmax_sim),
        "直近3か月": analyzer.filter_by_period(filtered_base, _bmax_sim - timedelta(days=90),  _bmax_sim),
    }
    sim_base_df = _sim_period_map[sim_period]

    # ── 実行ボタン ───────────────────────────────────────────────────────────
    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        run_sim = st.button("▶ シミュレーション実行", type="primary", use_container_width=True)
    with col_btn2:
        run_sweep = st.button(
            "📊 適正蓄電池容量を診断", use_container_width=True,
            help="蓄電池容量を変えてシミュレーションし、最適容量を自動提案します（数秒かかります）。",
        )

    # ── シミュレーション実行 ─────────────────────────────────────────────────
    if run_sim:
        with st.spinner("シミュレーション計算中..."):
            _sim_result = solar_simulator.run_simulation(
                sim_base_df,
                solar_capacity_kw=sim_solar_kw,
                battery_capacity_kwh=sim_battery_kwh,
                battery_efficiency=sim_battery_eff,
                mode=sim_mode,
                min_soc_pct=sim_min_soc_f,
                peak_threshold_kw=sim_peak_kw,
            )
        st.session_state["ppa_sim_result"]      = _sim_result
        st.session_state["ppa_sim_battery_kwh"] = sim_battery_kwh
        st.session_state["ppa_sim_mode"]        = sim_mode

    # ── 容量診断（スイープ）────────────────────────────────────────────────
    if run_sweep:
        with st.spinner("容量診断中（数秒かかります）..."):
            _sweep_df, _rec_kwh = solar_simulator.sweep_battery_capacity(
                sim_base_df,
                solar_capacity_kw=sim_solar_kw,
                battery_efficiency=sim_battery_eff,
                mode=sim_mode,
                min_soc_pct=sim_min_soc_f,
                peak_threshold_kw=sim_peak_kw,
            )
        st.session_state["ppa_sweep_df"]  = _sweep_df
        st.session_state["ppa_rec_kwh"]   = _rec_kwh

    # ── 容量診断グラフ ────────────────────────────────────────────────────
    _sweep_df  = st.session_state.get("ppa_sweep_df")
    _rec_kwh   = st.session_state.get("ppa_rec_kwh", 0)
    if _sweep_df is not None:
        st.markdown("#### 📊 適正蓄電池容量 診断結果")
        rec_col1, rec_col2, rec_col3 = st.columns([1, 1, 2])
        rec_col1.metric("推奨蓄電池容量", f"{_rec_kwh:.0f} kWh")
        if not _sweep_df.empty:
            _rec_row = _sweep_df[_sweep_df["battery_kwh"] >= _rec_kwh]
            if not _rec_row.empty:
                rec_col2.metric(
                    "その時の自給率",
                    f"{_rec_row['self_sufficiency_rate'].iloc[0]:.1f}%",
                )
        with rec_col3:
            _mode_label = solar_simulator.BATTERY_MODE_LABELS.get(sim_mode, sim_mode)
            st.caption(
                f"モード: {_mode_label} ／ 太陽光: {sim_solar_kw:.0f} kWp ／ 分析期間: {sim_period}"
            )
        st.plotly_chart(
            visualizer.battery_sweep_chart(_sweep_df, _rec_kwh),
            use_container_width=True,
        )
        st.markdown("---")

    # ── シミュレーション結果 ─────────────────────────────────────────────────
    ppa_sim: pd.DataFrame | None = st.session_state.get("ppa_sim_result")

    if ppa_sim is None:
        st.info("パラメータを設定し「▶ シミュレーション実行」を押してください。")
    else:
        kpis = solar_simulator.calc_kpis(ppa_sim)
        _stored_mode = st.session_state.get("ppa_sim_mode", "basic")
        _mode_label  = solar_simulator.BATTERY_MODE_LABELS.get(_stored_mode, _stored_mode)

        st.markdown(f"#### シミュレーション結果　｜　モード: {_mode_label}")
        k1, k2, k3 = st.columns(3)
        k1.metric(
            "自家消費率", f"{kpis['self_consumption_rate']:.1f}%",
            help="発電量のうち自家消費（直接＋蓄電池経由）した割合",
        )
        k2.metric(
            "自給率", f"{kpis['self_sufficiency_rate']:.1f}%",
            help="総需要のうち太陽光＋蓄電池で賄えた割合",
        )
        k3.metric("発電量（期間合計）", _fmt(kpis["total_solar_kwh"]))

        k4, k5, k6 = st.columns(3)
        k4.metric("グリッド買電削減量", _fmt(kpis["grid_reduction_kwh"]))
        k5.metric("グリッド買電削減率", f"{kpis['grid_reduction_rate']:.1f}%")
        k6.metric(
            "系統への売電量", _fmt(kpis["total_grid_export_kwh"]),
            help="蓄電池に入りきらなかった余剰太陽光が系統へ流れた量",
        )

        st.markdown("---")

        # 表示期間でフィルタ（時系列グラフ用）
        sim_disp = ppa_sim[
            (ppa_sim["datetime"] >= start_dt) & (ppa_sim["datetime"] <= end_dt)
        ]
        if sim_disp.empty:
            sim_disp = ppa_sim

        period_label = f"{start_dt.strftime('%Y/%m/%d')} 〜 {end_dt.strftime('%Y/%m/%d')}"
        st.caption(f"📅 以下の時系列グラフは需要カーブの表示期間（{period_label}）を使用しています。")

        st.plotly_chart(
            visualizer.solar_supply_chart(sim_disp),
            use_container_width=True,
        )

        _stored_battery = st.session_state.get("ppa_sim_battery_kwh", 0)
        if _stored_battery > 0:
            st.plotly_chart(
                visualizer.battery_operation_chart(sim_disp, battery_capacity_kwh=_stored_battery),
                use_container_width=True,
            )

        st.plotly_chart(
            visualizer.monthly_self_consumption_bar(ppa_sim),
            use_container_width=True,
        )
