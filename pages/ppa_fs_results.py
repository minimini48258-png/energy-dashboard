"""
pages/ppa_fs_results.py
PPA採算性：試算結果。顧客メリット／事業者メリット／金融成立性のKPIカード、
損益分岐PPA単価（4条件）、主要グラフ、年次詳細テーブル、感度分析を表示する。
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

import analyzer
import common
import ppa_retail_calc as calc
import solar_simulator
import visualizer

st.title("📊 PPA採算性：試算結果")

if not st.session_state.get("ppa_fs_inputs"):
    st.info("👈 まず「シナリオ設計」ページで条件を設定してください。")
    st.stop()

inputs = calc.inputs_from_dict(st.session_state["ppa_fs_inputs"])
result = calc.simulate(inputs)
breakeven = calc.compute_breakeven(inputs)
summary = result.summary
yearly = result.yearly


def _yen(v: float) -> str:
    return f"{v:,.0f}円"


def _man_yen(v: float) -> str:
    return f"{v/10_000:,.1f}万円"


def _pct(v: float | None, digits: int = 1) -> str:
    return "—" if v is None else f"{v:.{digits}f}%"


def _num(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


st.caption(f"現在のシナリオ区分: {'住宅' if inputs.customer.segment == 'residential' else '事業所'}")

k1, k2, k3 = st.columns(3)
with k1:
    st.markdown("##### 👤 顧客メリット")
    st.markdown(f"## {_yen(summary.customer_annual_saving_year1)}/年")
    st.caption(f"削減率 {_pct(summary.customer_saving_rate_pct)}")
    st.caption(f"20年累積削減額 約{_man_yen(summary.customer_cumulative_saving_20y)}")
    if yearly:
        st.caption(f"現在 {_man_yen(yearly[0].customer_current_cost)}/年 → 新プラン {_man_yen(yearly[0].customer_new_cost)}/年")
with k2:
    st.markdown("##### 🏢 事業者メリット")
    st.markdown(f"## 事業IRR {_pct(summary.project_irr_pct)}")
    st.caption(f"エクイティIRR {_pct(summary.equity_irr_pct)}")
    st.caption(f"NPV(事業) {_man_yen(summary.npv_project)}")
    _payback = "未回収" if summary.simple_payback_years is None else f"{summary.simple_payback_years:.1f}年目"
    _cum_be = "未到達" if summary.cumulative_cf_breakeven_year is None else f"{summary.cumulative_cf_breakeven_year}年目"
    st.caption(f"単純回収 {_payback} / 累積CF黒字化 {_cum_be}")
with k3:
    st.markdown("##### 🏦 金融成立性")
    st.markdown(f"## 最低DSCR {_num(summary.min_dscr)}")
    st.caption(f"平均DSCR {_num(summary.avg_dscr)}")
    st.caption(
        f"初期投資 {_man_yen(summary.initial_investment)}"
        f"（自己資金{_man_yen(summary.equity_amount)} / 借入{_man_yen(summary.debt_amount)}）"
    )

st.markdown("---")

with st.container(border=True):
    st.markdown("##### 💡 損益分岐PPA単価")
    cur_price = inputs.customer.current_unit_price
    be_rate = breakeven.breakeven_rate
    bc1, bc2, bc3 = st.columns(3)
    bc1.metric("顧客の現在単価", f"{cur_price:.1f}円/kWh")
    bc2.metric("事業成立最低単価", "算出不可" if be_rate is None else f"{be_rate:.1f}円/kWh")
    bc3.metric("提案単価", f"{inputs.customer.unified_rate:.1f}円/kWh")

    if be_rate is not None:
        st.markdown(
            f"「顧客にもメリットがあり、事業者にも成立する価格帯」： **{be_rate:.1f}〜{cur_price:.1f}円/kWh**"
        )
        if be_rate > cur_price:
            st.warning("⚠ 現在の前提では事業成立最低単価が顧客現在単価を上回っています（価格帯なし）。条件を見直すか、下の内訳・感度分析で要因を確認してください。")

    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("① NPV=0となる単価", "—" if breakeven.rate_for_npv_zero is None else f"{breakeven.rate_for_npv_zero:.2f}円/kWh")
    dc2.metric(f"② 事業IRR{inputs.finance.target_project_irr_pct:.0f}%", "—" if breakeven.rate_for_project_irr_target is None else f"{breakeven.rate_for_project_irr_target:.2f}円/kWh")
    dc3.metric(f"③ エクイティIRR{inputs.finance.target_equity_irr_pct:.0f}%", "—" if breakeven.rate_for_equity_irr_target is None else f"{breakeven.rate_for_equity_irr_target:.2f}円/kWh")
    dc4.metric(f"④ 最低DSCR{inputs.finance.target_min_dscr:.2f}以上", "—" if breakeven.rate_for_min_dscr_target is None else f"{breakeven.rate_for_min_dscr_target:.2f}円/kWh")

st.markdown("---")

tab_summary, tab_balance, tab_pattern8, tab_detail, tab_sensitivity = st.tabs(
    ["📈 グラフ・サマリー", "⚡ 需給バランス", "📅 8パターン分析", "📋 年次詳細", "🔬 感度分析"]
)

with tab_summary:
    g1, g2 = st.columns(2)
    g1.plotly_chart(visualizer.ppa_cashflow_chart(yearly), use_container_width=True)
    g2.plotly_chart(visualizer.ppa_cumulative_cf_chart(yearly), use_container_width=True)
    g3, g4 = st.columns(2)
    g3.plotly_chart(visualizer.ppa_generation_chart(yearly), use_container_width=True)
    g4.plotly_chart(visualizer.ppa_energy_mix_chart(yearly), use_container_width=True)
    g5, g6 = st.columns(2)
    g5.plotly_chart(visualizer.ppa_loan_balance_chart(yearly), use_container_width=True)
    g6.plotly_chart(visualizer.ppa_customer_compare_chart(yearly), use_container_width=True)

with tab_balance:
    sim_df = st.session_state.get("ppa_fs_sim_df")
    if sim_df is None or sim_df.empty:
        st.info(
            "「シナリオ設計」ページで実需要データを使って自家消費率を計算すると、"
            "ここで1日・1週間などの単位での需給バランス（実績の30分値）を確認できます。"
            "現在は仮定値モードのため、年間の自家消費率(%)のみを使って計算しています。"
        )
    else:
        st.caption(
            "太陽光発電がこの顧客の需要をどれだけ賄い、どれだけ余剰電力（→小売電気事業者が買い取り、"
            "他の需要家への供給電源として活用）が出て、どれだけ系統（市場等）からの調達が必要かを、"
            "実績の30分値データで確認できます。"
        )
        bal_start, bal_end, _bal_period = common.render_flexible_period(
            sim_df, key_prefix="ppa_balance",
            options=["1日", "1週間", "1か月", "3か月", "全データ期間"], default_index=1,
        )
        bal_df = analyzer.filter_by_period(sim_df, bal_start, bal_end)
        if bal_df.empty:
            st.warning("選択した期間にデータがありません。")
        else:
            bal_kpis = solar_simulator.calc_kpis(bal_df)
            bk1, bk2, bk3, bk4 = st.columns(4)
            bk1.metric("需要量", f"{bal_kpis['total_demand_kwh']:,.0f} kWh")
            bk2.metric("太陽光発電量", f"{bal_kpis['total_solar_kwh']:,.0f} kWh")
            bk3.metric("自給率", f"{bal_kpis['self_sufficiency_rate']:.1f} %")
            bk4.metric("外部調達(系統)", f"{bal_kpis['total_grid_import_kwh']:,.0f} kWh")
            bk5, bk6 = st.columns(2)
            bk5.metric("余剰電力(売電・他需要家供給用)", f"{bal_kpis['total_grid_export_kwh']:,.0f} kWh")
            bk6.metric("自家消費率(発電量に対して)", f"{bal_kpis['self_consumption_rate']:.1f} %")
            st.plotly_chart(visualizer.solar_supply_chart(bal_df, title=f"需給バランス（{_bal_period}）"), use_container_width=True)

with tab_pattern8:
    sim_df = st.session_state.get("ppa_fs_sim_df")
    if sim_df is None or sim_df.empty:
        st.info(
            "「シナリオ設計」ページで実需要データを使って自家消費率を計算すると、"
            "季節（春夏秋冬）×平日/休日の8パターンで代表的な1日の需給バランスを確認できます。"
        )
    else:
        st.caption(
            "実績データをもとに、季節×平日/休日の組み合わせごとに、同じ時間帯の実績を平均した"
            "「代表的な1日」の需給バランス（30分値）を比較します。"
        )
        _p8 = sim_df.copy()
        _p8["season"] = analyzer.assign_season(_p8["datetime"])
        _p8["day_type"] = analyzer.assign_day_type(_p8["datetime"])
        _p8["hour"] = _p8["datetime"].dt.hour
        _p8["minute"] = _p8["datetime"].dt.minute

        _P8_SEASONS = ["春", "夏", "秋", "冬"]
        _P8_DAY_TYPES = ["平日", "休日"]
        _P8_COLS = [
            "demand_kwh", "solar_kwh", "direct_use_kwh",
            "battery_charge_kwh", "battery_discharge_kwh", "grid_import_kwh", "grid_export_kwh",
        ]
        _P8_BASE_DATE = pd.Timestamp("2000-01-01")

        def _p8_representative_day(season: str, day_type: str) -> tuple[pd.DataFrame, int]:
            sub = _p8[(_p8["season"] == season) & (_p8["day_type"] == day_type)]
            n_days = sub["datetime"].dt.date.nunique()
            rep = sub.groupby(["hour", "minute"], as_index=False)[_P8_COLS].mean()
            rep["datetime"] = (
                _P8_BASE_DATE + pd.to_timedelta(rep["hour"], unit="h") + pd.to_timedelta(rep["minute"], unit="m")
            )
            rep = rep.sort_values("datetime").reset_index(drop=True)
            return rep, n_days

        for _season in _P8_SEASONS:
            st.markdown(f"#### {_season}")
            _cols = st.columns(2)
            for _day_type, _col in zip(_P8_DAY_TYPES, _cols):
                _rep, _n_days = _p8_representative_day(_season, _day_type)
                with _col:
                    if _rep.empty or _rep["demand_kwh"].isna().all():
                        st.info(f"{_season}・{_day_type}：データがありません。")
                        continue
                    _rep_kpis = solar_simulator.calc_kpis(_rep)
                    st.caption(f"{_day_type}（{_n_days}日の平均）")
                    _rk1, _rk2, _rk3 = st.columns(3)
                    _rk1.metric("需要量", f"{_rep_kpis['total_demand_kwh']:,.1f} kWh")
                    _rk2.metric("自給率", f"{_rep_kpis['self_sufficiency_rate']:.1f} %")
                    _rk3.metric("外部調達", f"{_rep_kpis['total_grid_import_kwh']:,.1f} kWh")
                    _fig = visualizer.solar_supply_chart(_rep, title=f"{_season}・{_day_type}の代表的な1日")
                    _fig.update_xaxes(tickformat="%H:%M", title="時刻")
                    st.plotly_chart(_fig, use_container_width=True)
            st.markdown("---")

with tab_detail:
    rows = []
    for y in yearly:
        rows.append({
            "年": y.year,
            "発電量(kWh)": round(y.generation_kwh),
            "自家消費(kWh)": round(y.self_consumed_kwh),
            "余剰(kWh)": round(y.surplus_kwh),
            "外部調達(kWh)": round(y.external_procurement_kwh),
            "収入計(円)": round(y.total_revenue),
            "支出計(円)": round(y.total_opex),
            "EBITDA(円)": round(y.ebitda),
            "元利返済(円)": round(y.debt_service),
            "返済後CF(円)": round(y.cf_after_debt),
            "累積CF(円)": round(y.cumulative_cf_after_debt),
            "借入残高(円)": round(y.loan_balance_end),
            "DSCR": None if y.dscr is None else round(y.dscr, 2),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, height=480, hide_index=True)

    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    st.download_button(
        "📥 年次結果をCSV出力", data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name="ppa_fs_yearly_result.csv", mime="text/csv",
    )

with tab_sensitivity:
    st.caption(
        "主要11変数を ±10%／±20% 変化させ、事業IRR・NPV(事業)・最低DSCRへの影響を比較します。"
        "「NPV(事業)」は無借金換算（元利返済前CF基準）のため、金利は定義上ここに影響しません"
        "（エクイティIRR・DSCRには影響します）。値が0の変数は、現在のシナリオ設定でその項目が"
        "使われていないことを示します（例: 補助金0円、O&M費が%モード、最終年度が「撤去」以外 等）。"
    )
    points = calc.compute_sensitivity(inputs)
    ranking = calc.rank_sensitivity_impact(points)
    st.plotly_chart(visualizer.ppa_sensitivity_tornado_chart(ranking), use_container_width=True)

    by_key: dict[str, list] = {}
    for p in points:
        by_key.setdefault(p.variable_key, []).append(p)

    for r in ranking:
        with st.expander(r["label"], expanded=False):
            pts = sorted(by_key[r["key"]], key=lambda p: p.change_pct)
            rows = [{
                "変化率": f"{p.change_pct:+d}%",
                "事業IRR": _pct(p.project_irr_pct),
                "NPV(事業)": _man_yen(p.npv_project),
                "最低DSCR": _num(p.min_dscr),
            } for p in pts]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
