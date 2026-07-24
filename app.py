"""
app.py
電力需給分析ダッシュボード（Streamlit）— マルチページ・エントリポイント。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import cache_manager
import grouping
import supply_cache_manager

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
    "supply_sources": [],         # list[SupplySource] as dicts（パラメータ設定電源）
    "editing_source_idx": None,   # None=非編集, -1=新規追加, int=編集中インデックス
    "supply_df": None,            # アップロード済み供給データ DataFrame
    "supply_filenames": [],       # アップロード済みファイル名リスト
    "loaded_supply_file_ids": set(),
    "selected_supply_names": [],  # 表示対象として選択した電源名リスト
    "jepx_actual_df": None,       # アップロード済みJEPX実績価格 DataFrame
    "scenario_summaries": None,   # シナリオ比較結果
    "retail_fs_facilities": None, # list[dict]（FacilityConfig）。None=未ロード
    "retail_fs_tariffs": None,    # list[dict]（TariffPlan）。None=未ロード
    "retail_fs_result": None,     # run_fs() の戻り値
    "retail_fs_sensitivity": None,
    "retail_fs_co2": None,
    "fs_design": None,            # シナリオ設計ページが組み立てる小売FS前提条件一式
    "ppa_sim_result": None,
    "ppa_sim_battery_kwh": 0.0,
    "ppa_sim_mode": "basic",
    "ppa_sweep_df": None,
    "ppa_rec_kwh": 0,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── 需要データ・供給データの自動読み込み（保存済みの最新データがあれば復元） ──
if st.session_state["df"] is None:
    _entries = cache_manager.list_entries()
    if _entries:
        _latest = _entries[0]  # list_entries は新しい順
        try:
            st.session_state["df"] = cache_manager.load(_latest["cache_id"])
            st.session_state["mapping_confirmed"] = True
            st.session_state["loaded_filenames"] = _latest["filenames"]
            st.session_state["nav_end_date"] = pd.Timestamp(_latest["date_max"]).date()
            st.session_state["custom_groups"] = grouping.load_custom_groups()
        except Exception:
            pass

if st.session_state["supply_df"] is None:
    _supply_entries = supply_cache_manager.list_entries()
    if _supply_entries:
        _latest_s = _supply_entries[0]
        try:
            st.session_state["supply_df"] = supply_cache_manager.load(_latest_s["cache_id"])
            st.session_state["supply_filenames"] = _latest_s["filenames"]
            st.session_state["selected_supply_names"] = _latest_s["source_names"]
        except Exception:
            pass


# ---------------------------------------------------------------------------
# サイドバー：現在の読み込み状況
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚡ 電力需給分析")
    _df = st.session_state.get("df")
    if _df is not None:
        st.caption(
            f"📂 需要データ: {_df['datetime'].min().strftime('%Y/%m/%d')} 〜 "
            f"{_df['datetime'].max().strftime('%Y/%m/%d')}"
            f"（{_df['facility_name'].nunique()} 施設）"
        )
    else:
        st.caption("📂 需要データ未読み込み")
    _sdf = st.session_state.get("supply_df")
    if _sdf is not None:
        st.caption(f"⚡ 供給データ: {_sdf['source_name'].nunique()} 電源")
    st.markdown("---")


# ---------------------------------------------------------------------------
# ナビゲーション
# ---------------------------------------------------------------------------

pg = st.navigation({
    "データ管理": [
        st.Page("pages/data_upload.py", title="データ読み込み", icon="📂"),
        st.Page("pages/supply_sources.py", title="電源管理", icon="⚡"),
    ],
    "需要分析": [
        st.Page("pages/demand_curve.py", title="需要カーブ", icon="📈"),
        st.Page("pages/demand_pattern.py", title="需要パターン分析", icon="📊"),
    ],
    "需給・シミュレーション": [
        st.Page("pages/balance.py", title="需給分析", icon="⚡"),
        st.Page("pages/ppa.py", title="PPAシミュレーション", icon="☀️"),
    ],
    "🏪 小売FS": [
        st.Page("pages/fs_scenario_design.py", title="シナリオ設計", icon="📝"),
        st.Page("pages/fs_results.py", title="試算結果", icon="📊"),
        st.Page("pages/fs_comparison.py", title="シナリオ比較", icon="🔀"),
    ],
})
pg.run()
