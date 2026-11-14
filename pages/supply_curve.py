"""
pages/supply_curve.py
供給カーブ（発電量の30分値の時系列グラフ、需要データがあれば需要も重ねて表示）。
需要分析の「需要カーブ」と同じ構成。
"""

from __future__ import annotations

import streamlit as st

import analyzer
import common
import visualizer

st.title("🔆 供給カーブ")

sdf = common.require_supply_data()
filtered_base, group_mode = common.render_source_filter(sdf)
filtered, start_dt, end_dt, agg_mode = common.render_supply_period_and_kpis(filtered_base, group_mode)

period_label = common.format_date_range(start_dt, end_dt)
# 集計単位（電源別／グループ合計／全電源合計）に合わせて facility_name を読み替えてから集計する
series = common.supply_series_for(filtered, agg_mode)
ts = analyzer.aggregate_30min(series, by_facility=True)

st.plotly_chart(
    visualizer.demand_timeseries(
        ts, title=f"発電量（30分値）— {period_label}", y_label="発電量 (kWh/30min)", entity="電源",
    ),
    use_container_width=True,
)

# ── 需要データがあれば、同じ期間の需要（全施設合計）と重ねて表示 ──
_df = st.session_state.get("df")
if _df is not None and not _df.empty:
    demand = analyzer.filter_by_period(_df, start_dt, end_dt)
    if demand.empty:
        st.info(
            f"需要データ期間（{common.format_date_range(_df['datetime'].min(), _df['datetime'].max())}）が"
            f"現在の表示期間（{period_label}）と重なっていないため、需要との重ね合わせは表示していません。"
        )
    else:
        demand_total = analyzer.aggregate_30min(demand, by_facility=False)
        supply_for_chart = series.rename(
            columns={"facility_name": "source_name", "consumption_kwh": "supply_kwh"}
        )
        st.plotly_chart(
            visualizer.demand_supply_timeseries(
                demand_total, supply_for_chart, title=f"需要（全施設合計） vs 発電量 — {period_label}",
            ),
            use_container_width=True,
        )
