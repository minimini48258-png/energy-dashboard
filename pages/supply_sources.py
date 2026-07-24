"""
pages/supply_sources.py
電源管理（自社発電・相対電源のパラメータ設定）。
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

import supply_planner
import visualizer

st.title("⚡ 電源管理")
st.caption(
    "新電力として調達・運用する電源を登録します。需給分析・小売FSに使用されます。"
    "「相対電源」を選ぶと、相対契約（固定単価・契約数量）での電力調達として扱われます。"
)

_MONTH_NAMES = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]


def _source_form(prefix: str, defaults: dict | None = None) -> dict | None:
    """電源追加/編集フォーム。保存ボタンが押されたら dict を返す。"""
    d = defaults or {}
    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
    name = col1.text_input("電源名", value=d.get("name", ""), key=f"{prefix}_name")
    stype_lbl = col2.selectbox(
        "種別",
        options=list(supply_planner.SOURCE_TYPE_LABELS.values()),
        index=list(supply_planner.SOURCE_TYPE_LABELS.values()).index(
            supply_planner.SOURCE_TYPE_LABELS.get(d.get("source_type", "hydro"), "水力")
        ),
        key=f"{prefix}_type",
    )
    cap = col3.number_input("設備容量 (kW)", min_value=0.0, value=float(d.get("capacity_kw", 300.0)),
                             step=10.0, key=f"{prefix}_cap")
    cost = col4.number_input("発電コスト (円/kWh)", min_value=0.0,
                              value=float(d.get("cost_per_kwh", 8.0)), step=0.5, key=f"{prefix}_cost")

    st.caption("月別稼働率 (%)")
    monthly_default = d.get("monthly_utilization_pct", [80.0] * 12)
    cols6a = st.columns(6)
    cols6b = st.columns(6)
    monthly = []
    for i, (mn, c) in enumerate(zip(_MONTH_NAMES[:6], cols6a)):
        monthly.append(c.number_input(mn, 0, 100, int(monthly_default[i]), key=f"{prefix}_m{i}"))
    for i, (mn, c) in enumerate(zip(_MONTH_NAMES[6:], cols6b)):
        monthly.append(c.number_input(mn, 0, 100, int(monthly_default[i + 6]), key=f"{prefix}_m{i+6}"))

    st.caption("時間帯別出力比")
    preset_opts = list(supply_planner.HOURLY_PRESETS.keys()) + ["カスタム"]
    hourly_default = d.get("hourly_pattern_pct", [100.0] * 24)
    matched_preset = "カスタム"
    for pname, pvals in supply_planner.HOURLY_PRESETS.items():
        if pvals == hourly_default:
            matched_preset = pname
            break
    preset = st.radio("プリセット", preset_opts,
                       index=preset_opts.index(matched_preset),
                       horizontal=True, key=f"{prefix}_preset")
    if preset == "カスタム":
        hourly_df = pd.DataFrame({
            "時間帯": [f"{h:02d}:00" for h in range(24)],
            "出力比(%)": hourly_default,
        })
        edited_h = st.data_editor(
            hourly_df,
            column_config={"出力比(%)": st.column_config.NumberColumn(min_value=0, max_value=100)},
            hide_index=True, use_container_width=True, height=400, key=f"{prefix}_heditor",
        )
        hourly = edited_h["出力比(%)"].tolist()
    else:
        hourly = supply_planner.HOURLY_PRESETS[preset]
        st.plotly_chart(
            visualizer.hourly_pattern_bar(hourly, name or "電源"),
            use_container_width=True,
        )

    start_date_str = st.text_input("運転開始日 (YYYY-MM-DD、空欄=既存)",
                                    value=d.get("start_date") or "", key=f"{prefix}_start")

    if st.button("💾 保存", key=f"{prefix}_save"):
        if not name:
            st.error("電源名を入力してください。")
            return None
        return {
            "name": name,
            "source_type": supply_planner.SOURCE_TYPE_KEYS.get(stype_lbl, "hydro"),
            "capacity_kw": cap,
            "cost_per_kwh": cost,
            "monthly_utilization_pct": monthly,
            "hourly_pattern_pct": hourly,
            "start_date": start_date_str or None,
        }
    return None


sources_raw: list[dict] = st.session_state.get("supply_sources", [])
sources = [supply_planner.SupplySource(**s) for s in sources_raw]

if sources:
    for idx, src in enumerate(sources):
        type_lbl = supply_planner.SOURCE_TYPE_LABELS.get(src.source_type, src.source_type)
        with st.container(border=True):
            h1, h2, h3, h_edit, h_del = st.columns([3, 2, 2, 1, 1])
            h1.markdown(f"**{src.name}**")
            h2.caption(f"{type_lbl} / {src.capacity_kw:.0f} kW")
            h3.caption(f"{src.cost_per_kwh:.1f} 円/kWh")
            if h_edit.button("編集", key=f"edit_{idx}"):
                st.session_state["editing_source_idx"] = idx
                st.rerun()
            if h_del.button("削除", key=f"del_src_{idx}"):
                sources.pop(idx)
                st.session_state["supply_sources"] = [asdict(s) for s in sources]
                try:
                    supply_planner.save_sources(sources)
                except Exception:
                    pass
                st.rerun()
else:
    st.info("電源が登録されていません。")

editing_idx = st.session_state.get("editing_source_idx")

if editing_idx is not None:
    label = "電源を編集" if editing_idx >= 0 else "電源を追加"
    st.markdown(f"#### {label}")
    defaults = asdict(sources[editing_idx]) if editing_idx >= 0 else None
    result = _source_form(prefix=f"src_form_{editing_idx}", defaults=defaults)
    if result:
        new_src = supply_planner.SupplySource(**result)
        if editing_idx >= 0:
            sources[editing_idx] = new_src
        else:
            sources.append(new_src)
        st.session_state["supply_sources"] = [asdict(s) for s in sources]
        st.session_state["editing_source_idx"] = None
        try:
            supply_planner.save_sources(sources)
        except Exception:
            pass
        st.rerun()
    if st.button("キャンセル", key="cancel_form"):
        st.session_state["editing_source_idx"] = None
        st.rerun()
else:
    if st.button("＋ 電源を追加"):
        st.session_state["editing_source_idx"] = -1
        st.rerun()
