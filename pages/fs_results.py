"""
pages/fs_results.py
小売FS 試算結果：シナリオ設計ページで組み立てた前提条件（fs_design）で試算を実行し、
損益計算書・需要分析・施設別収支・資金繰りをタブで表示する。
"""

from __future__ import annotations

import json

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


def _result_fingerprint(demand_df: pd.DataFrame, design: dict) -> tuple:
    """分析期間＋シナリオ設計の内容から、結果が最新かどうかを判定するための指紋を作る。"""
    if demand_df.empty:
        period_key = (0, None, None)
    else:
        period_key = (len(demand_df), str(demand_df["datetime"].min()), str(demand_df["datetime"].max()))
    try:
        design_key = json.dumps(design, sort_keys=True, default=str)
    except Exception:
        design_key = str(design)
    return (period_key, design_key)


if not fs_demand_df.empty:
    st.caption(
        f"対象期間: {fs_demand_df['datetime'].min().strftime('%Y/%m/%d')} 〜 "
        f"{fs_demand_df['datetime'].max().strftime('%Y/%m/%d')}"
    )

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
                    fip_indexed_sources=fs_design.get("fip_indexed_sources", {}),
                )
                st.session_state["retail_fs_result"] = result
                st.session_state["fs_demand_df"] = fs_demand_df
                st.session_state["fs_supply_df"] = fs_supply_df
                st.session_state["fs_result_fingerprint"] = _result_fingerprint(fs_demand_df, fs_design)

                _annual = result["annual"]
                _other_revenue = _annual["basic_revenue"] + _annual["volumetric_revenue"] + _annual["fuel_adj_revenue"]
                _other_cost = _annual["transmission_cost"] + _annual["capacity_contribution"]
                st.session_state["retail_fs_sensitivity"] = retail_fs.sensitivity_jepx_shift(
                    fs_balance_df, fs_supply_df, fs_design["source_costs"], jepx_by_month_hour,
                    fs_design["reserve_margin_pct"],
                    base_gross_profit=_annual["gross_profit"],
                    other_revenue=_other_revenue, other_cost=_other_cost,
                    fip_indexed_sources=fs_design.get("fip_indexed_sources", {}),
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
    _current_fingerprint = _result_fingerprint(fs_demand_df, fs_design)
    _stored_fingerprint = st.session_state.get("fs_result_fingerprint")
    if _stored_fingerprint is not None and _current_fingerprint != _stored_fingerprint:
        st.warning(
            "⚠️ 分析期間または設定が変更されていますが、下記の結果はまだ変更前のものです。"
            "「▶ 小売FS試算実行」を押して再計算してください。"
        )
    try:
        _annual = fs_result["annual"]
        _monthly = fs_result["monthly"].copy()
        _monthly["month"] = pd.to_datetime(_monthly["month"])
        for _col in _monthly.columns:
            if _col != "month":
                _monthly[_col] = pd.to_numeric(_monthly[_col], errors="coerce").fillna(0.0)
        _co2 = st.session_state.get("retail_fs_co2") or {}
        _result_demand_df = st.session_state.get("fs_demand_df", fs_demand_df)
        _result_supply_df = st.session_state.get("fs_supply_df")

        st.markdown("---")
        tab_pl, tab_jepx, tab_demand, tab_pattern8, tab_facility, tab_cashflow = st.tabs(
            ["📊 損益計算書", "🔌 JEPX取引", "📈 需要分析", "📅 8パターン分析", "🏢 施設別収支", "💰 資金繰り"]
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

        # ── 🔌 JEPX取引 ──────────────────────────────────────────────
        with tab_jepx:
            st.caption(
                "この試算で使用したJEPX想定単価（実績データがあればそちらを優先）と、"
                "不足分（JEPXからの調達）・余剰分（JEPXへの売電）の推移を表示します。"
            )
            if _result_demand_df is None or _result_demand_df.empty:
                st.info("需要データがありません。")
            else:
                _jepx_balance_df = financial_model.calc_balance(
                    _result_demand_df,
                    _result_supply_df if _result_supply_df is not None else pd.DataFrame(
                        columns=["datetime", "source_name", "supply_kwh"]
                    ),
                )
                _jepx_detail = retail_fs.calc_jepx_market_detail(
                    _jepx_balance_df, jepx_by_month_hour, jepx_actual_series=jepx_actual_series,
                )

                _freq_label = st.radio("表示単位", ["月次", "日次"], horizontal=True, key="jepx_tab_freq")
                _freq = "M" if _freq_label == "月次" else "D"
                _jepx_agg = retail_fs.aggregate_jepx_market_detail(_jepx_detail, freq=_freq)

                if _jepx_agg.empty:
                    st.info("データがありません。")
                else:
                    j1, j2, j3, j4 = st.columns(4)
                    j1.metric("調達量合計（不足分）", f"{_jepx_agg['deficit_kwh'].sum():,.0f} kWh")
                    j2.metric("調達コスト合計", f"{_jepx_agg['procurement_cost'].sum()/10000:,.0f} 万円")
                    j3.metric("売電量合計（余剰分）", f"{_jepx_agg['surplus_kwh'].sum():,.0f} kWh")
                    j4.metric("売電収入合計", f"{_jepx_agg['sale_revenue'].sum()/10000:,.0f} 万円")

                    st.plotly_chart(
                        visualizer.jepx_price_trend_chart(_jepx_agg, freq_label=_freq_label),
                        use_container_width=True,
                    )
                    st.plotly_chart(
                        visualizer.jepx_volume_chart(_jepx_agg, freq_label=_freq_label),
                        use_container_width=True,
                    )
                    with st.expander(f"{_freq_label}数値テーブル"):
                        _jepx_tbl = _jepx_agg.rename(columns={
                            "period": "期間", "jepx_price_avg": "JEPX想定単価平均(円/kWh)",
                            "deficit_kwh": "調達量(kWh)", "surplus_kwh": "売電量(kWh)",
                            "procurement_cost": "調達コスト(円)", "sale_revenue": "売電収入(円)",
                            "net": "純額(円)",
                        }).set_index("期間")
                        st.dataframe(
                            _jepx_tbl, use_container_width=True,
                            column_config={
                                c: st.column_config.NumberColumn(c, format="%,.1f" if "単価" in c else "%,.0f")
                                for c in _jepx_tbl.columns
                            },
                        )

                _fip_detail = retail_fs.calc_fip_source_detail(
                    _result_supply_df if _result_supply_df is not None else pd.DataFrame(
                        columns=["datetime", "source_name", "supply_kwh"]
                    ),
                    jepx_by_month_hour, fs_design.get("source_costs", {}),
                    fip_indexed_sources=fs_design.get("fip_indexed_sources", {}),
                    jepx_actual_series=jepx_actual_series,
                )
                if not _fip_detail.empty:
                    st.markdown("**JEPX価格連動電源（FIP買取等）の明細**")
                    st.caption(
                        "登録した供給量の全量を「JEPX想定単価＋スプレッド」で買い取る前提のため、"
                        "自家消費しきれず余剰分をJEPX想定単価（スプレッドなし）で再売電すると、"
                        "その差額（スプレッド分）が電源1kWhあたりの目減りになります。"
                    )
                    _fip_disp = _fip_detail.rename(columns={
                        "source_name": "電源名", "kwh": "供給量(kWh)",
                        "avg_jepx_price": "平均JEPX単価(円/kWh)", "spread": "スプレッド(円/kWh)",
                        "avg_unit_cost": "実効調達単価(円/kWh)", "total_cost": "総調達コスト(円)",
                    })
                    st.dataframe(
                        _fip_disp.set_index("電源名"), use_container_width=True,
                        column_config={
                            "供給量(kWh)": st.column_config.NumberColumn("供給量(kWh)", format="%,.0f"),
                            "平均JEPX単価(円/kWh)": st.column_config.NumberColumn("平均JEPX単価(円/kWh)", format="%.2f"),
                            "スプレッド(円/kWh)": st.column_config.NumberColumn("スプレッド(円/kWh)", format="%.2f"),
                            "実効調達単価(円/kWh)": st.column_config.NumberColumn("実効調達単価(円/kWh)", format="%.2f"),
                            "総調達コスト(円)": st.column_config.NumberColumn("総調達コスト(円)", format="%,.0f"),
                        },
                    )

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

        # ── 📅 8パターン分析 ──────────────────────────────────────────
        with tab_pattern8:
            st.caption(
                "この試算で使用した需要・供給データをもとに、季節（春夏秋冬）×平日/休日の組み合わせごとに、"
                "同じ時間帯の実績を平均した「代表的な1日」の需給バランス（30分値）を比較します。"
            )
            if _result_demand_df is None or _result_demand_df.empty:
                st.info("需要データがありません。")
            else:
                _p8_supply_df = _result_supply_df if _result_supply_df is not None else pd.DataFrame(
                    columns=["datetime", "source_name", "supply_kwh"]
                )
                _p8_source_names = (
                    sorted(_p8_supply_df["source_name"].unique().tolist()) if not _p8_supply_df.empty else []
                )

                _p8_demand_total = _result_demand_df.groupby("datetime", as_index=False)["consumption_kwh"].sum()
                _p8_demand_total["season"] = analyzer.assign_season(_p8_demand_total["datetime"])
                _p8_demand_total["day_type"] = analyzer.assign_day_type(_p8_demand_total["datetime"])
                _p8_demand_total["hour"] = _p8_demand_total["datetime"].dt.hour
                _p8_demand_total["minute"] = _p8_demand_total["datetime"].dt.minute

                _p8_supply_work = _p8_supply_df.copy()
                if not _p8_supply_work.empty:
                    _p8_supply_work["season"] = analyzer.assign_season(_p8_supply_work["datetime"])
                    _p8_supply_work["day_type"] = analyzer.assign_day_type(_p8_supply_work["datetime"])
                    _p8_supply_work["hour"] = _p8_supply_work["datetime"].dt.hour
                    _p8_supply_work["minute"] = _p8_supply_work["datetime"].dt.minute

                _P8_SEASONS = ["春", "夏", "秋", "冬"]
                _P8_DAY_TYPES = ["平日", "休日"]
                _P8_BASE_DATE = pd.Timestamp("2000-01-01")

                def _p8_representative_day(season: str, day_type: str) -> tuple[pd.DataFrame, pd.DataFrame, int]:
                    """季節×平日/休日に該当する実績を時刻ごとに平均し、代表的な1日分のdemand/supplyを作る。"""
                    d = _p8_demand_total[
                        (_p8_demand_total["season"] == season) & (_p8_demand_total["day_type"] == day_type)
                    ]
                    n_days = d["datetime"].dt.date.nunique()

                    d_rep = d.groupby(["hour", "minute"], as_index=False)["consumption_kwh"].mean()
                    d_rep["datetime"] = (
                        _P8_BASE_DATE + pd.to_timedelta(d_rep["hour"], unit="h") + pd.to_timedelta(d_rep["minute"], unit="m")
                    )
                    d_rep["facility_name"] = "代表日"
                    d_rep = d_rep[["datetime", "facility_name", "consumption_kwh"]].sort_values("datetime").reset_index(drop=True)

                    if _p8_supply_work.empty:
                        s_rep = pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
                    else:
                        s = _p8_supply_work[
                            (_p8_supply_work["season"] == season) & (_p8_supply_work["day_type"] == day_type)
                        ]
                        s_rep = s.groupby(["source_name", "hour", "minute"], as_index=False)["supply_kwh"].mean()
                        s_rep["datetime"] = (
                            _P8_BASE_DATE + pd.to_timedelta(s_rep["hour"], unit="h") + pd.to_timedelta(s_rep["minute"], unit="m")
                        )
                        s_rep = s_rep[["datetime", "source_name", "supply_kwh"]].sort_values("datetime").reset_index(drop=True)

                    return d_rep, s_rep, n_days

                for _p8_season in _P8_SEASONS:
                    st.markdown(f"#### {_p8_season}")
                    _p8_cols = st.columns(2)
                    for _p8_day_type, _p8_col in zip(_P8_DAY_TYPES, _p8_cols):
                        _d_rep, _s_rep, _n_days = _p8_representative_day(_p8_season, _p8_day_type)
                        with _p8_col:
                            if _d_rep.empty or _d_rep["consumption_kwh"].isna().all():
                                st.info(f"{_p8_season}・{_p8_day_type}：データがありません。")
                                continue
                            _p8_balance_df = financial_model.calc_balance(_d_rep, _s_rep)
                            _p8_kpis = financial_model.calc_balance_kpis(_p8_balance_df)
                            st.caption(f"{_p8_day_type}（{_n_days}日の平均）")
                            _k1, _k2, _k3 = st.columns(3)
                            _k1.metric("総需要", f"{_p8_kpis['total_demand_kwh']:,.0f} kWh")
                            _k2.metric("自給率", f"{_p8_kpis['self_sufficiency_pct']:.1f} %")
                            _k3.metric("不足", f"{_p8_kpis['deficit_kwh']:,.0f} kWh")
                            _p8_fig = visualizer.supply_demand_balance_chart(
                                _p8_balance_df, _p8_source_names,
                                title=f"{_p8_season}・{_p8_day_type}の代表的な1日",
                            )
                            _p8_fig.update_xaxes(tickformat="%H:%M", title="時刻")
                            st.plotly_chart(_p8_fig, use_container_width=True)
                    st.markdown("---")

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
                "現金残高は資本金からスタートし、月初残高＋当月キャッシュフロー＝月末残高（翌月の月初残高）として推移します。"
            )
            _cf = retail_fs.calc_cash_flow(_monthly, capital_yen, revenue_collection_lag_months=collection_lag_months)
            cf1, cf2, cf3 = st.columns(3)
            cf1.metric("資本金（開始時点の現金残高）", f"{capital_yen/10000:,.0f} 万円")
            cf2.metric("期末現金残高", f"{_cf['closing_balance'].iloc[-1]/10000:,.0f} 万円" if not _cf.empty else "—")
            _min_balance = min(_cf["closing_balance"].min(), capital_yen) if not _cf.empty else capital_yen
            cf3.metric("期間中の最低残高", f"{_min_balance/10000:,.0f} 万円")
            if _min_balance < 0:
                st.warning("⚠️ 期間中に現金残高がマイナスになる月があります。資本金の増額や資金調達を検討してください。")

            if not _cf.empty:
                st.plotly_chart(visualizer.cash_flow_chart(_cf), use_container_width=True)
                with st.expander("月別キャッシュフロー・テーブル"):
                    _cf_tbl = _cf.copy()
                    _cf_tbl["month"] = _cf_tbl["month"].dt.strftime("%Y-%m")
                    _cf_tbl = _cf_tbl[["month", "cash_in", "cash_out", "net_cash_flow", "opening_balance", "closing_balance"]]
                    _cf_tbl = _cf_tbl.rename(columns={
                        "month": "月", "cash_in": "入金(円)", "cash_out": "出金(円)",
                        "net_cash_flow": "月次キャッシュフロー(円)",
                        "opening_balance": "月初残高(円)", "closing_balance": "月末残高(円)",
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
