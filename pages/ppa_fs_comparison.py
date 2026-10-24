"""
pages/ppa_fs_comparison.py
PPA採算性：シナリオ比較。保存済みPPAシナリオを一覧・比較する。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ppa_retail_calc as calc
import ppa_scenario_manager

st.title("🔀 PPA採算性：シナリオ比較")
st.caption(
    "「シナリオ設計」ページで保存したシナリオを一覧・比較します。MVPでは「小売＋PPA一体型」を"
    "中心に、住宅/事業所それぞれのシナリオを複製・保存・比較する運用を想定しています。"
)

scenarios = ppa_scenario_manager.load_scenarios()

if not scenarios:
    st.info("保存済みシナリオがありません。「シナリオ設計」ページの末尾からシナリオを保存してください。")
    st.stop()

del_col1, del_col2 = st.columns([3, 1])
del_name = del_col1.selectbox("削除するシナリオ", [s.name for s in scenarios])
if del_col2.button("🗑 削除", disabled=len(scenarios) <= 0):
    ppa_scenario_manager.delete_scenario(del_name)
    st.rerun()

st.markdown("---")

rows = []
for sc in scenarios:
    inputs = calc.inputs_from_dict(sc.inputs)
    result = calc.simulate(inputs)
    breakeven = calc.compute_breakeven(inputs)
    summary = result.summary
    rows.append({
        "シナリオ": sc.name,
        "区分": "住宅" if inputs.customer.segment == "residential" else "事業所",
        "提案単価(円/kWh)": round(inputs.customer.unified_rate, 1),
        "顧客削減額/年(円)": round(summary.customer_annual_saving_year1),
        "事業IRR": None if summary.project_irr_pct is None else round(summary.project_irr_pct, 2),
        "エクイティIRR": None if summary.equity_irr_pct is None else round(summary.equity_irr_pct, 2),
        "NPV(事業,万円)": round(summary.npv_project / 10_000, 1),
        "最低DSCR": None if summary.min_dscr is None else round(summary.min_dscr, 2),
        "事業成立最低単価(円/kWh)": None if breakeven.breakeven_rate is None else round(breakeven.breakeven_rate, 1),
        "保存日時": sc.created_at,
    })

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)
