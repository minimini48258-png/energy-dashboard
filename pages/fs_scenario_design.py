"""
pages/fs_scenario_design.py
小売FS シナリオ設計：料金プラン・施設設定・託送料金・燃調/賦課金/容量拠出金/予備費率・
JEPX想定単価・電源別コストを設定し、st.session_state["fs_design"] に組み立てる。
試算の実行・結果表示は「試算結果」ページで行う。
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

import common
import financial_model
import jepx_loader
import retail_fs
import supply_planner

st.title("📝 小売FS：シナリオ設計")
st.caption(
    "施設ごとの契約電力・料金プラン・託送料金・容量拠出金・再エネ賦課金を設定します。"
    "単価類の初期値はあくまで目安値です。実際の数値は各エリアの料金表・託送供給等約款・"
    "OCCTO公表資料等でご確認のうえ入力してください（※要確認）。"
)

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

_uploaded = st.session_state.get("supply_df")
_sources = [supply_planner.SupplySource(**s) for s in st.session_state.get("supply_sources", [])]

# ── ① 料金プラン ────────────────────────────────────────────────────
if st.session_state["retail_fs_tariffs"] is None:
    _loaded_plans = retail_fs.load_tariff_plans()
    st.session_state["retail_fs_tariffs"] = [
        asdict(p) for p in (_loaded_plans or retail_fs.default_tariff_plans())
    ]
_plans_current = [retail_fs.TariffPlan(**d) for d in st.session_state["retail_fs_tariffs"]]

_MODE_LABELS = {"flat": "一律", "tou": "時間帯別（昼夜2区分）", "seasonal": "季節別（夏季/その他季）", "tiered": "累進段階制（3段階）"}
_MODE_KEYS = {v: k for k, v in _MODE_LABELS.items()}

with st.container(border=True):
    st.markdown("**① 料金プラン（基本料金＋従量料金）**")
    st.caption(
        "従量料金モードは4種類：一律／時間帯別（昼夜2区分）／季節別（夏季7-9月・その他季）／"
        "累進段階制（低圧・従量電灯B型を想定した3段階）。"
    )

    _updated_plans: list[retail_fs.TariffPlan] = []
    for i, plan in enumerate(_plans_current):
        with st.expander(f"{plan.name}（{plan.voltage_class}）", expanded=False):
            c1, c2, c3 = st.columns(3)
            new_name = c1.text_input("プラン名", value=plan.name, key=f"fs_plan_name_{i}")
            new_voltage = c2.selectbox(
                "電圧区分", retail_fs.VOLTAGE_CLASSES,
                index=retail_fs.VOLTAGE_CLASSES.index(plan.voltage_class),
                key=f"fs_plan_voltage_{i}",
            )
            new_basic = c3.number_input(
                "基本料金単価(円/kW・月)", min_value=0.0, value=plan.basic_yen_per_kw,
                step=10.0, key=f"fs_plan_basic_{i}",
            )

            mode_label = st.radio(
                "従量料金モード", list(_MODE_LABELS.values()),
                index=list(_MODE_LABELS.keys()).index(plan.volumetric_mode),
                key=f"fs_plan_mode_{i}", horizontal=True,
            )
            new_mode = _MODE_KEYS[mode_label]

            new_flat, new_day, new_night = plan.flat_rate, plan.day_rate, plan.night_rate
            new_summer, new_other = plan.summer_rate, plan.other_rate
            new_tiered = plan.tiered_rates
            if new_mode == "flat":
                new_flat = st.number_input(
                    "従量単価(円/kWh)", min_value=0.0, value=plan.flat_rate,
                    step=0.5, key=f"fs_plan_flat_{i}",
                )
            elif new_mode == "tou":
                dcol, ncol = st.columns(2)
                new_day = dcol.number_input(
                    "昼間単価（8-22時・円/kWh）", min_value=0.0, value=plan.day_rate,
                    step=0.5, key=f"fs_plan_day_{i}",
                )
                new_night = ncol.number_input(
                    "夜間単価（22-8時・円/kWh）", min_value=0.0, value=plan.night_rate,
                    step=0.5, key=f"fs_plan_night_{i}",
                )
            elif new_mode == "seasonal":
                scol, ocol = st.columns(2)
                new_summer = scol.number_input(
                    "夏季単価（7-9月・円/kWh）", min_value=0.0, value=plan.summer_rate,
                    step=0.1, key=f"fs_plan_summer_{i}",
                    help="出典：中部電力ミライズ 高圧業務用電力(FR相当) 目安値 ※要確認",
                )
                new_other = ocol.number_input(
                    "その他季単価（円/kWh）", min_value=0.0, value=plan.other_rate,
                    step=0.1, key=f"fs_plan_other_{i}",
                    help="出典：中部電力ミライズ 高圧業務用電力(FR相当) 目安値 ※要確認",
                )
            else:  # tiered
                t1c, t2c, t3c = st.columns(3)
                _t1 = t1c.number_input(
                    "第1段階 〜120kWh (円/kWh)", min_value=0.0,
                    value=plan.tiered_rates[0][1], step=0.1, key=f"fs_plan_t1_{i}",
                    help="出典：中部電力ミライズ 従量電灯B 目安値 ※要確認",
                )
                _t2 = t2c.number_input(
                    "第2段階 120〜300kWh (円/kWh)", min_value=0.0,
                    value=plan.tiered_rates[1][1], step=0.1, key=f"fs_plan_t2_{i}",
                )
                _t3 = t3c.number_input(
                    "第3段階 300kWh超 (円/kWh)", min_value=0.0,
                    value=plan.tiered_rates[2][1], step=0.1, key=f"fs_plan_t3_{i}",
                )
                new_tiered = [(120.0, _t1), (300.0, _t2), (None, _t3)]

            new_pf = st.checkbox(
                "力率割引/割増を適用（高圧・特別高圧、基準85%・1ポイント=1%）",
                value=plan.power_factor_discount, key=f"fs_plan_pf_{i}",
            )
            delete = st.button("🗑 このプランを削除", key=f"fs_plan_delete_{i}")

        if delete:
            continue
        _updated_plans.append(retail_fs.TariffPlan(
            name=new_name, voltage_class=new_voltage, basic_yen_per_kw=new_basic,
            volumetric_mode=new_mode, flat_rate=new_flat, day_rate=new_day, night_rate=new_night,
            summer_rate=new_summer, other_rate=new_other, tiered_rates=new_tiered,
            power_factor_discount=new_pf,
        ))

    pcol1, pcol2 = st.columns(2)
    with pcol1:
        if st.button("➕ 新規プランを追加", key="fs_plan_add_new"):
            _updated_plans.append(retail_fs.TariffPlan(name=f"新規プラン{len(_updated_plans) + 1}"))
            st.session_state["retail_fs_tariffs"] = [asdict(p) for p in _updated_plans]
            retail_fs.save_tariff_plans(_updated_plans)
            st.rerun()
    with pcol2:
        if st.button("💾 料金プランを保存", type="primary", key="fs_plan_save"):
            st.session_state["retail_fs_tariffs"] = [asdict(p) for p in _updated_plans]
            retail_fs.save_tariff_plans(_updated_plans)
            st.success("料金プランを保存しました。")
            st.rerun()

    tariff_plans = _updated_plans or _plans_current
    plan_names = [p.name for p in tariff_plans]

# ── ② 施設設定 ────────────────────────────────────────────────────
if st.session_state["retail_fs_facilities"] is None:
    st.session_state["retail_fs_facilities"] = [asdict(c) for c in retail_fs.load_facility_configs()]
_existing_cfg = {c["facility_name"]: c for c in st.session_state["retail_fs_facilities"]}

with st.container(border=True):
    st.markdown("**② 施設設定（契約電力・電圧区分・料金プラン割当）**")
    st.caption("契約電力の初期値は実績30分値のピークから自動推計した目安です。必要に応じて修正してください。")

    _default_plan = plan_names[1] if len(plan_names) > 1 else (plan_names[0] if plan_names else "")
    _rows = []
    for name in facility_names:
        cfg = _existing_cfg.get(name)
        if cfg is not None and cfg.get("tariff_plan_name") in plan_names:
            _rows.append(cfg)
        else:
            _rows.append({
                "facility_name": name,
                "contract_kw": retail_fs.suggest_contract_kw(filtered_base, name),
                "voltage_class": "高圧",
                "power_factor_pct": 100.0,
                "tariff_plan_name": _default_plan,
            })
    _fac_df = pd.DataFrame(_rows)

    _edited_fac_df = st.data_editor(
        _fac_df,
        column_config={
            "facility_name": st.column_config.TextColumn("施設名", disabled=True),
            "contract_kw": st.column_config.NumberColumn("契約電力(kW)", min_value=0.0, step=5.0),
            "voltage_class": st.column_config.SelectboxColumn("電圧区分", options=retail_fs.VOLTAGE_CLASSES),
            "power_factor_pct": st.column_config.NumberColumn("力率(%)", min_value=50.0, max_value=105.0, step=1.0),
            "tariff_plan_name": st.column_config.SelectboxColumn("料金プラン", options=plan_names),
        },
        hide_index=True, use_container_width=True, key="retail_fs_facility_editor",
    )
    if st.button("💾 施設設定を保存", key="fs_facility_save"):
        _records = _edited_fac_df.to_dict("records")
        st.session_state["retail_fs_facilities"] = _records
        retail_fs.save_facility_configs([retail_fs.FacilityConfig(**r) for r in _records])
        st.success("施設設定を保存しました。")

    facility_configs = [retail_fs.FacilityConfig(**r) for r in _edited_fac_df.to_dict("records")]

# ── ③ 託送料金 ────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**③ 託送料金（電圧区分別）**")
    _default_trans = retail_fs.default_transmission_rates()
    transmission_rates: dict[str, retail_fs.TransmissionRate] = {}
    _trans_cols = st.columns(3)
    for vc, col in zip(retail_fs.VOLTAGE_CLASSES, _trans_cols):
        with col:
            st.caption(vc)
            b = st.number_input(
                "基本単価(円/kW・月)", min_value=0.0,
                value=_default_trans[vc].basic_yen_per_kw, step=10.0, key=f"fs_trans_basic_{vc}",
            )
            v = st.number_input(
                "従量単価(円/kWh)", min_value=0.0,
                value=_default_trans[vc].volumetric_yen_per_kwh, step=0.1, key=f"fs_trans_vol_{vc}",
            )
            transmission_rates[vc] = retail_fs.TransmissionRate(vc, basic_yen_per_kw=b, volumetric_yen_per_kwh=v)

# ── ④ 燃料費調整・再エネ賦課金・容量拠出金・予備費率 ─────────────────
with st.container(border=True):
    st.markdown("**④ 燃料費調整・再エネ賦課金・容量拠出金・予備費率**")
    f1, f2, f3, f4 = st.columns(4)
    fuel_adj = f1.number_input(
        "燃料費調整単価(円/kWh)", value=0.0, step=0.1, key="fs_fuel_adj",
        help="※要確認：エリア・月別の実際の燃調単価をご確認のうえ入力してください",
    )
    levy = f2.number_input(
        "再エネ賦課金単価(円/kWh)", value=4.18, step=0.01, key="fs_levy",
        help="※要確認：経済産業省公表、2026年5月〜2027年4月適用値。年度により変更されます",
    )
    capacity_unit = f3.number_input(
        "容量拠出金単価(円/kW・年)", value=0.0, step=10.0, key="fs_capacity_unit",
        help="※要確認：簡易試算＝契約電力合計×単価。実際はOCCTO公表のエリア負担総額×"
             "ピークシェアで算定されるため、目安として利用してください",
    )
    reserve_margin = f4.number_input(
        "予備費率(%)", value=3.0, min_value=0.0, step=0.5, key="fs_reserve_margin",
        help="需要見込み誤差に備えて電力調達費に上乗せする率（インバランスの簡易モデル）",
    )

# ── ⑤ JEPX想定単価 ───────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**⑤ JEPX想定単価**")

    jepx_upload = st.file_uploader(
        "JEPX実績価格ファイル（CSV／Excel）をアップロード（任意）",
        type=["csv", "xlsx"], key="jepx_actual_upload",
        help="JEPX公式CSV（受渡日・時刻コード・エリアプライス中部等）または datetime+price の汎用形式に対応",
    )
    if jepx_upload is not None:
        try:
            _jepx_df = jepx_loader.load_jepx_price_file(jepx_upload, filename=jepx_upload.name)
            st.session_state["jepx_actual_df"] = _jepx_df
            st.success(f"✅ 実績データ使用中：{_jepx_df['datetime'].min()} 〜 {_jepx_df['datetime'].max()}（{len(_jepx_df):,} 件）")
        except Exception as _jepx_err:
            st.error(f"JEPX実績ファイルの読み込みに失敗しました: {_jepx_err}")

    st.caption(
        "実績データがない時間帯・データ未アップロード時は下記の目安値（季節×時間帯）を使用します。"
        "出典：JEPXシステムプライス週平均 約19.09円/kWh（新電力ネット, 2026/7/19週）を基準にした季節按分の目安値。"
        "※要確認・中部エリア固有の値ではありません。"
    )
    _jepx_labels = {
        "深夜（0〜6時）": list(range(0, 6)), "朝（6〜9時）": list(range(6, 9)),
        "日中（9〜16時）": list(range(9, 16)), "夕方（16〜20時）": list(range(16, 20)),
        "夜（20〜24時）": list(range(20, 24)),
    }

    def _default_block_price(hours: list[int], season_months: set[int]) -> float:
        vals = [financial_model.DEFAULT_JEPX_PRICE_BY_MONTH_HOUR[(m, h)] for m in season_months for h in hours]
        return round(sum(vals) / len(vals), 1)

    _other_months = set(range(1, 13)) - retail_fs.SUMMER_MONTHS

    st.caption("夏季（7〜9月）")
    _cols_s = st.columns(5)
    _summer_prices = {}
    for (label, hours), col in zip(_jepx_labels.items(), _cols_s):
        _summer_prices[label] = col.number_input(
            label, min_value=0.0, value=_default_block_price(hours, retail_fs.SUMMER_MONTHS),
            step=0.5, key=f"jepx_summer_{label}",
        )
    st.caption("その他季")
    _cols_o = st.columns(5)
    _other_prices = {}
    for (label, hours), col in zip(_jepx_labels.items(), _cols_o):
        _other_prices[label] = col.number_input(
            label, min_value=0.0, value=_default_block_price(hours, _other_months),
            step=0.5, key=f"jepx_other_{label}",
        )

    jepx_by_month_hour: dict[tuple[int, int], float] = {}
    for m in range(1, 13):
        season_prices = _summer_prices if m in retail_fs.SUMMER_MONTHS else _other_prices
        for label, hours in _jepx_labels.items():
            for h in hours:
                jepx_by_month_hour[(m, h)] = season_prices[label]

# ── ⑥ 電源別 調達コスト・排出係数・地域内フラグ ──────────────────────
_all_src_names: list[str] = []
_src_default_cost: dict[str, float] = {}
if _uploaded is not None:
    for sn in sorted(_uploaded["source_name"].unique()):
        _all_src_names.append(sn)
        _src_default_cost[sn] = 8.0
for src in _sources:
    if src.name not in _all_src_names:
        _all_src_names.append(src.name)
    _src_default_cost[src.name] = src.cost_per_kwh

source_costs: dict[str, float] = {}
emission_factors: dict[str, float] = {}
local_flags: dict[str, bool] = {}
with st.container(border=True):
    st.markdown("**⑥ 電源別 調達コスト・排出係数・地域内フラグ**")
    st.caption("相対電源（固定単価での相対契約）も「電源管理」で登録した電源として、ここで単価を設定できます。")
    if _all_src_names:
        for sn in _all_src_names:
            sc1, sc2, sc3 = st.columns([2, 1, 1])
            sc1.markdown(f"　{sn}")
            source_costs[sn] = sc1.number_input(
                "発電コスト(円/kWh)", min_value=0.0, value=_src_default_cost[sn],
                step=0.5, key=f"fs_cost_{sn}", label_visibility="collapsed",
            )
            emission_factors[sn] = sc2.number_input(
                "排出係数(kg-CO2/kWh)", min_value=0.0, value=0.0,
                step=0.01, key=f"fs_emission_{sn}",
            )
            local_flags[sn] = sc3.checkbox("地域内電源", value=False, key=f"fs_local_{sn}")
    else:
        st.caption("電源が登録されていません（「データ読み込み」でアップロードするか「電源管理」で登録してください）。"
                   "登録がない場合は全量をJEPX市場から調達する前提で試算します。")

# ── シナリオ設計を組み立てて保存 ──────────────────────────────────────
st.session_state["fs_design"] = {
    "tariff_plans": [asdict(p) for p in tariff_plans],
    "facility_configs": [asdict(c) for c in facility_configs],
    "transmission_rates": {vc: asdict(r) for vc, r in transmission_rates.items()},
    "fuel_adjustment_yen_per_kwh": fuel_adj,
    "renewable_levy_yen_per_kwh": levy,
    "capacity_unit_yen_per_kw_year": capacity_unit,
    "reserve_margin_pct": reserve_margin,
    "jepx_by_month_hour": {f"{m}-{h}": p for (m, h), p in jepx_by_month_hour.items()},
    "source_costs": source_costs,
    "emission_factors": emission_factors,
    "local_flags": local_flags,
}

st.markdown("---")
st.success("✅ シナリオ設計を反映しました。「試算結果」ページで試算を実行できます。")
