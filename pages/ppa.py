"""
pages/ppa.py
太陽光＋蓄電池 PPA シミュレーション。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import common
import pdf_report
import report_generator
import solar_simulator
import visualizer


def _fmt(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f} MWh"
    if v >= 1_000:
        return f"{v/1_000:.1f} MWh"
    return f"{v:.2f} kWh"


st.title("☀️ 太陽光＋蓄電池 PPA シミュレーション")
st.caption(
    "実際の需要データを使い、太陽光・蓄電池を導入した場合の自家消費率と蓄電池稼働を試算します。"
    "（日射量モデル：上田市周辺 NEDO 概算値）"
)

df = common.require_data()
facility_names, group_df = common.get_group_context(df)
filtered_base, group_mode = common.render_facility_filter(df, facility_names, group_df)

# ── ① 導入容量・分析期間 ────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**① 導入容量・分析期間**")
    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    with col_p1:
        sim_solar_kw = st.number_input(
            "太陽光容量 (kWp)", min_value=1.0, max_value=5000.0,
            value=100.0, step=10.0, key="sim_solar_kw",
            help="パネルの定格出力。100 kWp 程度から試してください。",
        )
    with col_p2:
        sim_battery_kwh = st.number_input(
            "蓄電池容量 (kWh)", min_value=0.0, max_value=50000.0,
            value=0.0, step=10.0, key="sim_battery_kwh_input",
            help="0 の場合は蓄電池なし（太陽光のみ）のシミュレーションになります。",
        )
    with col_p3:
        sim_battery_eff = st.slider(
            "充放電往復効率 (%)", min_value=70, max_value=99,
            value=95, key="sim_battery_eff",
            help="充電→放電の往復効率。リチウムイオンは 90〜97 % 程度。",
        ) / 100.0
    with col_p4:
        sim_period = st.selectbox(
            "分析期間", ["全データ期間", "直近1年", "直近6か月", "直近3か月"],
            key="sim_period",
            help="KPI・月別グラフの集計範囲。",
        )

# ── ② 充放電モード ───────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**② 充放電モード**")
    sim_mode = st.radio(
        "モードを選択",
        options=list(solar_simulator.BATTERY_MODE_LABELS.keys()),
        format_func=lambda x: {
            "basic": "🔋 自家消費優先（基本） — 余剰太陽光で充電し、太陽光が足りない時に自動放電",
            "reserve": "🚨 防災バッファ付き — 最低残量を常時確保しつつ自家消費優先",
            "peak_cut": "⚡ ピークカット — デマンドが閾値を超えた時のみ放電（需要ピーク抑制）",
        }[x],
        key="sim_mode",
        horizontal=False,
    )

    if sim_mode == "reserve":
        col_r1, col_r2 = st.columns([1, 3])
        with col_r1:
            sim_min_soc = st.slider(
                "最低残量 (%)", min_value=10, max_value=70, value=30, step=5,
                key="sim_min_soc",
                help="常時確保しておく蓄電池残量。30% = 蓄電池容量の30%を常に備蓄。",
            )
        with col_r2:
            if sim_battery_kwh > 0:
                reserve_kwh = sim_battery_kwh * sim_min_soc / 100
                st.info(
                    f"蓄電池 {sim_battery_kwh:.0f} kWh の場合、"
                    f"**{reserve_kwh:.0f} kWh** を防災用に確保。"
                    f"日常使用できるのは **{sim_battery_kwh - reserve_kwh:.0f} kWh**。"
                )
        sim_min_soc_f = float(sim_min_soc)
        sim_peak_kw = None
    elif sim_mode == "peak_cut":
        _auto_thresh = solar_simulator.auto_peak_threshold_kw(filtered_base)
        col_k1, col_k2 = st.columns([1, 3])
        with col_k1:
            sim_peak_kw = st.number_input(
                "デマンド閾値 (kW)", min_value=1.0,
                value=float(_auto_thresh), step=5.0,
                key="sim_peak_kw",
                help="この値を超える需要が発生したときのみ蓄電池が放電します。",
            )
        with col_k2:
            st.info(
                f"自動計算値（需要の 80 パーセンタイル）= **{_auto_thresh:.1f} kW**。"
                " 値を下げると蓄電池の放電機会が増え、自給率が向上します。"
            )
        sim_min_soc_f = 0.0
    else:
        sim_min_soc_f = 0.0
        sim_peak_kw = None

sim_base_df = common.filter_by_period_option(filtered_base, sim_period)

col_btn1, col_btn2 = st.columns([1, 1])
with col_btn1:
    run_sim = st.button("▶ シミュレーション実行", type="primary", use_container_width=True)
with col_btn2:
    run_sweep = st.button(
        "📊 適正蓄電池容量を診断", use_container_width=True,
        help="蓄電池容量を変えてシミュレーションし、最適容量を自動提案します（数秒かかります）。",
    )

if run_sim:
    with st.spinner("シミュレーション計算中..."):
        _sim_result = solar_simulator.run_simulation(
            sim_base_df,
            solar_capacity_kw=sim_solar_kw,
            battery_capacity_kwh=sim_battery_kwh,
            battery_efficiency=sim_battery_eff,
            mode=sim_mode,
            min_soc_pct=sim_min_soc_f,
            peak_threshold_kw=sim_peak_kw,
        )
    st.session_state["ppa_sim_result"] = _sim_result
    st.session_state["ppa_sim_battery_kwh"] = sim_battery_kwh
    st.session_state["ppa_sim_mode"] = sim_mode

if run_sweep:
    with st.spinner("容量診断中（数秒かかります）..."):
        _sweep_df, _rec_kwh = solar_simulator.sweep_battery_capacity(
            sim_base_df,
            solar_capacity_kw=sim_solar_kw,
            battery_efficiency=sim_battery_eff,
            mode=sim_mode,
            min_soc_pct=sim_min_soc_f,
            peak_threshold_kw=sim_peak_kw,
        )
    st.session_state["ppa_sweep_df"] = _sweep_df
    st.session_state["ppa_rec_kwh"] = _rec_kwh

_sweep_df = st.session_state.get("ppa_sweep_df")
_rec_kwh = st.session_state.get("ppa_rec_kwh", 0)
if _sweep_df is not None:
    st.markdown("#### 📊 適正蓄電池容量 診断結果")
    rec_col1, rec_col2, rec_col3 = st.columns([1, 1, 2])
    rec_col1.metric("推奨蓄電池容量", f"{_rec_kwh:.0f} kWh")
    if not _sweep_df.empty:
        _rec_row = _sweep_df[_sweep_df["battery_kwh"] >= _rec_kwh]
        if not _rec_row.empty:
            rec_col2.metric("その時の自給率", f"{_rec_row['self_sufficiency_rate'].iloc[0]:.1f}%")
    with rec_col3:
        _mode_label = solar_simulator.BATTERY_MODE_LABELS.get(sim_mode, sim_mode)
        st.caption(f"モード: {_mode_label} ／ 太陽光: {sim_solar_kw:.0f} kWp ／ 分析期間: {sim_period}")
    st.plotly_chart(visualizer.battery_sweep_chart(_sweep_df, _rec_kwh), use_container_width=True)
    st.markdown("---")

ppa_sim: pd.DataFrame | None = st.session_state.get("ppa_sim_result")

if ppa_sim is None:
    st.info("パラメータを設定し「▶ シミュレーション実行」を押してください。")
else:
    kpis = solar_simulator.calc_kpis(ppa_sim)
    _stored_mode = st.session_state.get("ppa_sim_mode", "basic")
    _mode_label = solar_simulator.BATTERY_MODE_LABELS.get(_stored_mode, _stored_mode)

    st.markdown(f"#### シミュレーション結果　｜　モード: {_mode_label}")
    k1, k2, k3 = st.columns(3)
    k1.metric("自家消費率", f"{kpis['self_consumption_rate']:.1f}%",
              help="発電量のうち自家消費（直接＋蓄電池経由）した割合")
    k2.metric("自給率", f"{kpis['self_sufficiency_rate']:.1f}%",
              help="総需要のうち太陽光＋蓄電池で賄えた割合")
    k3.metric("発電量（期間合計）", _fmt(kpis["total_solar_kwh"]))

    k4, k5, k6 = st.columns(3)
    k4.metric("グリッド買電削減量", _fmt(kpis["grid_reduction_kwh"]))
    k5.metric("グリッド買電削減率", f"{kpis['grid_reduction_rate']:.1f}%")
    k6.metric("系統への売電量", _fmt(kpis["total_grid_export_kwh"]),
              help="蓄電池に入りきらなかった余剰太陽光が系統へ流れた量")

    st.markdown("---")

    period_label = (
        f"{ppa_sim['datetime'].min().strftime('%Y/%m/%d')} 〜 "
        f"{ppa_sim['datetime'].max().strftime('%Y/%m/%d')}"
    )
    st.caption(f"📅 分析期間: {period_label}（① で選択した「分析期間」の範囲）")

    _stored_battery = st.session_state.get("ppa_sim_battery_kwh", 0)
    _fig_supply = visualizer.solar_supply_chart(ppa_sim)
    _fig_monthly = visualizer.monthly_self_consumption_bar(ppa_sim)

    _report_figures: list[tuple] = [(_fig_supply, "需給バランス（太陽光・蓄電池導入後）")]
    if _stored_battery > 0:
        _fig_battery = visualizer.battery_operation_chart(ppa_sim, battery_capacity_kwh=_stored_battery)
        _report_figures.append((_fig_battery, "蓄電池 充放電・残量推移"))
    _report_figures.append((_fig_monthly, "月別 自家消費率・自給率"))

    st.plotly_chart(_fig_supply, use_container_width=True)
    if _stored_battery > 0:
        st.plotly_chart(_fig_battery, use_container_width=True)
    st.plotly_chart(_fig_monthly, use_container_width=True)

    st.markdown("---")
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        _html_bytes = pdf_report.build_html_report(
            sim_df=ppa_sim, kpis=kpis, figures=_report_figures,
            solar_kw=sim_solar_kw, battery_kwh=_stored_battery,
            battery_eff=sim_battery_eff, mode_label=_mode_label, analysis_period=sim_period,
        )
        st.download_button(
            label="📄 PDFレポートをダウンロード（HTML）", data=_html_bytes,
            file_name=f"PPA_report_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.html",
            mime="text/html",
            help="ダウンロードしたHTMLをブラウザで開き、Ctrl+P → PDF として保存してください。",
            use_container_width=True,
        )
    with dl_col2:
        _excel_bytes = report_generator.build_excel_report(
            sim_df=ppa_sim, kpis=kpis, solar_kw=sim_solar_kw, battery_kwh=_stored_battery,
            battery_eff=sim_battery_eff, mode_label=_mode_label, analysis_period=sim_period,
        )
        st.download_button(
            label="📥 Excelデータをダウンロード", data=_excel_bytes,
            file_name=f"PPA_data_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
