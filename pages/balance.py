"""
pages/balance.py
需給バランス分析（自社供給・相対電源を含めた需給の月次・時系列把握）。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import analyzer
import common
import financial_model
import supply_planner
import visualizer

st.title("⚡ 需給バランス分析")

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

_uploaded_supply = st.session_state.get("supply_df")
_param_sources_all = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

uploaded_names = sorted(_uploaded_supply["source_name"].unique().tolist()) if _uploaded_supply is not None else []
param_names_all = [s.name for s in _param_sources_all]
all_source_names = uploaded_names + param_names_all

if not all_source_names:
    st.info(
        "供給データがありません。\n\n"
        "- **実データ**: 「データ読み込み」ページから Excel をアップロード\n"
        "- **推計値**: 「電源管理」ページでパラメータ設定"
    )
else:
    bc1, bc2 = st.columns([2, 4])
    with bc1:
        start_dt, end_dt, bal_period = common.render_flexible_period(
            filtered_base,
            key_prefix="bal",
            options=["全データ期間", "1年", "3か月", "1か月", "1週間", "1日", "カスタム"],
            default_index=0,
        )
    bal_df_demand = analyzer.filter_by_period(filtered_base, start_dt, end_dt)
    with bc2:
        if bal_df_demand.empty:
            st.warning("選択した期間・施設にデータがありません。")
            st.stop()
        st.caption(
            f"需要データ: {bal_df_demand['datetime'].min().strftime('%Y/%m/%d')} 〜 "
            f"{bal_df_demand['datetime'].max().strftime('%Y/%m/%d')}  "
            f"（{len(bal_df_demand):,} 行）"
        )

    _prev_sel = [n for n in st.session_state.get("bal_selected_sources", all_source_names) if n in all_source_names]
    sel_sources = st.multiselect(
        "表示する電源", options=all_source_names, default=_prev_sel, key="bal_selected_sources",
    )
    if not sel_sources:
        st.warning("電源を1つ以上選択してください。")
        st.stop()

    _bal_supply_parts = []
    if _uploaded_supply is not None:
        _sel_uploaded = [n for n in uploaded_names if n in sel_sources]
        if _sel_uploaded:
            _bal_supply_parts.append(_uploaded_supply[_uploaded_supply["source_name"].isin(_sel_uploaded)])
    _param_sources = [s for s in _param_sources_all if s.name in sel_sources]

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

    balance_df = financial_model.calc_balance(bal_df_demand, bal_supply_df)
    source_names = sorted(bal_supply_df["source_name"].unique().tolist())
    kpis = financial_model.calc_balance_kpis(balance_df)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("総需要", f"{kpis['total_demand_kwh']/1000:.1f} MWh")
    k2.metric("自社供給", f"{kpis['total_supply_kwh']/1000:.1f} MWh")
    k3.metric("自給率", f"{kpis['self_sufficiency_pct']:.1f} %")
    k4.metric("余剰（売電可）", f"{kpis['surplus_kwh']/1000:.1f} MWh")
    k5.metric("不足（JEPX）", f"{kpis['deficit_kwh']/1000:.1f} MWh")

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
