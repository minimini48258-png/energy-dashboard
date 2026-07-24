"""
pages/data_upload.py
需要データ・供給データのアップロードと、保存済みデータの読込・グループ管理。
"""

from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st

import cache_manager
import data_cleaner
import data_loader
import grouping
import supply_cache_manager
import supply_loader

st.title("📂 データ読み込み")


# ---------------------------------------------------------------------------
# 需要データアップロード
# ---------------------------------------------------------------------------

def _process_files(uploaded_files) -> None:
    current_ids = {f.file_id for f in uploaded_files}
    if current_ids == st.session_state["loaded_file_ids"] and st.session_state["df"] is not None:
        return

    all_dfs, errors = [], []
    prog = st.progress(0, text="読み込み準備中...")

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
            st.caption(f"✅ {f.name}：{len(df_clean):,} 行 / {label}")
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    prog.progress(1.0, text="完了")
    prog.empty()
    for e in errors:
        st.error(e)

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
        st.session_state["custom_groups"] = grouping.load_custom_groups()


st.header("需要データ")
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

if st.session_state.get("df") is not None:
    _df = st.session_state["df"]
    st.success(
        f"✅ 読み込み中：{_df['datetime'].min().strftime('%Y/%m/%d')} 〜 "
        f"{_df['datetime'].max().strftime('%Y/%m/%d')}　"
        f"（{_df['facility_name'].nunique()} 施設 / {len(_df):,} 行）"
    )

# ── 手動列マッピング ──────────────────────────────────
if st.session_state.get("df_raw_unmapped") is not None and not st.session_state["mapping_confirmed"]:
    st.markdown("---")
    st.subheader("🔧 列マッピング")
    raw = st.session_state["df_raw_unmapped"]
    cols = list(raw.columns)

    _has_time_cols = any(re.search(r"\d+:\d+", c) for c in cols)
    _has_nenmgd = "年月日" in cols
    if _has_nenmgd and _has_time_cols:
        st.warning(
            "⚠️ このファイルは横展開形式（1行＝1日・30分値×48列）の可能性があります。"
            " 手動マッピングでは正しく読み込めません。"
            " ファイル形式をご確認ください（東北電力 / エナリス形式）。"
        )

    sel_dt = st.selectbox("日時列", options=cols, index=0)
    sel_fac = st.selectbox("施設名列", options=cols, index=min(1, len(cols) - 1))
    sel_kwh = st.selectbox("使用量列", options=cols, index=min(2, len(cols) - 1))
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

report = st.session_state.get("clean_report")
if report and report.has_issues:
    with st.expander("⚠️ データ品質レポート", expanded=False):
        c = st.columns(4)
        c[0].metric("総行数", f"{report.total_rows:,}")
        c[1].metric("クリーン後", f"{report.rows_after:,}")
        c[2].metric("重複削除", f"{report.duplicate_rows:,}")
        c[3].metric("欠損値", f"{report.missing_consumption:,}")
        if report.datetime_gaps:
            st.warning("\n".join(f"- {g}" for g in report.datetime_gaps))

# ── 保存済み需要データ ────────────────────────────────────
entries = cache_manager.list_entries()
if entries:
    st.markdown("---")
    st.subheader("🗂 保存済みデータ")
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

# ---------------------------------------------------------------------------
# 供給データアップロード
# ---------------------------------------------------------------------------

st.markdown("---")
st.header("⚡ 供給データ")
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
                st.caption(f"✅ {f.name}：{len(sdf):,} 行 / {sname}")
            except Exception as e:
                supply_errors.append(f"{f.name}: {e}")
        for e in supply_errors:
            st.error(e)
        if supply_dfs:
            merged_supply = pd.concat(supply_dfs, ignore_index=True)
            st.session_state["supply_df"] = merged_supply
            st.session_state["supply_filenames"] = supply_names
            st.session_state["loaded_supply_file_ids"] = supply_ids
            st.session_state["selected_supply_names"] = sorted(merged_supply["source_name"].unique().tolist())
elif st.session_state["supply_df"] is not None and st.session_state["loaded_supply_file_ids"]:
    st.session_state["supply_df"] = None
    st.session_state["supply_filenames"] = []
    st.session_state["loaded_supply_file_ids"] = set()
    st.session_state["selected_supply_names"] = []

if st.session_state["supply_df"] is not None:
    _sdf = st.session_state["supply_df"]
    _all_srcs = sorted(_sdf["source_name"].unique().tolist())
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
    if st.button("💾 供給データを保存", key="save_supply_btn"):
        try:
            supply_cache_manager.save(_sdf, st.session_state.get("supply_filenames", []))
            st.success("保存しました")
            st.rerun()
        except Exception as _e:
            st.error(f"保存失敗: {_e}")

_supply_entries = supply_cache_manager.list_entries()
if _supply_entries:
    st.markdown("---")
    st.subheader("🗂 保存済み供給データ")
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

# ---------------------------------------------------------------------------
# グループ管理
# ---------------------------------------------------------------------------

if st.session_state.get("df") is not None:
    st.markdown("---")
    st.header("🏷 グループ管理")
    st.caption("自動検出した地域・機能種別を編集できます。変更後は「保存」を押してください。")

    _df = st.session_state["df"]
    facility_names = sorted(_df["facility_name"].unique().tolist())
    custom_groups = st.session_state.get("custom_groups", {})
    group_df = grouping.build_group_df(facility_names, custom_groups)

    edited = st.data_editor(
        group_df,
        column_config={
            "facility_name": st.column_config.TextColumn("施設名", disabled=True),
            "region": st.column_config.TextColumn("地域"),
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
        st.success("保存しました")

if st.session_state.get("df") is None:
    st.markdown("---")
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
