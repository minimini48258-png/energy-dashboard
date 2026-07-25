"""
pages/fs_results.py
小売FS 試算結果：シナリオ設計ページで組み立てた前提条件（fs_design）で試算を実行し、
損益計算書・需要分析・施設別収支・資金繰りをタブで表示する。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import analyzer
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
capital_yen = fs_design.get("capital_yen", 0.0)
collection_lag_months = int(fs_design.get("collection_lag_months", 2))
procurement_ratios = fs_design.get("procurement_ratios", {})

_uploaded = st.session_state.get("supply_df")
_supply_parts = []
if _uploaded is not None:
    _sel = st.session_state.get("selected_supply_names", [])
    _filtered_upload = _uploaded[_uploaded["source_name"].isin(_sel)] if _sel else _uploaded
    _supply_parts.append(_filtered_upload)
_sources = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

fs_demand_df = common.render_period_selector(filtered_base, key_prefix="fs")

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
                fs_supply_df = supply_planner.apply_procurement_ratios(fs_supply_df, procurement_ratios)
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
                    sga_items=fs_design.get("sga_items", {}),
                    corporate_tax_rate_pct=fs_design.get("corporate_tax_rate_pct", retail_fs.DEFAULT_CORPORATE_TAX_RATE_PCT),
                )
                st.session_state["retail_fs_result"] = result
                st.session_state["fs_demand_df"] = fs_demand_df

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
        _result_demand_df = st.session_state.get("fs_demand_df", fs_demand_df)

        st.markdown("---")
        tab_pl, tab_demand, tab_facility, tab_cashflow = st.tabs(
            ["📊 損益計算書", "📈 需要分析", "🏢 施設別収支", "💰 資金繰り"]
        )

        # ── 📊 損益計算書 ────────────────────────────────────────────
        with tab_pl:
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
                ("販管費", _annual["sga_cost"], None),
            ]
            for _item, _amount in _annual.get("sga_breakdown", {}).items():
                _pl_rows.append((f"　{_item}", _amount, None))
            _pl_rows += [
                ("営業利益", _annual["operating_profit"], _annual["operating_margin_pct"]),
                ("法人税等", _annual["corporate_tax"], None),
                ("当期純利益", _annual["net_income"], _annual["net_margin_pct"]),
            ]
            _pl_df = pd.DataFrame(_pl_rows, columns=["項目", "金額(円)", "対売上高(%)"])
            _pl_df["金額(円)"] = _pl_df["金額(円)"].round(0).astype(int)
            st.dataframe(
                _pl_df.set_index("項目"),
                use_container_width=True,
                column_config={
                    "金額(円)": st.column_config.NumberColumn("金額(円)", format="%,d"),
                    "対売上高(%)": st.column_config.NumberColumn("対売上高(%)", format="%.1f%%"),
                },
            )

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("売上高", f"{_annual['sales_revenue']/10000:,.0f} 万円")
            r2.metric("売上総利益（粗利益）", f"{_annual['gross_profit']/10000:,.0f} 万円")
            r3.metric("営業利益", f"{_annual['operating_profit']/10000:,.0f} 万円")
            r4.metric("当期純利益", f"{_annual['net_income']/10000:,.0f} 万円",
                       delta=f"純利益率 {_annual['net_margin_pct']:.1f} %")

            c1, c2, c3 = st.columns(3)
            c1.metric("契約電力合計", f"{_annual['contract_kw_total']:,.0f} kW")
            if _co2:
                c2.metric("CO2排出量", f"{_co2['co2_total_t']:,.1f} t-CO2")
                c3.metric("地産電源比率", f"{_co2['local_ratio_pct']:.1f} %")

            if not _monthly.empty:
                st.caption(
                    "単位: 千円。売上高は基本料金＋従量料金＋燃料費調整額＋市場売却収入（再エネ賦課金を除く）。"
                    "売上総利益（粗利益）＝売上高－再エネ賦課金－売上原価。"
                )
                _chart_df = _monthly.rename(columns={"sales_revenue": "revenue"})[
                    ["month", "revenue", "cost_of_sales", "gross_profit"]
                ]
                st.plotly_chart(visualizer.monthly_pnl_chart(_chart_df), use_container_width=True)

                st.markdown("**月別収支の内訳**")
                st.plotly_chart(visualizer.monthly_breakdown_chart(_monthly), use_container_width=True)

                with st.expander("月別数値テーブル"):
                    _tbl = _monthly.copy()
                    _tbl["month"] = _tbl["month"].dt.strftime("%Y-%m")
                    _tbl_col_config = {
                        c: st.column_config.NumberColumn(c, format="%.1f%%" if c.endswith("_pct") else "%,.0f")
                        for c in _tbl.columns if c != "month"
                    }
                    st.dataframe(_tbl.set_index("month"), use_container_width=True, column_config=_tbl_col_config)

            _sens_df = st.session_state.get("retail_fs_sensitivity")
            if _sens_df is not None and not _sens_df.empty:
                st.markdown("**感度分析：JEPX価格が変動した場合の売上総利益（粗利益）**")
                st.plotly_chart(visualizer.retail_fs_sensitivity_chart(_sens_df), use_container_width=True)

        # ── 📈 需要分析 ──────────────────────────────────────────────
        with tab_demand:
            st.caption("この試算で使用した需要データの分析です。")
            if _result_demand_df is None or _result_demand_df.empty:
                st.info("需要データがありません。")
            else:
                d1, d2, d3 = st.columns(3)
                d1.metric("総需要", f"{_result_demand_df['consumption_kwh'].sum()/1000:,.1f} MWh")
                d2.metric("対象施設数", f"{_result_demand_df['facility_name'].nunique()} 施設")
                d3.metric(
                    "対象期間",
                    f"{_result_demand_df['datetime'].min().strftime('%Y/%m/%d')} 〜 "
                    f"{_result_demand_df['datetime'].max().strftime('%Y/%m/%d')}",
                )
                col_l, col_r = st.columns(2)
                with col_l:
                    st.plotly_chart(
                        visualizer.monthly_bar(analyzer.aggregate_monthly(_result_demand_df, by_facility=False)),
                        use_container_width=True,
                    )
                with col_r:
                    st.plotly_chart(
                        visualizer.hourly_avg_bar(analyzer.aggregate_hourly_avg(_result_demand_df, by_facility=False)),
                        use_container_width=True,
                    )
                col_l2, col_r2 = st.columns(2)
                with col_l2:
                    st.plotly_chart(
                        visualizer.weekday_holiday_line(analyzer.weekday_vs_holiday(_result_demand_df)),
                        use_container_width=True,
                    )
                with col_r2:
                    st.plotly_chart(
                        visualizer.facility_ranking_bar(analyzer.facility_annual_ranking(_result_demand_df)),
                        use_container_width=True,
                    )

        # ── 🏢 施設別収支 ────────────────────────────────────────────
        with tab_facility:
            _fac_rev = fs_result.get("facility_revenue")
            _fac_trans = fs_result.get("facility_transmission")
            if _fac_rev is None or _fac_rev.empty:
                st.info("施設別のデータがありません。")
            else:
                _fac_pl = retail_fs.calc_facility_pl(_fac_rev, _fac_trans, _annual)
                st.caption(
                    "託送料金は施設ごとの実額、電力調達費・容量拠出金はkWh実績に応じた按分（簡易配賦）です。"
                    "販管費・法人税は会社全体の費用のため、施設別の粗利益には含めていません。"
                )
                _fac_disp = _fac_pl.rename(columns={
                    "facility_name": "施設名", "kwh": "使用量(kWh)", "revenue": "売上高(円)",
                    "transmission_cost": "託送料金(円)", "allocated_cost": "配賦コスト(円)",
                    "cost_of_sales": "売上原価(円)", "gross_profit": "粗利益(円)", "gross_margin_pct": "粗利率(%)",
                })
                st.dataframe(
                    _fac_disp.set_index("施設名"), use_container_width=True,
                    column_config={
                        "使用量(kWh)": st.column_config.NumberColumn("使用量(kWh)", format="%,.0f"),
                        "売上高(円)": st.column_config.NumberColumn("売上高(円)", format="%,.0f"),
                        "託送料金(円)": st.column_config.NumberColumn("託送料金(円)", format="%,.0f"),
                        "配賦コスト(円)": st.column_config.NumberColumn("配賦コスト(円)", format="%,.0f"),
                        "売上原価(円)": st.column_config.NumberColumn("売上原価(円)", format="%,.0f"),
                        "粗利益(円)": st.column_config.NumberColumn("粗利益(円)", format="%,.0f"),
                        "粗利率(%)": st.column_config.NumberColumn("粗利率(%)", format="%.1f%%"),
                    },
                )
                _fac_summaries = {
                    row["facility_name"]: {
                        "revenue": row["revenue"], "cost_of_sales": row["cost_of_sales"],
                        "gross_profit": row["gross_profit"],
                    }
                    for row in _fac_pl.to_dict("records")
                }
                st.plotly_chart(
                    visualizer.scenario_comparison_chart(_fac_summaries, title="施設別 売上高・売上原価・粗利益"),
                    use_container_width=True,
                )

        # ── 💰 資金繰り ──────────────────────────────────────────────
        with tab_cashflow:
            st.caption(
                f"簡易モデル：売上代金の入金は発生月から{collection_lag_months}ヶ月遅れると仮定しています"
                "（「シナリオ設計」⑧で変更可）。費用（電力調達費・託送料金・容量拠出金・販管費・法人税等）"
                "は発生月に支払われるものとして扱い、減価償却・設備投資は考慮しません。"
                "現金残高＝資本金＋月次キャッシュフローの累積。"
            )
            _cf = retail_fs.calc_cash_flow(_monthly, capital_yen, revenue_collection_lag_months=collection_lag_months)
            cf1, cf2, cf3 = st.columns(3)
            cf1.metric("資本金（期首現金残高）", f"{capital_yen/10000:,.0f} 万円")
            cf2.metric("期末現金残高", f"{_cf['cash_balance'].iloc[-1]/10000:,.0f} 万円" if not _cf.empty else "—")
            _min_balance = _cf["cash_balance"].min() if not _cf.empty else 0.0
            cf3.metric("期間中の最低残高", f"{_min_balance/10000:,.0f} 万円")
            if _min_balance < 0:
                st.warning("⚠️ 期間中に現金残高がマイナスになる月があります。資本金の増額や資金調達を検討してください。")

            if not _cf.empty:
                st.plotly_chart(visualizer.cash_flow_chart(_cf), use_container_width=True)
                with st.expander("月別キャッシュフロー・テーブル"):
                    _cf_tbl = _cf.copy()
                    _cf_tbl["month"] = _cf_tbl["month"].dt.strftime("%Y-%m")
                    _cf_tbl = _cf_tbl.rename(columns={
                        "month": "月", "cash_in": "入金(円)", "cash_out": "出金(円)",
                        "net_cash_flow": "月次キャッシュフロー(円)", "cash_balance": "現金残高(円)",
                    }).set_index("月")
                    st.dataframe(
                        _cf_tbl, use_container_width=True,
                        column_config={c: st.column_config.NumberColumn(c, format="%,.0f") for c in _cf_tbl.columns},
                    )
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
