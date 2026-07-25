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
st.caption("「シナリオ設計」ページで名前を付けて保存したシナリオを一覧・比較できます。")

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

saved_scenarios = scenario_manager.load_scenarios()

if not saved_scenarios:
    st.info(
        "保存済みシナリオはありません。「シナリオ設計」ページの下部で"
        "名前を付けて保存すると、ここに表示されます。"
    )
else:
    st.caption(f"保存済みシナリオ: {', '.join(s.name for s in saved_scenarios)}")

    del_col1, del_col2 = st.columns([3, 1])
    del_target = del_col1.selectbox("削除するシナリオ", [s.name for s in saved_scenarios], key="scenario_del_select")
    if del_col2.button("🗑 削除", key="delete_scenario_btn"):
        scenario_manager.delete_scenario(del_target)
        st.rerun()

    cmp_demand_df = common.render_period_selector(filtered_base, key_prefix="cmp")
    if not cmp_demand_df.empty:
        st.caption(
            f"対象期間: {cmp_demand_df['datetime'].min().strftime('%Y/%m/%d')} 〜 "
            f"{cmp_demand_df['datetime'].max().strftime('%Y/%m/%d')}"
        )
    _cmp_fingerprint = (
        tuple(sorted(s.name for s in saved_scenarios)),
        len(cmp_demand_df),
        str(cmp_demand_df["datetime"].min()) if not cmp_demand_df.empty else None,
        str(cmp_demand_df["datetime"].max()) if not cmp_demand_df.empty else None,
    )

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
            st.session_state["scenario_summaries_fingerprint"] = _cmp_fingerprint

    summaries = st.session_state.get("scenario_summaries")
    if summaries and st.session_state.get("scenario_summaries_fingerprint") != _cmp_fingerprint:
        st.warning(
            "⚠️ 比較対象期間または保存済みシナリオが変更されていますが、下記の結果はまだ変更前のものです。"
            "「▶ 全シナリオを一括計算して比較」を押して再計算してください。"
        )
    if summaries:
        st.plotly_chart(visualizer.scenario_comparison_chart(summaries), use_container_width=True)
        cmp_tbl = pd.DataFrame(summaries).T.rename(columns={
            "revenue": "売上高(円)", "cost_of_sales": "売上原価(円)", "gross_profit": "売上総利益(円)",
            "net_income": "当期純利益(円)",
        })
        st.dataframe(
            cmp_tbl, use_container_width=True,
            column_config={c: st.column_config.NumberColumn(c, format="%,.0f") for c in cmp_tbl.columns},
        )
