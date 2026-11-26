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

# ── JSONバックアップ（書き出し／読み込み） ─────────────────────────────
# Community Cloud等ではアプリの再起動で保存済みシナリオが消えるため、手元に退避・復元できるようにする。
with st.expander("💾 シナリオのバックアップ（JSONの書き出し／読み込み）", expanded=not saved_scenarios):
    st.caption(
        "保存済みシナリオをJSONで書き出し、アプリが再起動して消えたあとにここから読み込んで復元できます。"
        "同じ名前のシナリオは上書きされます。シナリオの前提には、供給データの電源名・施設設定・単価が含まれます"
        "（需要・供給の30分値そのものは含まれないため、先に「データ読み込み」で再アップロードしてください）。"
    )
    if saved_scenarios:
        st.download_button(
            "⬇ 全シナリオをJSONで書き出す", data=scenario_manager.scenarios_to_json(saved_scenarios),
            file_name="retail_fs_scenarios.json", mime="application/json", key="fs_scenarios_download",
        )
    _sc_upload = st.file_uploader("シナリオのJSONを読み込む", type=["json"], key="fs_scenarios_upload")
    if _sc_upload is not None and st.session_state.get("fs_scenarios_upload_id") != _sc_upload.file_id:
        try:
            _n = scenario_manager.import_scenarios(
                scenario_manager.scenarios_from_json(_sc_upload.getvalue().decode("utf-8"))
            )
            st.session_state["fs_scenarios_upload_id"] = _sc_upload.file_id
            st.success(f"{_n} 件のシナリオを読み込みました。")
            st.rerun()
        except ValueError as _e:
            st.error(str(_e))

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
            _jepx_df = st.session_state.get("jepx_actual_df")
            _jepx_series = _jepx_df.set_index("datetime")["jepx_price_yen"] if _jepx_df is not None else None
            _cur_supply = st.session_state.get("supply_df")
            _warn_msgs: dict[str, list[str]] = {}
            for sc in saved_scenarios:
                try:
                    fs_result = scenario_manager.run_scenario(
                        sc, cmp_demand_df, jepx_actual_series=_jepx_series, fallback_supply_df=_cur_supply,
                    )
                    summaries[sc.name] = scenario_manager.annual_summary(fs_result)
                    for _w in fs_result.get("warnings", []):
                        _warn_msgs.setdefault(_w, []).append(sc.name)
                except Exception as e:
                    st.error(f"シナリオ「{sc.name}」の計算でエラーが発生しました: {e}")
            st.session_state["scenario_summaries"] = summaries
            st.session_state["scenario_warnings"] = _warn_msgs
            st.session_state["scenario_summaries_fingerprint"] = _cmp_fingerprint

    summaries = st.session_state.get("scenario_summaries")
    if summaries and st.session_state.get("scenario_summaries_fingerprint") != _cmp_fingerprint:
        st.warning(
            "⚠️ 比較対象期間または保存済みシナリオが変更されていますが、下記の結果はまだ変更前のものです。"
            "「▶ 全シナリオを一括計算して比較」を押して再計算してください。"
        )
    for _w, _names in (st.session_state.get("scenario_warnings") or {}).items():
        st.warning(f"{_w}（{len(_names)}件：{', '.join(_names[:4])}{' ほか' if len(_names) > 4 else ''}）")
    if summaries:
        st.plotly_chart(visualizer.scenario_comparison_chart(summaries), use_container_width=True)
        cmp_tbl = pd.DataFrame(summaries).T.rename(columns={
            "revenue": "売上高(円)", "cost_of_sales": "売上原価(円)", "gross_profit": "売上総利益(円)",
            "net_income": "当期純利益(円)", "gross_margin_pct": "粗利率(%)",
            "market_sale_revenue": "うち市場売却収入(円)",
        })
        st.dataframe(
            cmp_tbl, use_container_width=True,
            column_config={
                c: st.column_config.NumberColumn(c, format="%,.1f" if "%" in c else "%,.0f") for c in cmp_tbl.columns
            },
        )
