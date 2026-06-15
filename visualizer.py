"""
visualizer.py
Plotly を使ってグラフを生成する関数群。
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# 共通カラーパレット
COLORS = px.colors.qualitative.Set2
SUPPLY_COLORS = {
    "太陽光": "#F4D03F",
    "蓄電池": "#5DADE2",
    "市場調達": "#58D68D",
    "その他": "#EC7063",
}


# ---------------------------------------------------------------------------
# 需要カーブ（30 分値折れ線）
# ---------------------------------------------------------------------------

def demand_timeseries(
    df: pd.DataFrame,
    title: str = "電力使用量（30分値）",
    y_label: str = "使用量 (kWh/30min)",
) -> go.Figure:
    """
    df: datetime, consumption_kwh[, facility_name]
    facility_name 列があれば施設ごとに色分けする。
    """
    has_facility = "facility_name" in df.columns and df["facility_name"].nunique() > 1

    fig = px.line(
        df,
        x="datetime",
        y="consumption_kwh",
        color="facility_name" if has_facility else None,
        labels={"consumption_kwh": y_label, "datetime": "日時", "facility_name": "施設"},
        title=title,
        color_discrete_sequence=COLORS,
    )
    fig.update_layout(
        hovermode="x unified",
        legend_title_text="施設",
        xaxis_title="日時",
        yaxis_title=y_label,
        margin=dict(l=20, r=20, t=50, b=20),
    )
    fig.update_traces(line_width=1.5)
    return fig


# ---------------------------------------------------------------------------
# 日別使用量棒グラフ
# ---------------------------------------------------------------------------

def daily_bar(df: pd.DataFrame, by_facility: bool = False) -> go.Figure:
    fig = px.bar(
        df,
        x="date",
        y="consumption_kwh",
        color="facility_name" if by_facility else None,
        labels={"consumption_kwh": "使用量 (kWh/日)", "date": "日付", "facility_name": "施設"},
        title="日別使用量",
        color_discrete_sequence=COLORS,
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# 月別使用量棒グラフ
# ---------------------------------------------------------------------------

def monthly_bar(df: pd.DataFrame, by_facility: bool = False) -> go.Figure:
    df = df.copy()
    df["month_str"] = df["month"].dt.strftime("%Y-%m")
    fig = px.bar(
        df,
        x="month_str",
        y="consumption_kwh",
        color="facility_name" if by_facility else None,
        labels={"consumption_kwh": "使用量 (kWh/月)", "month_str": "月", "facility_name": "施設"},
        title="月別使用量",
        color_discrete_sequence=COLORS,
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# 時間帯別平均棒グラフ
# ---------------------------------------------------------------------------

def hourly_avg_bar(df: pd.DataFrame, by_facility: bool = False) -> go.Figure:
    fig = px.bar(
        df,
        x="hour",
        y="consumption_kwh",
        color="facility_name" if by_facility else None,
        labels={"consumption_kwh": "平均使用量 (kWh/30min)", "hour": "時刻（時）", "facility_name": "施設"},
        title="時間帯別平均使用量",
        color_discrete_sequence=COLORS,
    )
    fig.update_xaxes(dtick=1)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# 平日・休日比較折れ線
# ---------------------------------------------------------------------------

def weekday_holiday_line(df: pd.DataFrame) -> go.Figure:
    fig = px.line(
        df,
        x="hour",
        y="consumption_kwh",
        color="day_type",
        labels={"consumption_kwh": "平均使用量 (kWh/30min)", "hour": "時刻（時）", "day_type": ""},
        title="平日・休日の時間帯別平均使用量",
        color_discrete_map={"平日": "#2E86AB", "休日": "#E84855"},
    )
    fig.update_xaxes(dtick=1)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# 施設別年間使用量ランキング
# ---------------------------------------------------------------------------

def facility_ranking_bar(df: pd.DataFrame) -> go.Figure:
    fig = px.bar(
        df.sort_values("annual_kwh"),
        x="annual_kwh",
        y="facility_name",
        orientation="h",
        labels={"annual_kwh": "年間使用量 (kWh)", "facility_name": "施設"},
        title="施設別年間使用量ランキング",
        color_discrete_sequence=COLORS,
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# 需給バランス（需要カーブ + 供給積み上げ）
# ---------------------------------------------------------------------------

def supply_demand_chart(balance_df: pd.DataFrame) -> go.Figure:
    supply_col_labels = {
        "solar_kwh": "太陽光",
        "battery_kwh": "蓄電池",
        "market_kwh": "市場調達",
        "other_kwh": "その他",
    }
    fig = go.Figure()

    # 供給積み上げ棒グラフ
    for col, label in supply_col_labels.items():
        if col in balance_df.columns:
            fig.add_trace(go.Bar(
                x=balance_df["datetime"],
                y=balance_df[col],
                name=label,
                marker_color=SUPPLY_COLORS.get(label, "#999"),
            ))

    # 需要折れ線
    fig.add_trace(go.Scatter(
        x=balance_df["datetime"],
        y=balance_df["demand_kwh"],
        mode="lines",
        name="需要",
        line=dict(color="black", width=2),
    ))

    fig.update_layout(
        barmode="stack",
        title="需給バランス",
        xaxis_title="日時",
        yaxis_title="電力量 (kWh/30min)",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


# ---------------------------------------------------------------------------
# 電源構成比 円グラフ
# ---------------------------------------------------------------------------

def supply_mix_pie(mix_df: pd.DataFrame) -> go.Figure:
    fig = px.pie(
        mix_df,
        names="source",
        values="kwh",
        title="電源構成比",
        color="source",
        color_discrete_map=SUPPLY_COLORS,
    )
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig
