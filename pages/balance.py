"""
pages/balance.py
需給バランス分析（自社供給・相対電源を含めた需給の月次・時系列把握）。
"""

from __future__ import annotations

from datetime import timedelta

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
        "- **実データ**: 「データ読み込み」ページから Excel をアップロード\n"
        "- **推計値**: 「電源管理」ページでパラメータ設定"
    )
else:
    bc1, bc2 = st.columns([2, 4])
    with bc1:
        bal_period = st.selectbox(
            "分析期間",
            ["全データ期間", "直近1年", "直近6か月", "直近3か月"],
            index=0, key="bal_period",
        )
    bal_df_demand = common.filter_by_period_option(filtered_base, bal_period)
    with bc2:
        st.caption(
            f"需要データ: {bal_df_demand['datetime'].min().strftime('%Y/%m/%d')} 〜 "
            f"{bal_df_demand['datetime'].max().strftime('%Y/%m/%d')}  "
            f"（{len(bal_df_demand):,} 行）"
        )

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

    uploaded_names = sorted(_uploaded_supply["source_name"].unique()) if _uploaded_supply is not None else []
    param_names = [s.name for s in _param_sources]
    if uploaded_names:
        st.caption(f"📂 実データ: {', '.join(uploaded_names)}")
    if param_names:
        st.caption(f"⚙️ 推計値: {', '.join(param_names)}")

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
