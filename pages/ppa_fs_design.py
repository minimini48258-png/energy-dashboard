"""
pages/ppa_fs_design.py
PPA採算性：シナリオ設計。顧客条件・需要データ/太陽光発電シミュレーション・小売電力条件・
維持管理・ファイナンス・リスクを設定し、st.session_state["ppa_fs_inputs"]（dict）に組み立てる。
試算の実行・結果表示は「試算結果」ページで行う。
"""

from __future__ import annotations

import json

import streamlit as st

import common
import ppa_demand_integration
import ppa_retail_calc as calc
import ppa_scenario_manager
import solar_simulator

st.title("📝 PPA採算性：シナリオ設計")
st.caption(
    "「小売電気料金＋オンサイトPPA」を一体単価で提供する事業モデルの前提条件を設定します。"
    "太字でない入力は目安の仮定値です。実際の数値は各社の調達条件・制度等でご確認ください（※要確認）。"
)

if "ppa_fs_inputs" not in st.session_state or st.session_state["ppa_fs_inputs"] is None:
    _saved = ppa_scenario_manager.load_design()
    st.session_state["ppa_fs_inputs"] = calc.inputs_to_dict(_saved or calc.create_residential_sample())

d = st.session_state["ppa_fs_inputs"]

rc1, rc2, rc3 = st.columns([2, 2, 4])
if rc1.button("🏠 住宅サンプルに戻す"):
    st.session_state["ppa_fs_inputs"] = calc.inputs_to_dict(calc.create_residential_sample())
    st.session_state["ppa_fs_sim_df"] = None
    st.session_state["ppa_fs_demand_df"] = None
    st.rerun()
if rc2.button("🏢 事業所サンプルに戻す"):
    st.session_state["ppa_fs_inputs"] = calc.inputs_to_dict(calc.create_business_sample())
    st.session_state["ppa_fs_sim_df"] = None
    st.session_state["ppa_fs_demand_df"] = None
    st.rerun()

# ── ① 顧客条件 ──────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**① 顧客条件**")
    c = d["customer"]
    col1, col2, col3 = st.columns(3)
    seg_label = col1.selectbox(
        "対象区分", ["住宅", "事業所"], index=0 if c["segment"] == "residential" else 1,
        help="将来の複数需要家ポートフォリオ分析への拡張を見据えた区分。現状は表示用。",
    )
    c["segment"] = "residential" if seg_label == "住宅" else "business"
    c["simulation_years"] = col2.number_input("シミュレーション期間(年)", min_value=1, value=int(c["simulation_years"]))
    c["contract_years"] = col3.number_input(
        "契約期間(年)", min_value=1, value=int(c["contract_years"]),
        help="この期間を超えると顧客請求が終了し、自家消費相当分は余剰電力として売却されると仮定します。",
    )

    col4, col5, col6 = st.columns(3)
    c["unified_rate"] = col4.number_input(
        "PPA/小売一体単価(円/kWh)", min_value=0.0, value=float(c["unified_rate"]), step=0.1,
        help="太陽光由来・外部調達由来を区別せず、顧客使用量すべてに一律で課す単価。契約期間中は固定と仮定。",
    )
    c["current_unit_price"] = col5.number_input("現在の顧客の平均電力単価(円/kWh)", min_value=0.0, value=float(c["current_unit_price"]), step=0.1)
    tax_label = col6.radio("税区分", ["税込", "税抜"], index=0 if c["tax_mode"] == "tax_included" else 1, horizontal=True)
    c["tax_mode"] = "tax_included" if tax_label == "税込" else "tax_excluded"

    col7, col8 = st.columns(2)
    c["current_price_escalation_rate_pct"] = col7.number_input(
        "既存電力料金の上昇率(%/年)", value=float(c["current_price_escalation_rate_pct"]), step=0.1,
        help="新プラン(一体単価)は契約期間中固定、現在プランのみ上昇すると仮定。",
    )
    c["consumption_growth_rate_pct"] = col8.number_input(
        "年間使用量の増減率(%/年)", value=float(c["consumption_growth_rate_pct"]), step=0.1,
        help="世帯人数の変化、事業拡大・縮小等による使用量の年平均変化率（将来年度の投影にのみ使用）。",
    )

# ── ② 需要データ・太陽光発電シミュレーション ─────────────────────────
with st.container(border=True):
    st.markdown("**② 需要データ・太陽光発電シミュレーション**")
    st.caption(
        "この顧客の実際の30分値使用量データを使って、太陽光でどれだけ需要を賄え、"
        "どれだけ電気が余るか（→小売電気事業者が買い取り他需要家へ供給）、"
        "どれだけ不足して市場等から別途調達が必要かを実績ベースで計算します。"
        "データが無い場合は、自家消費率を仮定値で入力する簡易モードにフォールバックします。"
    )

    s = d["solar"]
    demand_df = st.session_state.get("df")

    col1, col2, col3 = st.columns(3)
    s["capacity_kw"] = col1.number_input("太陽光容量(kW)", min_value=0.0, value=float(s["capacity_kw"]), step=1.0)
    s["unit_cost_per_kw"] = col2.number_input("設備導入単価(円/kW)", min_value=0.0, value=float(s["unit_cost_per_kw"]), step=1000.0)
    s["subsidy_amount"] = col3.number_input("補助金額(円)", min_value=0.0, value=float(s["subsidy_amount"]), step=10000.0)

    col4, col5 = st.columns(2)
    s["degradation_rate_pct"] = col4.number_input(
        "経年劣化率(%/年)", min_value=0.0, value=float(s["degradation_rate_pct"]), step=0.1,
        help="サンプル既定値0.33%/年は「20年で累積約5〜6%、30年で累積約9%の発電量低下」という前提に基づく仮定値。",
    )
    s["useful_life_years"] = col5.number_input("設備利用期間(年)", min_value=1, value=int(s["useful_life_years"]))

    with st.expander("蓄電池（任意）", expanded=bool(s.get("battery_enabled"))):
        bc1, bc2, bc3, bc4 = st.columns(4)
        s["battery_enabled"] = bc1.checkbox("蓄電池を導入する", value=bool(s["battery_enabled"]))
        s["battery_capacity_kwh"] = bc2.number_input(
            "蓄電池容量(kWh)", min_value=0.0, value=float(s.get("battery_capacity_kwh", 0.0)),
            step=10.0, disabled=not s["battery_enabled"], key="ppa_battery_kwh",
        )
        s["battery_efficiency_pct"] = bc3.number_input(
            "充放電往復効率(%)", min_value=50.0, max_value=100.0,
            value=float(s.get("battery_efficiency_pct", 95.0)), disabled=not s["battery_enabled"], key="ppa_battery_eff",
        )
        s["battery_cost"] = bc4.number_input("導入費用(円)", min_value=0.0, value=float(s["battery_cost"]), step=10000.0, disabled=not s["battery_enabled"], key="ppa_battery_cost")
        s["battery_annual_om"] = st.number_input(
            "年間O&M(円/年)", min_value=0.0, value=float(s["battery_annual_om"]), disabled=not s["battery_enabled"], key="ppa_battery_om",
        )

        battery_mode = "basic"
        min_soc_pct = 30.0
        peak_threshold_kw = None
        if s["battery_enabled"]:
            battery_mode = st.radio(
                "充放電モード", list(solar_simulator.BATTERY_MODE_LABELS.keys()),
                format_func=lambda k: solar_simulator.BATTERY_MODE_LABELS.get(k, k),
                horizontal=True, key="ppa_battery_mode",
            )
            if battery_mode == "reserve":
                min_soc_pct = st.slider("最低残量(%)", min_value=10, max_value=70, value=30, step=5, key="ppa_battery_min_soc")
            elif battery_mode == "peak_cut":
                peak_threshold_kw = st.number_input("デマンド閾値(kW)", min_value=1.0, value=10.0, step=1.0, key="ppa_battery_peak_kw")

    st.markdown("###### 実績データとの照合")
    if demand_df is None:
        st.info("👈 サイドバーの「データ読み込み」ページで需要データを読み込むと、実績ベースで自家消費・余剰電力を自動計算できます。現在は仮定値モードで入力してください。")
        use_real_data = False
    else:
        facility_names, group_df = common.get_group_context(demand_df)
        filtered_base, group_mode = common.render_facility_filter(demand_df, facility_names, group_df)
        use_real_data = st.checkbox(
            "この顧客の需要として選択した施設の実績データを使って自家消費率を計算する", value=True,
            key="ppa_use_real_data",
        )

        if use_real_data and not filtered_base.empty:
            with st.spinner("実データで太陽光＋蓄電池シミュレーション計算中..."):
                metrics = ppa_demand_integration.run_real_data_simulation(
                    filtered_base,
                    solar_capacity_kw=s["capacity_kw"],
                    battery_capacity_kwh=s.get("battery_capacity_kwh", 0.0) if s["battery_enabled"] else 0.0,
                    battery_efficiency_pct=s.get("battery_efficiency_pct", 95.0),
                    mode=battery_mode,
                    min_soc_pct=min_soc_pct,
                    peak_threshold_kw=peak_threshold_kw,
                )
            d = ppa_demand_integration.apply_real_data_metrics(d, metrics)
            s = d["solar"]

            st.session_state["ppa_fs_sim_df"] = metrics.sim_df
            st.session_state["ppa_fs_demand_df"] = filtered_base

            mk1, mk2, mk3, mk4 = st.columns(4)
            mk1.metric("年間使用量(実績換算)", f"{metrics.annual_consumption_kwh:,.0f} kWh")
            mk2.metric("年間発電量(実績換算)", f"{metrics.annual_generation_kwh:,.0f} kWh")
            mk3.metric("自家消費率", f"{metrics.self_consumption_rate_pct:.1f} %")
            mk4.metric("自給率", f"{metrics.self_sufficiency_rate_pct:.1f} %")
            mk5, mk6 = st.columns(2)
            mk5.metric("外部調達電力量(年換算・市場等から調達)", f"{metrics.grid_import_kwh_annual:,.0f} kWh")
            mk6.metric("余剰電力量(年換算・小売電気として他需要家へ)", f"{metrics.grid_export_kwh_annual:,.0f} kWh")
            st.caption(f"実データ対象期間: {metrics.n_days_in_data}日分のデータを年換算（×365/{metrics.n_days_in_data}）して使用しています。")
        else:
            use_real_data = False
            if filtered_base.empty:
                st.warning("施設が選択されていません。")

    if not use_real_data:
        st.session_state["ppa_fs_sim_df"] = None
        st.session_state["ppa_fs_demand_df"] = None
        st.markdown("###### 仮定値モード（実データ未使用）")
        mode_label = st.radio(
            "発電量の入力方式", ["設備容量×kWh/kWで計算", "年間発電量を直接入力"],
            index=0 if s["generation_input_mode"] == "capacity_x_yield" else 1, horizontal=True,
        )
        s["generation_input_mode"] = "capacity_x_yield" if mode_label == "設備容量×kWh/kWで計算" else "direct_input"

        mcol1, mcol2, mcol3 = st.columns(3)
        s["annual_yield_per_kw"] = mcol1.number_input(
            "年間発電量(kWh/kW/年)", min_value=0.0, value=float(s["annual_yield_per_kw"]), step=10.0,
            disabled=s["generation_input_mode"] != "capacity_x_yield",
            help="設置地域・方位・角度により800〜1,300kWh/kW/年程度まで幅があります。",
        )
        s["direct_annual_generation_kwh"] = mcol2.number_input(
            "初年度年間発電量(kWh)", min_value=0.0, value=float(s["direct_annual_generation_kwh"]),
            disabled=s["generation_input_mode"] != "direct_input",
        )
        c["annual_consumption_kwh"] = mcol3.number_input(
            "年間電力使用量・初年度(kWh)", min_value=0.0, value=float(c["annual_consumption_kwh"]), step=100.0,
        )

        mcol4, mcol5 = st.columns(2)
        s["self_consumption_rate_pct"] = mcol4.number_input(
            "自家消費率(%)", min_value=0.0, max_value=100.0, value=float(s["self_consumption_rate_pct"]),
            help="発電量のうち顧客が自家消費する割合（使用量でキャップ）。年間代表率としての簡略化。",
        )
        with mcol5:
            st.markdown("蓄電池・エコキュートによる自家消費率への上乗せ")
            bb1, bb2 = st.columns(2)
            s["battery_self_consumption_boost_pct"] = bb1.number_input(
                "蓄電池(pp)", value=float(s["battery_self_consumption_boost_pct"]), disabled=not s["battery_enabled"], key="ppa_battery_boost_assume",
            )
            s["heat_pump_enabled"] = bb2.checkbox("エコキュート等", value=bool(s["heat_pump_enabled"]), key="ppa_hp_enabled_assume")
        s["heat_pump_self_consumption_boost_pct"] = st.number_input(
            "エコキュート等の自家消費率への上乗せ(pp)", value=float(s["heat_pump_self_consumption_boost_pct"]),
            disabled=not s["heat_pump_enabled"], key="ppa_hp_boost_assume",
        )
        s["heat_pump_cost"] = st.number_input(
            "エコキュート等導入費用(円)", min_value=0.0, value=float(s["heat_pump_cost"]), step=10000.0,
            disabled=not s["heat_pump_enabled"], key="ppa_hp_cost_assume",
        )
    else:
        s["heat_pump_enabled"] = False

    _initial_investment = calc.compute_initial_investment(calc.SolarAssetInputs(**s))
    st.metric("初期設備費(自動計算)", f"{_initial_investment:,.0f}円")

# ── ③ 小売電力条件・余剰電力 ─────────────────────────────────────────
with st.container(border=True):
    st.markdown("**③ 小売電力条件（外部調達原価）**")
    st.caption("太陽光で賄えない「外部調達電力量」にのみ適用されます。自家消費分には適用しません（二重計上防止）。")
    r = d["retail"]
    col1, col2, col3, col4 = st.columns(4)
    r["grid_procurement_price"] = col1.number_input("系統電力調達単価(円/kWh)", min_value=0.0, value=float(r["grid_procurement_price"]), step=0.1)
    r["transmission_fee"] = col2.number_input("託送料金等(円/kWh)", min_value=0.0, value=float(r["transmission_fee"]), step=0.1)
    r["capacity_contribution_fee"] = col3.number_input("容量拠出金等(円/kWh)", min_value=0.0, value=float(r["capacity_contribution_fee"]), step=0.1)
    r["other_retail_cost"] = col4.number_input("その他小売原価(円/kWh)", min_value=0.0, value=float(r["other_retail_cost"]), step=0.1)

    col5, col6, col7 = st.columns(3)
    r["apply_renewable_levy"] = col5.checkbox(
        "再エネ賦課金を外部調達電力に課す", value=bool(r["apply_renewable_levy"]),
        help="自家消費分の太陽光電力には再エネ賦課金がかからないという前提（※要確認）。",
    )
    r["renewable_levy_rate"] = col6.number_input("再エネ賦課金単価(円/kWh)", min_value=0.0, value=float(r["renewable_levy_rate"]), step=0.1, disabled=not r["apply_renewable_levy"])
    r["retail_cost_escalation_rate_pct"] = col7.number_input("小売原価上昇率(%/年)", value=float(r["retail_cost_escalation_rate_pct"]), step=0.1)

    st.markdown("**余剰電力（小売電気事業者が買い取り、他の需要先への調達電源として活用）**")
    su = d["surplus"]
    col8, col9, col10 = st.columns(3)
    su["surplus_price"] = col8.number_input(
        "余剰電力売却単価(円/kWh)", min_value=0.0, value=float(su["surplus_price"]), step=0.1,
        help="サンプル既定値15円/kWhは、単純な市場売却ではなく他需要家への供給電源として活用する想定の標準買取単価（※仮定値）。",
    )
    su["surplus_price_escalation_rate_pct"] = col9.number_input("売却単価の上昇率(%/年)", value=float(su["surplus_price_escalation_rate_pct"]), step=0.1)
    dest_labels = {"market": "市場へ売却", "self_retail_portfolio": "他の自社需要家へ販売", "battery_charge": "蓄電池へ充電"}
    dest_label = col10.selectbox("売却先", list(dest_labels.values()), index=list(dest_labels.keys()).index(su["destination"]))
    su["destination"] = {v: k for k, v in dest_labels.items()}[dest_label]

# ── ④ 維持管理 ──────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**④ 維持管理**")
    m = d["maintenance"]
    col1, col2, col3 = st.columns(3)
    om_label = col1.selectbox("O&M費の算定方法", ["設備費に対する%", "固定額"], index=0 if m["om_mode"] == "pct_of_capex" else 1)
    m["om_mode"] = "pct_of_capex" if om_label == "設備費に対する%" else "fixed"
    m["om_pct_of_capex"] = col2.number_input("設備費に対する割合(%/年)", min_value=0.0, value=float(m["om_pct_of_capex"]), step=0.1, disabled=m["om_mode"] != "pct_of_capex")
    m["om_fixed_amount"] = col3.number_input("固定額(円/年)", min_value=0.0, value=float(m["om_fixed_amount"]), disabled=m["om_mode"] != "fixed")

    col4, col5, col6 = st.columns(3)
    ins_label = col4.selectbox("保険料の算定方法", ["設備費に対する%", "固定額"], index=0 if m["insurance_mode"] == "pct_of_capex" else 1)
    m["insurance_mode"] = "pct_of_capex" if ins_label == "設備費に対する%" else "fixed"
    m["insurance_pct_of_capex"] = col5.number_input("設備費に対する割合(%/年)", min_value=0.0, value=float(m["insurance_pct_of_capex"]), step=0.1, disabled=m["insurance_mode"] != "pct_of_capex", key="ins_pct")
    m["insurance_fixed_amount"] = col6.number_input("固定額(円/年)", min_value=0.0, value=float(m["insurance_fixed_amount"]), disabled=m["insurance_mode"] != "fixed", key="ins_fixed")

    col7, col8, col9 = st.columns(3)
    m["management_fee_annual"] = col7.number_input("設備管理費(円/年)", min_value=0.0, value=float(m["management_fee_annual"]))
    _inv_year = col8.number_input(
        "パワコン交換年(0=交換なし)", min_value=0, value=int(m["inverter_replacement_year"] or 0),
        help="サンプル既定値は15年（パワコンは15年程度で交換が必要という前提の仮定値）。",
    )
    m["inverter_replacement_year"] = _inv_year if _inv_year > 0 else None
    m["inverter_replacement_cost"] = col9.number_input("パワコン交換費用(円)", min_value=0.0, value=float(m["inverter_replacement_cost"]), step=10000.0)

    st.markdown("その他修繕費（年次ごと）")
    for i, item in enumerate(m["repair_schedule"]):
        rc1, rc2, rc3, rc4 = st.columns([1, 2, 3, 1])
        item["year"] = rc1.number_input("年目", min_value=1, value=int(item["year"]), key=f"ppa_repair_year_{i}")
        item["amount"] = rc2.number_input("金額(円)", min_value=0.0, value=float(item["amount"]), key=f"ppa_repair_amount_{i}")
        item["label"] = rc3.text_input("メモ", value=item.get("label", ""), key=f"ppa_repair_label_{i}")
        if rc4.button("削除", key=f"ppa_repair_del_{i}"):
            m["repair_schedule"].pop(i)
            st.rerun()
    if st.button("＋ 修繕項目を追加"):
        m["repair_schedule"].append({"year": 10, "amount": 100000, "label": ""})
        st.rerun()

    st.markdown(
        "最終年度の扱い（本モデルは設備を顧客へ無償譲渡せず、事業者が長期所有することを前提にしています）"
    )
    term_labels = {"removal": "撤去", "replacement": "設備更新", "residual_value": "残存価値を計上"}
    term_label = st.selectbox("最終年度の処理", list(term_labels.values()), index=list(term_labels.keys()).index(m["terminal_treatment"]))
    m["terminal_treatment"] = {v: k for k, v in term_labels.items()}[term_label]

    col10, col11, col12, col13 = st.columns(4)
    m["removal_cost"] = col10.number_input("撤去費用(円)", min_value=0.0, value=float(m["removal_cost"]), step=10000.0, disabled=m["terminal_treatment"] != "removal")
    m["recycling_cost"] = col11.number_input("リサイクル費用(円)", min_value=0.0, value=float(m["recycling_cost"]), step=10000.0, disabled=m["terminal_treatment"] != "removal")
    m["replacement_cost"] = col12.number_input("設備更新費用(円)", min_value=0.0, value=float(m["replacement_cost"]), step=10000.0, disabled=m["terminal_treatment"] != "replacement")
    m["residual_value"] = col13.number_input("残存価値(円)", min_value=0.0, value=float(m["residual_value"]), step=10000.0, disabled=m["terminal_treatment"] != "residual_value")

# ── ⑤ ファイナンス ──────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**⑤ ファイナンス**")
    f = d["finance"]
    col1, col2, col3 = st.columns(3)
    f["equity_ratio_pct"] = col1.number_input("自己資本比率(%)", min_value=0.0, max_value=100.0, value=float(f["equity_ratio_pct"]))
    f["interest_rate_pct"] = col2.number_input("借入金利(%/年)", min_value=0.0, value=float(f["interest_rate_pct"]), step=0.1)
    f["loan_term_years"] = col3.number_input("借入期間(年)", min_value=0, value=int(f["loan_term_years"]))

    col4, col5, col6 = st.columns(3)
    repay_label = col4.selectbox("返済方法", ["元利均等", "元金均等"], index=0 if f["repayment_method"] == "equal_payment" else 1)
    f["repayment_method"] = "equal_payment" if repay_label == "元利均等" else "equal_principal"
    f["grace_period_years"] = col5.number_input("据置期間(年)", min_value=0, value=int(f["grace_period_years"]))
    f["loan_fee_pct"] = col6.number_input("融資手数料(%、借入額に対して)", min_value=0.0, value=float(f["loan_fee_pct"]), step=0.1)

    col7, col8, col9, col10 = st.columns(4)
    f["discount_rate_pct"] = col7.number_input("NPV割引率(%)", min_value=0.0, value=float(f["discount_rate_pct"]), step=0.1)
    f["target_project_irr_pct"] = col8.number_input("事業IRR目標値(%)", value=float(f["target_project_irr_pct"]), step=0.1)
    f["target_equity_irr_pct"] = col9.number_input("エクイティIRR目標値(%)", value=float(f["target_equity_irr_pct"]), step=0.1)
    f["target_min_dscr"] = col10.number_input("最低DSCR目標値", value=float(f["target_min_dscr"]), step=0.05)

# ── ⑥ リスク ────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**⑥ リスク（特に事業所向け：途中解約・倒産・移転）**")
    rk = d["risk"]
    col1, col2, col3 = st.columns(3)
    rk["annual_cancel_prob_pct"] = col1.number_input("年間解約確率(%/年)", min_value=0.0, value=float(rk["annual_cancel_prob_pct"]), step=0.1)
    rk["annual_bankruptcy_prob_pct"] = col2.number_input("年間倒産確率(%/年)", min_value=0.0, value=float(rk["annual_bankruptcy_prob_pct"]), step=0.1)
    rk["annual_relocation_prob_pct"] = col3.number_input("年間移転確率(%/年)", min_value=0.0, value=float(rk["annual_relocation_prob_pct"]), step=0.1)

    handling_labels = {
        "succession": "A. 新しい需要家へ契約承継",
        "resell_surplus": "B. 余剰電力として他需要家へ販売",
        "removal": "C. 設備撤去",
        "termination_fee": "D. 顧客から中途解約金を受領",
    }
    handling_label = st.selectbox("途中解約時の処理方法", list(handling_labels.values()), index=list(handling_labels.keys()).index(rk["termination_handling"]))
    rk["termination_handling"] = {v: k for k, v in handling_labels.items()}[handling_label]

    col4, col5 = st.columns(2)
    rk["succession_success_rate_pct"] = col4.number_input(
        "契約承継成功率(%)", min_value=0.0, max_value=100.0, value=float(rk["succession_success_rate_pct"]),
        disabled=rk["termination_handling"] != "succession",
    )
    rk["termination_fee_amount"] = col5.number_input(
        "中途解約金(円)", min_value=0.0, value=float(rk["termination_fee_amount"]), step=10000.0,
        disabled=rk["termination_handling"] != "termination_fee",
    )

st.session_state["ppa_fs_inputs"] = d
ppa_scenario_manager.save_design(calc.inputs_from_dict(d))

# ── ⑦ シナリオ保存 ──────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**⑦ シナリオとして保存**")
    st.caption("保存すると「シナリオ比較」ページで他のシナリオと一覧比較できます。")
    sc1, sc2 = st.columns([3, 1])
    scenario_name = sc1.text_input("シナリオ名", value=("住宅サンプル" if d["customer"]["segment"] == "residential" else "事業所サンプル"))
    if sc2.button("💾 シナリオを保存", type="primary"):
        if not scenario_name:
            st.error("シナリオ名を入力してください。")
        else:
            ppa_scenario_manager.save_scenario(ppa_scenario_manager.PpaScenario(name=scenario_name, inputs=d))
            st.success(f"シナリオ「{scenario_name}」を保存しました。「シナリオ比較」ページで確認できます。")

# ── ⑧ バックアップ（JSON入出力） ────────────────────────────────────
with st.container(border=True):
    st.markdown("**⑧ バックアップ（JSON入出力）**")
    st.caption(
        "⚠️ このアプリはコードを更新（git push）するたびにサーバーが再作成され、"
        "「⑦シナリオとして保存」の内容も含めて消えてしまいます。大事に作り込んだ条件は、"
        "下記からJSONファイルとしてダウンロードし、ご自身のPC・Google Drive等に保管してください。"
        "次回、同じJSONファイルを読み込めば条件を復元できます。"
    )
    jc1, jc2 = st.columns(2)
    with jc1:
        st.download_button(
            "📥 現在の入力をJSON出力",
            data=json.dumps(d, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"ppa_scenario_{scenario_name or 'untitled'}.json",
            mime="application/json",
        )
    with jc2:
        uploaded_json = st.file_uploader("📤 JSONファイルを読み込んで復元", type=["json"], key="ppa_json_upload")
        if uploaded_json is not None and st.session_state.get("ppa_last_uploaded_json_id") != uploaded_json.file_id:
            try:
                restored = json.loads(uploaded_json.read().decode("utf-8"))
                calc.inputs_from_dict(restored)  # 形式検証
                st.session_state["ppa_fs_inputs"] = restored
                st.session_state["ppa_fs_sim_df"] = None
                st.session_state["ppa_fs_demand_df"] = None
                st.session_state["ppa_last_uploaded_json_id"] = uploaded_json.file_id
                ppa_scenario_manager.save_design(calc.inputs_from_dict(restored))
                st.success("JSONから条件を復元しました。")
                st.rerun()
            except Exception as e:
                st.error(f"読み込みに失敗しました: {e}")

st.info("👉 入力は自動保存されます。「試算結果」ページへ進んで計算結果を確認してください。")
