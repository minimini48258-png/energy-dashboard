"""
app.py
電力需給分析ダッシュボード（Streamlit）
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import analyzer
import cache_manager
import data_cleaner
import data_loader
import financial_model
import grouping
import solar_simulator
import supply_cache_manager
import supply_loader
import supply_planner
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
    "nav_end_date": None,
    "custom_groups": {},
    "supply_sources": [],        # list[SupplySource] as dicts（パラメータ設定電源）
    "editing_source_idx": None,  # None=非編集, -1=新規追加, int=編集中インデックス
    "supply_df": None,           # アップロード済み供給データ DataFrame
    "supply_filenames": [],      # アップロード済みファイル名リスト
    "loaded_supply_file_ids": set(),
    "selected_supply_names": [], # 表示対象として選択した電源名リスト
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

    # ── 供給データアップロード ─────────────────────────────
    st.markdown("---")
    st.header("⚡ 供給データ読み込み")
    uploaded_supply = st.file_uploader(
        "供給側 Excel をアップロード（複数可）",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="supply_uploader",
    )
    if uploaded_supply:
        supply_ids = {f.file_id for f in uploaded_supply}
        if supply_ids != st.session_state["loaded_supply_file_ids"] or st.session_state["supply_df"] is None:
            supply_dfs, supply_names, supply_errors = [], [], []
            for f in uploaded_supply:
                try:
                    buf = io.BytesIO(f.read())
                    sdf, sname = supply_loader.load_supply_file(buf, filename=f.name)
                    supply_dfs.append(sdf)
                    supply_names.append(sname)
                    st.sidebar.caption(f"✅ {f.name}：{len(sdf):,} 行 / {sname}")
                except Exception as e:
                    supply_errors.append(f"{f.name}: {e}")
            for e in supply_errors:
                st.sidebar.error(e)
            if supply_dfs:
                merged_supply = pd.concat(supply_dfs, ignore_index=True)
                st.session_state["supply_df"] = merged_supply
                st.session_state["supply_filenames"] = supply_names
                st.session_state["loaded_supply_file_ids"] = supply_ids
                # 新規読み込み時は全電源を選択状態にする
                st.session_state["selected_supply_names"] = sorted(merged_supply["source_name"].unique().tolist())
    elif st.session_state["supply_df"] is not None and st.session_state["loaded_supply_file_ids"]:
        st.session_state["supply_df"] = None
        st.session_state["supply_filenames"] = []
        st.session_state["loaded_supply_file_ids"] = set()
        st.session_state["selected_supply_names"] = []

    if st.session_state["supply_df"] is not None:
        _sdf = st.session_state["supply_df"]
        _all_srcs = sorted(_sdf["source_name"].unique().tolist())
        # 発電所選択（複数電源がある場合のみ表示）
        if len(_all_srcs) > 1:
            _prev_sel = [s for s in st.session_state.get("selected_supply_names", _all_srcs) if s in _all_srcs]
            _sel_srcs = st.multiselect("📍 表示する発電所", _all_srcs, default=_prev_sel or _all_srcs)
            st.session_state["selected_supply_names"] = _sel_srcs
        else:
            st.session_state["selected_supply_names"] = _all_srcs
            st.caption(f"電源: {', '.join(_all_srcs)}")
        st.caption(
            f"{_sdf['datetime'].min().strftime('%Y/%m/%d')} 〜 "
            f"{_sdf['datetime'].max().strftime('%Y/%m/%d')}  "
            f"（{len(_sdf):,} 行）"
        )
        # 保存ボタン
        if st.button("💾 供給データを保存", key="save_supply_btn"):
            try:
                supply_cache_manager.save(_sdf, st.session_state.get("supply_filenames", []))
                st.success("保存しました")
                st.rerun()
            except Exception as _e:
                st.error(f"保存失敗: {_e}")

    # ── 保存済み供給データ ─────────────────────────────────
    _supply_entries = supply_cache_manager.list_entries()
    if _supply_entries:
        st.markdown("---")
        st.header("🗂 保存済み供給データ")
        for _smeta in _supply_entries:
            _src_preview = "、".join(_smeta["source_names"][:3])
            if len(_smeta["source_names"]) > 3:
                _src_preview += f" 他{len(_smeta['source_names'])-3}電源"
            _slabel = f"{_smeta['date_min']} 〜 {_smeta['date_max']}  |  {_smeta['rows']:,}行"
            with st.expander(f"⚡ {_src_preview}", expanded=False):
                st.caption(_slabel)
                st.caption(f"ファイル: {', '.join(_smeta['filenames'][:2])}")
                _sc1, _sc2 = st.columns(2)
                if _sc1.button("読み込む", key=f"load_supply_{_smeta['cache_id']}"):
                    _df_s = supply_cache_manager.load(_smeta["cache_id"])
                    st.session_state["supply_df"] = _df_s
                    st.session_state["supply_filenames"] = _smeta["filenames"]
                    st.session_state["loaded_supply_file_ids"] = set()
                    st.session_state["selected_supply_names"] = _smeta["source_names"]
                    st.rerun()
                if _sc2.button("削除", key=f"del_supply_{_smeta['cache_id']}"):
                    supply_cache_manager.delete(_smeta["cache_id"])
                    st.rerun()

    # ── 保存済み需要データ ────────────────────────────────────
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

        # 横展開・エナリス形式の誤検出を案内
        _has_time_cols = any(re.search(r"\d+:\d+", c) for c in cols)
        _has_nenmgd = "年月日" in cols
        if _has_nenmgd and _has_time_cols:
            st.warning(
                "⚠️ このファイルは横展開形式（1行＝1日・30分値×48列）の可能性があります。"
                " 手動マッピングでは正しく読み込めません。"
                " ファイル形式をご確認ください（東北電力 / エナリス形式）。"
            )

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
# 電源管理
# ---------------------------------------------------------------------------

_MONTH_NAMES = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]

def _source_form(prefix: str, defaults: dict | None = None) -> dict | None:
    """電源追加/編集フォーム。保存ボタンが押されたら dict を返す。"""
    d = defaults or {}
    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
    name     = col1.text_input("電源名",         value=d.get("name", ""), key=f"{prefix}_name")
    stype_lbl = col2.selectbox(
        "種別",
        options=list(supply_planner.SOURCE_TYPE_LABELS.values()),
        index=list(supply_planner.SOURCE_TYPE_LABELS.values()).index(
            supply_planner.SOURCE_TYPE_LABELS.get(d.get("source_type","hydro"), "水力")
        ),
        key=f"{prefix}_type",
    )
    cap  = col3.number_input("設備容量 (kW)", min_value=0.0, value=float(d.get("capacity_kw", 300.0)),
                              step=10.0, key=f"{prefix}_cap")
    cost = col4.number_input("発電コスト (円/kWh)", min_value=0.0,
                              value=float(d.get("cost_per_kwh", 8.0)), step=0.5, key=f"{prefix}_cost")

    # 月別稼働率
    st.caption("月別稼働率 (%)")
    monthly_default = d.get("monthly_utilization_pct", [80.0]*12)
    cols6a = st.columns(6)
    cols6b = st.columns(6)
    monthly = []
    for i, (mn, c) in enumerate(zip(_MONTH_NAMES[:6], cols6a)):
        monthly.append(c.number_input(mn, 0, 100, int(monthly_default[i]), key=f"{prefix}_m{i}"))
    for i, (mn, c) in enumerate(zip(_MONTH_NAMES[6:], cols6b)):
        monthly.append(c.number_input(mn, 0, 100, int(monthly_default[i+6]), key=f"{prefix}_m{i+6}"))

    # 時間帯別出力
    st.caption("時間帯別出力比")
    preset_opts = list(supply_planner.HOURLY_PRESETS.keys()) + ["カスタム"]
    hourly_default = d.get("hourly_pattern_pct", [100.0]*24)
    # 既存設定からプリセットを推定
    matched_preset = "カスタム"
    for pname, pvals in supply_planner.HOURLY_PRESETS.items():
        if pvals == hourly_default:
            matched_preset = pname
            break
    preset = st.radio("プリセット", preset_opts,
                      index=preset_opts.index(matched_preset),
                      horizontal=True, key=f"{prefix}_preset")
    if preset == "カスタム":
        hourly_df = pd.DataFrame({
            "時間帯": [f"{h:02d}:00" for h in range(24)],
            "出力比(%)": hourly_default,
        })
        edited_h = st.data_editor(
            hourly_df,
            column_config={"出力比(%)": st.column_config.NumberColumn(min_value=0, max_value=100)},
            hide_index=True, use_container_width=True, height=400, key=f"{prefix}_heditor",
        )
        hourly = edited_h["出力比(%)"].tolist()
    else:
        hourly = supply_planner.HOURLY_PRESETS[preset]
        st.plotly_chart(
            visualizer.hourly_pattern_bar(hourly, name or "電源"),
            use_container_width=True,
        )

    start_date_str = st.text_input("運転開始日 (YYYY-MM-DD、空欄=既存)",
                                    value=d.get("start_date") or "", key=f"{prefix}_start")

    if st.button("💾 保存", key=f"{prefix}_save"):
        if not name:
            st.error("電源名を入力してください。")
            return None
        return {
            "name": name,
            "source_type": supply_planner.SOURCE_TYPE_KEYS.get(stype_lbl, "hydro"),
            "capacity_kw": cap,
            "cost_per_kwh": cost,
            "monthly_utilization_pct": monthly,
            "hourly_pattern_pct": hourly,
            "start_date": start_date_str or None,
        }
    return None


with st.expander("⚡ 電源管理（供給側の設定）", expanded=False):
    st.caption("新電力として調達・運用する電源を登録します。需給分析・収支シミュレーションに使用されます。")

    sources_raw: list[dict] = st.session_state.get("supply_sources", [])
    sources = [supply_planner.SupplySource(**s) for s in sources_raw]

    # 登録済み電源一覧
    if sources:
        for idx, src in enumerate(sources):
            type_lbl = supply_planner.SOURCE_TYPE_LABELS.get(src.source_type, src.source_type)
            with st.container(border=True):
                h1, h2, h3, h_edit, h_del = st.columns([3, 2, 2, 1, 1])
                h1.markdown(f"**{src.name}**")
                h2.caption(f"{type_lbl} / {src.capacity_kw:.0f} kW")
                h3.caption(f"{src.cost_per_kwh:.1f} 円/kWh")
                if h_edit.button("編集", key=f"edit_{idx}"):
                    st.session_state["editing_source_idx"] = idx
                    st.rerun()
                if h_del.button("削除", key=f"del_src_{idx}"):
                    sources.pop(idx)
                    st.session_state["supply_sources"] = [asdict(s) for s in sources]
                    try:
                        supply_planner.save_sources(sources)
                    except Exception:
                        pass
                    st.rerun()
    else:
        st.info("電源が登録されていません。")

    editing_idx = st.session_state.get("editing_source_idx")

    # 編集フォーム
    if editing_idx is not None:
        label = "電源を編集" if editing_idx >= 0 else "電源を追加"
        st.markdown(f"#### {label}")
        defaults = asdict(sources[editing_idx]) if editing_idx >= 0 else None
        result = _source_form(prefix=f"src_form_{editing_idx}", defaults=defaults)
        if result:
            new_src = supply_planner.SupplySource(**result)
            if editing_idx >= 0:
                sources[editing_idx] = new_src
            else:
                sources.append(new_src)
            st.session_state["supply_sources"] = [asdict(s) for s in sources]
            st.session_state["editing_source_idx"] = None
            try:
                supply_planner.save_sources(sources)
            except Exception:
                pass
            st.rerun()
        if st.button("キャンセル", key="cancel_form"):
            st.session_state["editing_source_idx"] = None
            st.rerun()
    else:
        if st.button("＋ 電源を追加"):
            st.session_state["editing_source_idx"] = -1
            st.rerun()


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

tab_demand, tab_pattern, tab_balance, tab_pnl, tab_supply = st.tabs([
    "📈 需要カーブ",
    "📊 需要パターン分析",
    "⚡ 需給分析",
    "💰 収支シミュレーション",
    "☀️ PPAシミュレーション",
])


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


def _supply_for_period(start: date, end: date) -> pd.DataFrame | None:
    """選択中の電源・指定期間でフィルタした supply_df を返す。なければ None。"""
    _sdf = st.session_state.get("supply_df")
    if _sdf is None or _sdf.empty:
        return None
    _sel = st.session_state.get("selected_supply_names", [])
    if not _sel:
        return None
    _sdf = _sdf[_sdf["source_name"].isin(_sel)].copy()
    _sdf = _sdf[(_sdf["datetime"].dt.date >= start) & (_sdf["datetime"].dt.date <= end)]
    return _sdf if not _sdf.empty else None


with tab_demand:
    period_label = f"{start_dt.strftime('%Y/%m/%d')} 〜 {end_dt.strftime('%Y/%m/%d')}"
    _chart_supply = _supply_for_period(start_dt, end_dt)
    if _chart_supply is not None:
        st.plotly_chart(
            visualizer.demand_supply_timeseries(
                _ts_data(filtered), _chart_supply,
                title=f"需要 vs 供給（30分値）— {period_label}",
            ),
            use_container_width=True,
        )
    else:
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


with tab_balance:
    st.subheader("⚡ 需給バランス分析")

    # 供給データの統合（アップロード実データ + パラメータ設定）
    _bal_supply_parts = []
    _uploaded_supply = st.session_state.get("supply_df")
    if _uploaded_supply is not None:
        _sel_names = st.session_state.get("selected_supply_names", [])
        _filtered_upload = (
            _uploaded_supply[_uploaded_supply["source_name"].isin(_sel_names)]
            if _sel_names else _uploaded_supply
        )
        _bal_supply_parts.append(_filtered_upload)
    _param_sources = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

    if not _bal_supply_parts and not _param_sources:
        st.info(
            "供給データがありません。\n\n"
            "- **実データ**: サイドバーの「供給データ読み込み」から Excel をアップロード\n"
            "- **推計値**: 「電源管理」Expander でパラメータ設定"
        )
    else:
        # 分析期間セレクタ
        bc1, bc2 = st.columns([2, 4])
        with bc1:
            bal_period = st.selectbox(
                "分析期間",
                ["全データ期間", "直近1年", "直近6か月", "直近3か月", "表示期間と同じ"],
                index=0, key="bal_period",
            )
        _bmax = filtered_base["datetime"].max()
        if bal_period == "全データ期間":
            bal_df_demand = filtered_base.copy()
        elif bal_period == "直近1年":
            bal_df_demand = analyzer.filter_by_period(filtered_base, _bmax - timedelta(days=365), _bmax)
        elif bal_period == "直近6か月":
            bal_df_demand = analyzer.filter_by_period(filtered_base, _bmax - timedelta(days=180), _bmax)
        elif bal_period == "直近3か月":
            bal_df_demand = analyzer.filter_by_period(filtered_base, _bmax - timedelta(days=90), _bmax)
        else:
            bal_df_demand = filtered.copy()
        with bc2:
            st.caption(
                f"需要データ: {bal_df_demand['datetime'].min().strftime('%Y/%m/%d')} 〜 "
                f"{bal_df_demand['datetime'].max().strftime('%Y/%m/%d')}  "
                f"（{len(bal_df_demand):,} 行）"
            )

        # パラメータ設定電源のプロファイルを追加
        bal_timestamps = pd.DatetimeIndex(bal_df_demand["datetime"].sort_values().unique())
        if _param_sources:
            _bal_supply_parts.append(
                supply_planner.combine_supply_profiles(_param_sources, bal_timestamps)
            )
        bal_supply_df = (
            pd.concat(_bal_supply_parts, ignore_index=True)
            if _bal_supply_parts
            else pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
        )

        # 需給バランス計算
        balance_df   = financial_model.calc_balance(bal_df_demand, bal_supply_df)
        source_names = sorted(bal_supply_df["source_name"].unique().tolist())
        kpis         = financial_model.calc_balance_kpis(balance_df)

        # 供給データソースの表示
        uploaded_names = sorted(_uploaded_supply["source_name"].unique()) if _uploaded_supply is not None else []
        param_names    = [s.name for s in _param_sources]
        if uploaded_names:
            st.caption(f"📂 実データ: {', '.join(uploaded_names)}")
        if param_names:
            st.caption(f"⚙️ 推計値: {', '.join(param_names)}")

        # KPI
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("総需要",       f"{kpis['total_demand_kwh']/1000:.1f} MWh")
        k2.metric("自社供給",     f"{kpis['total_supply_kwh']/1000:.1f} MWh")
        k3.metric("自給率",       f"{kpis['self_sufficiency_pct']:.1f} %")
        k4.metric("余剰（売電可）", f"{kpis['surplus_kwh']/1000:.1f} MWh")
        k5.metric("不足（JEPX）",  f"{kpis['deficit_kwh']/1000:.1f} MWh")

        st.markdown("---")
        try:
            st.plotly_chart(
                visualizer.supply_demand_balance_chart(balance_df, source_names),
                use_container_width=True,
            )
        except Exception as _chart_err:
            st.error(f"チャート描画エラー: {type(_chart_err).__name__}: {_chart_err}")
            st.write("**デバッグ情報**")
            st.write(f"balance_df columns: {list(balance_df.columns)}")
            st.write(f"source_names: {source_names}")
            st.write(f"balance_df shape: {balance_df.shape}")
            import traceback
            st.code(traceback.format_exc())


with tab_pnl:
    st.subheader("💰 収支シミュレーション")

    _pnl_supply_parts = []
    _pnl_uploaded = st.session_state.get("supply_df")
    if _pnl_uploaded is not None:
        _pnl_sel = st.session_state.get("selected_supply_names", [])
        _pnl_filtered = (
            _pnl_uploaded[_pnl_uploaded["source_name"].isin(_pnl_sel)]
            if _pnl_sel else _pnl_uploaded
        )
        _pnl_supply_parts.append(_pnl_filtered)
    sources_for_pnl = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

    if not _pnl_supply_parts and not sources_for_pnl:
        st.info("サイドバーから供給データをアップロードするか、「電源管理」で電源を登録してください。")
    else:
        # ── 価格設定 ────────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**① 価格設定**")
            pc1, pc2, pc3, pc4 = st.columns(4)
            retail_price   = pc1.number_input("小売単価 (円/kWh)",          min_value=0.0, value=25.0, step=0.5)
            surplus_price  = pc2.number_input("余剰売電単価 (円/kWh)",       min_value=0.0, value=7.0,  step=0.5)
            imb_factor     = pc3.number_input("インバランス率 (%)",           min_value=0.0, value=10.0, step=1.0,
                                               help="調達量のうち計画誤差でインバランスになる割合")
            imb_premium    = pc4.number_input("インバランスプレミアム (円/kWh)", min_value=0.0, value=3.0, step=0.5,
                                               help="インバランス精算の追加コスト")

        with st.container(border=True):
            st.markdown("**② JEPX 想定単価（時間帯別）**")
            st.caption("デフォルトは 2023〜24 年平均の目安値。実データに合わせて調整してください。")
            jepx_labels = {
                "深夜（0〜6時）":    list(range(0, 6)),
                "朝（6〜9時）":      list(range(6, 9)),
                "日中（9〜16時）":   list(range(9, 16)),
                "夕方（16〜20時）":  list(range(16, 20)),
                "夜（20〜24時）":    list(range(20, 24)),
            }
            jepx_defaults = {
                "深夜（0〜6時）": 9.0, "朝（6〜9時）": 18.0,
                "日中（9〜16時）": 15.0, "夕方（16〜20時）": 21.0, "夜（20〜24時）": 12.0,
            }
            jepx_cols = st.columns(5)
            jepx_block_prices = {}
            for (label, hours), col in zip(jepx_labels.items(), jepx_cols):
                jepx_block_prices[label] = col.number_input(
                    label, min_value=0.0,
                    value=jepx_defaults[label], step=0.5, key=f"jepx_{label}",
                )
            jepx_by_hour: dict[int, float] = {}
            for label, hours in jepx_labels.items():
                for h in hours:
                    jepx_by_hour[h] = jepx_block_prices[label]

        with st.container(border=True):
            st.markdown("**③ 発電コスト（電源別）**")
            # アップロード電源とパラメータ設定電源を統合してコスト入力欄を生成
            _all_src_names: list[str] = []
            _all_src_defaults: dict[str, float] = {}
            if _pnl_uploaded is not None:
                for _sn in sorted(_pnl_uploaded["source_name"].unique()):
                    _all_src_names.append(_sn)
                    _all_src_defaults[_sn] = 8.0  # アップロード電源のデフォルト発電コスト
            for _src in sources_for_pnl:
                if _src.name not in _all_src_names:
                    _all_src_names.append(_src.name)
                _all_src_defaults[_src.name] = _src.cost_per_kwh

            source_costs: dict[str, float] = {}
            if _all_src_names:
                _n_cols = min(len(_all_src_names), 4)
                src_cost_cols = st.columns(_n_cols)
                for i, _sn in enumerate(_all_src_names):
                    col = src_cost_cols[i % _n_cols]
                    source_costs[_sn] = col.number_input(
                        f"{_sn} (円/kWh)",
                        min_value=0.0, value=_all_src_defaults[_sn], step=0.5,
                        key=f"cost_{_sn}",
                    )
            else:
                st.caption("電源が登録されていません。")

        # ── 分析期間 ────────────────────────────────────────────────────────
        pnl_period = st.selectbox(
            "分析期間", ["全データ期間", "直近1年", "直近6か月", "直近3か月"],
            key="pnl_period",
        )
        _pmax = filtered_base["datetime"].max()
        _pmap = {
            "全データ期間": filtered_base,
            "直近1年":   analyzer.filter_by_period(filtered_base, _pmax - timedelta(days=365), _pmax),
            "直近6か月": analyzer.filter_by_period(filtered_base, _pmax - timedelta(days=180), _pmax),
            "直近3か月": analyzer.filter_by_period(filtered_base, _pmax - timedelta(days=90),  _pmax),
        }
        pnl_demand_df = _pmap[pnl_period]

        if st.button("▶ 収支シミュレーション実行", type="primary"):
            with st.spinner("計算中..."):
                _pnl_ts = pd.DatetimeIndex(pnl_demand_df["datetime"].sort_values().unique())
                if sources_for_pnl:
                    _pnl_supply_parts.append(
                        supply_planner.combine_supply_profiles(sources_for_pnl, _pnl_ts)
                    )
                _pnl_supply = (
                    pd.concat(_pnl_supply_parts, ignore_index=True)
                    if _pnl_supply_parts
                    else pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
                )
                _pnl_balance = financial_model.calc_balance(pnl_demand_df, _pnl_supply)
                _pnl_df      = financial_model.calc_pnl(
                    _pnl_balance, _pnl_supply, source_costs,
                    retail_price_yen     = retail_price,
                    jepx_price_by_hour   = jepx_by_hour,
                    surplus_sell_price_yen = surplus_price,
                    inbalance_factor_pct = imb_factor,
                    inbalance_premium_yen = imb_premium,
                )
                st.session_state["pnl_result"]  = _pnl_df
                st.session_state["pnl_monthly"] = financial_model.monthly_pnl_summary(_pnl_df)

        pnl_result  = st.session_state.get("pnl_result")
        pnl_monthly = st.session_state.get("pnl_monthly")

        if pnl_result is None:
            st.info("価格を設定して「収支シミュレーション実行」を押してください。")
        else:
            # KPI
            total_revenue = float(pnl_result["retail_revenue"].sum() + pnl_result["surplus_revenue"].sum())
            total_cost    = float(pnl_result["gen_cost"].sum() + pnl_result["procurement_cost"].sum() + pnl_result["inbalance_cost"].sum())
            total_profit  = float(pnl_result["profit"].sum())
            months        = pnl_monthly["month"].nunique() if pnl_monthly is not None else 1

            st.markdown("---")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("総収入（期間）",    f"{total_revenue/10000:.0f} 万円")
            r2.metric("総コスト（期間）",   f"{total_cost/10000:.0f} 万円")
            r3.metric("事業利益（期間）",   f"{total_profit/10000:.0f} 万円",
                       delta=f"月平均 {total_profit/10000/max(months,1):.0f} 万円")
            r4.metric("収支率",
                       f"{total_profit/total_revenue*100:.1f} %" if total_revenue > 0 else "—")

            if pnl_monthly is not None:
                st.plotly_chart(
                    visualizer.monthly_pnl_chart(pnl_monthly),
                    use_container_width=True,
                )

                with st.expander("月別数値テーブル"):
                    tbl = pnl_monthly.copy()
                    tbl["month"] = tbl["month"].dt.strftime("%Y-%m")
                    tbl = tbl.rename(columns={
                        "month": "月", "retail_revenue": "小売収入(円)",
                        "surplus_revenue": "余剰売電(円)", "gen_cost": "発電コスト(円)",
                        "procurement_cost": "JEPX調達(円)", "inbalance_cost": "インバランス(円)",
                        "profit": "利益(円)", "demand_kwh": "需要(kWh)",
                        "deficit_kwh": "不足(kWh)", "surplus_kwh": "余剰(kWh)",
                    })
                    st.dataframe(tbl.set_index("月"), use_container_width=True)


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
