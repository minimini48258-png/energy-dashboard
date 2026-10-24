"""
pages/ppa_fs_design.py
PPA採算性：シナリオ設計。顧客条件・太陽光条件・小売電力条件・維持管理・ファイナンス・
リスクを設定し、st.session_state["ppa_fs_inputs"]（dict）に組み立てる。
試算の実行・結果表示は「試算結果」ページで行う。
"""

from __future__ import annotations

import streamlit as st

import ppa_retail_calc as calc
import ppa_scenario_manager

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
    st.rerun()
if rc2.button("🏢 事業所サンプルに戻す"):
    st.session_state["ppa_fs_inputs"] = calc.inputs_to_dict(calc.create_business_sample())
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
    col9, col10 = st.columns(2)
    c["annual_consumption_kwh"] = col9.number_input("年間電力使用量・初年度(kWh)", min_value=0.0, value=float(c["annual_consumption_kwh"]), step=100.0)
    c["consumption_growth_rate_pct"] = col10.number_input("年間使用量の増減率(%/年)", value=float(c["consumption_growth_rate_pct"]), step=0.1)

# ── ② 太陽光条件 ────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**② 太陽光条件**")
    s = d["solar"]
    mode_label = st.radio(
        "発電量の入力方式", ["設備容量×kWh/kWで計算", "年間発電量を直接入力"],
        index=0 if s["generation_input_mode"] == "capacity_x_yield" else 1, horizontal=True,
    )
    s["generation_input_mode"] = "capacity_x_yield" if mode_label == "設備容量×kWh/kWで計算" else "direct_input"

    col1, col2, col3 = st.columns(3)
    s["capacity_kw"] = col1.number_input("太陽光容量(kW)", min_value=0.0, value=float(s["capacity_kw"]), step=1.0)
    s["unit_cost_per_kw"] = col2.number_input("設備導入単価(円/kW)", min_value=0.0, value=float(s["unit_cost_per_kw"]), step=1000.0)
    s["subsidy_amount"] = col3.number_input("補助金額(円)", min_value=0.0, value=float(s["subsidy_amount"]), step=10000.0)

    col4, col5, col6 = st.columns(3)
    s["annual_yield_per_kw"] = col4.number_input(
        "年間発電量(kWh/kW/年)", min_value=0.0, value=float(s["annual_yield_per_kw"]), step=10.0,
        disabled=s["generation_input_mode"] != "capacity_x_yield",
        help="設置地域・方位・角度により800〜1,300kWh/kW/年程度まで幅があります。",
    )
    s["direct_annual_generation_kwh"] = col5.number_input(
        "初年度年間発電量(kWh)", min_value=0.0, value=float(s["direct_annual_generation_kwh"]),
        disabled=s["generation_input_mode"] != "direct_input",
    )
    s["degradation_rate_pct"] = col6.number_input(
        "経年劣化率(%/年)", min_value=0.0, value=float(s["degradation_rate_pct"]), step=0.1,
        help="一般的な結晶シリコン系パネルで0.3〜0.7%/年程度が目安。",
    )

    col7, col8, col9 = st.columns(3)
    s["self_consumption_rate_pct"] = col7.number_input(
        "自家消費率(%)", min_value=0.0, max_value=100.0, value=float(s["self_consumption_rate_pct"]),
        help="発電量のうち顧客が自家消費する割合（使用量でキャップ）。年間代表率としての簡略化。",
    )
    s["useful_life_years"] = col8.number_input("設備利用期間(年)", min_value=1, value=int(s["useful_life_years"]))
    _initial_investment = calc.compute_initial_investment(calc.SolarAssetInputs(**s))
    col9.metric("初期設備費(自動計算)", f"{_initial_investment:,.0f}円")

    with st.expander("蓄電池・エコキュート等（簡易対応：自家消費率への上乗せとして近似）", expanded=False):
        bc1, bc2, bc3, bc4 = st.columns(4)
        s["battery_enabled"] = bc1.checkbox("蓄電池を導入する", value=bool(s["battery_enabled"]))
        s["battery_self_consumption_boost_pct"] = bc2.number_input(
            "自家消費率への上乗せ(pp)", value=float(s["battery_self_consumption_boost_pct"]), disabled=not s["battery_enabled"],
            key="ppa_battery_boost",
        )
        s["battery_cost"] = bc3.number_input("導入費用(円)", min_value=0.0, value=float(s["battery_cost"]), step=10000.0, disabled=not s["battery_enabled"], key="ppa_battery_cost")
        s["battery_annual_om"] = bc4.number_input("年間O&M(円/年)", min_value=0.0, value=float(s["battery_annual_om"]), disabled=not s["battery_enabled"], key="ppa_battery_om")

        hc1, hc2, hc3 = st.columns(3)
        s["heat_pump_enabled"] = hc1.checkbox("エコキュート等を導入する", value=bool(s["heat_pump_enabled"]))
        s["heat_pump_self_consumption_boost_pct"] = hc2.number_input(
            "自家消費率への上乗せ(pp)", value=float(s["heat_pump_self_consumption_boost_pct"]), disabled=not s["heat_pump_enabled"],
            key="ppa_hp_boost",
        )
        s["heat_pump_cost"] = hc3.number_input("導入費用(円)", min_value=0.0, value=float(s["heat_pump_cost"]), step=10000.0, disabled=not s["heat_pump_enabled"], key="ppa_hp_cost")

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

    st.markdown("**余剰電力**")
    su = d["surplus"]
    col8, col9, col10 = st.columns(3)
    su["surplus_price"] = col8.number_input("余剰電力売却単価(円/kWh)", min_value=0.0, value=float(su["surplus_price"]), step=0.1)
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
    _inv_year = col8.number_input("パワコン交換年(0=交換なし)", min_value=0, value=int(m["inverter_replacement_year"] or 0))
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

st.info("👉 入力は自動保存されます。「試算結果」ページへ進んで計算結果を確認してください。")
