"""
pages/demand_curve.py
需要カーブ（30分値の時系列グラフ、供給データがあれば発電量も表示）。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import analyzer
import common
import visualizer

st.title("📈 需要カーブ")

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)
filtered, filtered_base, start_dt, end_dt, agg_mode = common.render_period_and_kpis(
    filtered_base, group_mode, group_df,
)


def _ts_data(filt: pd.DataFrame) -> pd.DataFrame:
    if agg_mode == "グループ合計" and "group_label" in filt.columns:
        return analyzer.aggregate_30min_by_group(filt)
    elif agg_mode == "施設別":
        return analyzer.aggregate_30min(filt, by_facility=True)
    else:
        return analyzer.aggregate_30min(filt, by_facility=False)


def _supply_for_period(start: date, end: date) -> pd.DataFrame | None:
    """選択中の電源・指定期間でフィルタした supply_df を返す。なければ None。"""
    _sdf = st.session_state.get("supply_df")
    if _sdf is None or _sdf.empty:
        return None
    _sel = st.session_state.get("selected_supply_names", [])
    if not _sel:
        return None
    _sdf = _sdf[_sdf["source_name"].isin(_sel)].copy()
    _start_ts = pd.Timestamp(start)
    _end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    _sdf = _sdf[(_sdf["datetime"] >= _start_ts) & (_sdf["datetime"] < _end_ts)]
    return _sdf if not _sdf.empty else None


period_label = f"{start_dt.strftime('%Y/%m/%d')} 〜 {end_dt.strftime('%Y/%m/%d')}"
_chart_supply = _supply_for_period(start_dt, end_dt)
st.plotly_chart(
    visualizer.demand_timeseries(_ts_data(filtered), title=f"電力使用量（30分値）— {period_label}"),
    use_container_width=True,
)

_sdf_raw = st.session_state.get("supply_df")
_sel_names = st.session_state.get("selected_supply_names", [])

if _sdf_raw is not None:
    if not _sel_names:
        _sel_names = sorted(_sdf_raw["source_name"].unique().tolist())
        st.session_state["selected_supply_names"] = _sel_names
        _chart_supply = _supply_for_period(start_dt, end_dt)

    if _chart_supply is not None and not _chart_supply.empty:
        st.plotly_chart(
            visualizer.supply_timeseries(_chart_supply, title=f"発電量（30分値）— {period_label}"),
            use_container_width=True,
        )
    else:
        _s_min = _sdf_raw["datetime"].min().strftime("%Y/%m/%d")
        _s_max = _sdf_raw["datetime"].max().strftime("%Y/%m/%d")
        st.info(
            f"供給データ期間（{_s_min} 〜 {_s_max}）が"
            f"現在の表示期間（{period_label}）と重なっていません。"
            "日付ナビゲーションで表示期間を供給データの期間に合わせてください。"
        )
