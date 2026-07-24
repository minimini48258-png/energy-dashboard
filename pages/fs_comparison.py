"""
pages/fs_comparison.py
小売FS シナリオ比較：シナリオ設計ページの内容を名前付きで保存し、
複数シナリオを一括計算して売上高・売上原価・粗利益を比較する。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import common
import scenario_manager
import visualizer

st.title("🔀 小売FS：シナリオ比較")
st.caption("「シナリオ設計」ページの現在の設定を、名前を付けて保存・比較できます。")

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

fs_design = st.session_state.get("fs_design")

with st.container(border=True):
    st.markdown("**現在のシナリオ設計を保存**")
    if not fs_design:
        st.info("👈 まず「シナリオ設計」ページで設定してください。")
    else:
        sc1, sc2 = st.columns([3, 1])
        scenario_name = sc1.text_input("シナリオ名", key="scenario_name_input", placeholder="例: 標準シナリオ")
        if sc2.button("💾 保存", key="save_scenario_btn"):
            if not scenario_name:
                st.error("シナリオ名を入力してください。")
            else:
                _scenario = scenario_manager.Scenario(
                    name=scenario_name,
                    fs_design=fs_design,
                    supply_sources=st.session_state.get("supply_sources", []),
                )
                scenario_manager.save_scenario(_scenario)
                st.success(f"シナリオ「{scenario_name}」を保存しました。")
                st.rerun()

saved_scenarios = scenario_manager.load_scenarios()

if not saved_scenarios:
    st.caption("保存済みシナリオはありません。")
else:
    st.markdown("---")
    st.caption(f"保存済みシナリオ: {', '.join(s.name for s in saved_scenarios)}")

    del_col1, del_col2 = st.columns([3, 1])
    del_target = del_col1.selectbox("削除するシナリオ", [s.name for s in saved_scenarios], key="scenario_del_select")
    if del_col2.button("🗑 削除", key="delete_scenario_btn"):
        scenario_manager.delete_scenario(del_target)
        st.rerun()

    period = st.selectbox("比較対象期間", ["全データ期間", "直近1年", "直近6か月", "直近3か月"], key="cmp_period")
    cmp_demand_df = common.filter_by_period_option(filtered_base, period)

    if st.button("▶ 全シナリオを一括計算して比較", key="compare_scenarios_btn"):
        with st.spinner("全シナリオを計算中..."):
            summaries = {}
            for sc in saved_scenarios:
                try:
                    fs_result = scenario_manager.run_scenario(sc, cmp_demand_df)
                    summaries[sc.name] = scenario_manager.annual_summary(fs_result)
                except Exception as e:
                    st.error(f"シナリオ「{sc.name}」の計算でエラーが発生しました: {e}")
            st.session_state["scenario_summaries"] = summaries

    summaries = st.session_state.get("scenario_summaries")
    if summaries:
        st.plotly_chart(visualizer.scenario_comparison_chart(summaries), use_container_width=True)
        cmp_tbl = pd.DataFrame(summaries).T.rename(columns={
            "revenue": "売上高(円)", "cost_of_sales": "売上原価(円)", "gross_profit": "売上総利益(円)",
        })
        st.dataframe(cmp_tbl, use_container_width=True)
