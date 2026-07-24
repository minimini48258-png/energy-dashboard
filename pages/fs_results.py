"""
pages/fs_results.py
小売FS 試算結果：シナリオ設計ページで組み立てた前提条件（fs_design）で試算を実行し、
損益計算書・グラフ・CO2排出量・JEPX感度分析を表示する。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import common
import financial_model
import retail_fs
import supply_planner
import visualizer

st.title("📊 小売FS：試算結果")

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

fs_design = st.session_state.get("fs_design")
if not fs_design:
    st.info("👈 まず「シナリオ設計」ページで料金プラン・施設設定などを設定してください。")
    st.stop()

tariff_plans = [retail_fs.TariffPlan(**p) for p in fs_design["tariff_plans"]]
facility_configs = [retail_fs.FacilityConfig(**c) for c in fs_design["facility_configs"]]
plan_names = [p.name for p in tariff_plans]
transmission_rates = {vc: retail_fs.TransmissionRate(**r) for vc, r in fs_design["transmission_rates"].items()}
jepx_by_month_hour = {
    tuple(int(x) for x in k.split("-")): v for k, v in fs_design["jepx_by_month_hour"].items()
}
_jepx_actual_df = st.session_state.get("jepx_actual_df")
jepx_actual_series = _jepx_actual_df.set_index("datetime")["jepx_price_yen"] if _jepx_actual_df is not None else None

_uploaded = st.session_state.get("supply_df")
_supply_parts = []
if _uploaded is not None:
    _sel = st.session_state.get("selected_supply_names", [])
    _filtered_upload = _uploaded[_uploaded["source_name"].isin(_sel)] if _sel else _uploaded
    _supply_parts.append(_filtered_upload)
_sources = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

fs_period = st.selectbox("分析期間", ["全データ期間", "直近1年", "直近6か月", "直近3か月"], key="fs_period")
fs_demand_df = common.filter_by_period_option(filtered_base, fs_period)

if st.button("▶ 小売FS試算実行", type="primary", key="run_retail_fs"):
    if fs_demand_df.empty:
        st.warning("選択した分析期間にデータがありません。分析期間を変更してください。")
    elif not any(c.tariff_plan_name in plan_names for c in facility_configs):
        st.warning("有効な料金プランが割り当てられた施設がありません。「シナリオ設計」ページで料金プランを選択してください。")
    else:
        try:
            with st.spinner("計算中..."):
                fs_ts = pd.DatetimeIndex(fs_demand_df["datetime"].sort_values().unique())
                supply_parts = list(_supply_parts)
                if _sources:
                    supply_parts.append(supply_planner.combine_supply_profiles(_sources, fs_ts))
                fs_supply_df = (
                    pd.concat(supply_parts, ignore_index=True) if supply_parts
                    else pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
                )
                fs_balance_df = financial_model.calc_balance(fs_demand_df, fs_supply_df)

                result = retail_fs.run_fs(
                    demand_df=fs_demand_df,
                    balance_df=fs_balance_df,
                    supply_df=fs_supply_df,
                    facility_configs=facility_configs,
                    tariff_plans=tariff_plans,
                    transmission_rates=transmission_rates,
                    source_costs=fs_design["source_costs"],
                    jepx_price_by_month_hour=jepx_by_month_hour,
                    fuel_adjustment_yen_per_kwh=fs_design["fuel_adjustment_yen_per_kwh"],
                    renewable_levy_yen_per_kwh=fs_design["renewable_levy_yen_per_kwh"],
                    capacity_unit_yen_per_kw_year=fs_design["capacity_unit_yen_per_kw_year"],
                    reserve_margin_pct=fs_design["reserve_margin_pct"],
                    jepx_actual_series=jepx_actual_series,
                )
                st.session_state["retail_fs_result"] = result

                _annual = result["annual"]
                _other_revenue = _annual["basic_revenue"] + _annual["volumetric_revenue"] + _annual["fuel_adj_revenue"]
                _other_cost = _annual["transmission_cost"] + _annual["capacity_contribution"]
                st.session_state["retail_fs_sensitivity"] = retail_fs.sensitivity_jepx_shift(
                    fs_balance_df, fs_supply_df, fs_design["source_costs"], jepx_by_month_hour,
                    fs_design["reserve_margin_pct"],
                    base_gross_profit=_annual["gross_profit"],
                    other_revenue=_other_revenue, other_cost=_other_cost,
                )
                st.session_state["retail_fs_co2"] = retail_fs.calc_co2_and_local_ratio(
                    fs_balance_df, fs_supply_df, fs_design["emission_factors"], fs_design["local_flags"],
                )
        except Exception as e:
            st.error("小売FSの試算中にエラーが発生しました。入力内容を確認するか、下記の詳細を開発担当へ共有してください。")
            st.exception(e)
            st.session_state["retail_fs_result"] = None

fs_result = st.session_state.get("retail_fs_result")

if fs_result is None:
    st.info("設定を確認して「小売FS試算実行」を押してください。")
else:
    try:
        _annual = fs_result["annual"]
        _monthly = fs_result["monthly"].copy()
        _monthly["month"] = pd.to_datetime(_monthly["month"])
        for _col in _monthly.columns:
            if _col != "month":
                _monthly[_col] = pd.to_numeric(_monthly[_col], errors="coerce").fillna(0.0)
        _co2 = st.session_state.get("retail_fs_co2") or {}

        st.markdown("---")
        st.markdown("**損益計算書ふうサマリー（期間合計）**")
        _pl_rows = [
            ("売上高", _annual["sales_revenue"], 100.0),
            ("　基本料金", _annual["basic_revenue"], None),
            ("　従量料金", _annual["volumetric_revenue"], None),
            ("　燃料費調整額", _annual["fuel_adj_revenue"], None),
            ("　再エネ賦課金（預り金）", _annual["levy_revenue"], None),
            ("　市場売却収入", _annual["market_sale_revenue"], None),
            ("売上原価", _annual["cost_of_sales"] + _annual["levy_revenue"], None),
            ("　電力調達費", _annual["procurement_cost"], None),
            ("　託送料金", _annual["transmission_cost"], None),
            ("　容量拠出金", _annual["capacity_contribution"], None),
            ("　再エネ賦課金（納付）", _annual["levy_revenue"], None),
            ("売上総利益（粗利益）", _annual["gross_profit"], _annual["gross_margin_pct"]),
        ]
        _pl_df = pd.DataFrame(_pl_rows, columns=["項目", "金額(円)", "対売上高(%)"])
        _pl_df["金額(円)"] = _pl_df["金額(円)"].round(0).astype(int)
        st.dataframe(_pl_df.set_index("項目"), use_container_width=True)

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("売上高", f"{_annual['sales_revenue']/10000:,.0f} 万円")
        r2.metric("売上総利益（粗利益）", f"{_annual['gross_profit']/10000:,.0f} 万円")
        r3.metric("粗利益率", f"{_annual['gross_margin_pct']:.1f} %")
        r4.metric("契約電力合計", f"{_annual['contract_kw_total']:,.0f} kW")

        if _co2:
            c1, c2 = st.columns(2)
            c1.metric("CO2排出量", f"{_co2['co2_total_t']:,.1f} t-CO2")
            c2.metric("地産電源比率", f"{_co2['local_ratio_pct']:.1f} %")

        if not _monthly.empty:
            st.caption(
                "単位: 千円。売上高は基本料金＋従量料金＋燃料費調整額＋市場売却収入（再エネ賦課金を除く）。"
                "売上総利益（粗利益）＝売上高－再エネ賦課金－売上原価。"
            )
            _chart_df = _monthly.rename(columns={"sales_revenue": "revenue"})[
                ["month", "revenue", "cost_of_sales", "gross_profit"]
            ]
            st.plotly_chart(visualizer.monthly_pnl_chart(_chart_df), use_container_width=True)
            with st.expander("月別数値テーブル"):
                _tbl = _monthly.copy()
                _tbl["month"] = _tbl["month"].dt.strftime("%Y-%m")
                st.dataframe(_tbl.set_index("month"), use_container_width=True)

        _sens_df = st.session_state.get("retail_fs_sensitivity")
        if _sens_df is not None and not _sens_df.empty:
            st.markdown("**感度分析：JEPX価格が変動した場合の売上総利益（粗利益）**")
            st.plotly_chart(visualizer.retail_fs_sensitivity_chart(_sens_df), use_container_width=True)
    except Exception as e:
        st.error(
            "結果の表示中にエラーが発生しました。下記の詳細を共有いただければ原因を特定できます。"
            "「🔄 試算結果をクリア」を押してから設定を見直し、再度試算してください。"
        )
        st.exception(e)
        if st.button("🔄 試算結果をクリア", key="fs_clear_result"):
            st.session_state["retail_fs_result"] = None
            st.session_state["retail_fs_sensitivity"] = None
            st.session_state["retail_fs_co2"] = None
            st.rerun()
