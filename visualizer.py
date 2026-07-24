"""
visualizer.py
Plotly を使ってグラフを生成する関数群。
"""

from __future__ import annotations

__version__ = "1.1.0"  # supply_demand_balance_chart, monthly_pnl_chart, hourly_pattern_bar 追加

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

# 収支FS（売上高/売上原価/粗利益）用の固定配色。
# dataviz スキルの validate_palette.js で colorblind-safe（all-pairs）を確認済み。
FS_REVENUE_COLOR = "#2a78d6"   # 売上高（紺）
FS_COST_COLOR    = "#e34948"   # 売上原価（赤）
FS_PROFIT_COLOR  = "#008300"   # 売上総利益・粗利益（緑）
_FS_TITLE_COLOR  = "#1F3864"


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


# ---------------------------------------------------------------------------
# PPA シミュレーション
# ---------------------------------------------------------------------------

def solar_supply_chart(
    sim_df: pd.DataFrame,
    title: str = "需給バランス（太陽光・蓄電池導入後）",
) -> go.Figure:
    """
    太陽光＋蓄電池シミュレーション結果の需給バランスを積み上げ棒グラフで表示。
    7日以内: 30分値、それ以降: 日別集計に自動切替。
    """
    n_days = (sim_df["datetime"].max() - sim_df["datetime"].min()).days

    if n_days <= 7:
        plot_df = sim_df.copy()
        x_col, x_label, unit = "datetime", "日時", "kWh/30min"
    else:
        plot_df = sim_df.copy()
        plot_df["date"] = plot_df["datetime"].dt.date
        plot_df = plot_df.groupby("date", as_index=False).agg(
            direct_use_kwh=("direct_use_kwh", "sum"),
            battery_discharge_kwh=("battery_discharge_kwh", "sum"),
            battery_charge_kwh=("battery_charge_kwh", "sum"),
            grid_import_kwh=("grid_import_kwh", "sum"),
            grid_export_kwh=("grid_export_kwh", "sum"),
            solar_kwh=("solar_kwh", "sum"),
            demand_kwh=("demand_kwh", "sum"),
        )
        plot_df["date"] = pd.to_datetime(plot_df["date"])
        x_col, x_label, unit = "date", "日付", "kWh/日"

    fig = go.Figure()

    # ── 需要側（0より上）: 積み上げ棒グラフ ─────────────────────────────────
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=plot_df["grid_import_kwh"],
        name="グリッド買電", marker_color="#EC7063", opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=plot_df["battery_discharge_kwh"],
        name="蓄電池放電", marker_color="#5DADE2", opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=plot_df["direct_use_kwh"],
        name="太陽光直接消費", marker_color="#F4D03F", opacity=0.85,
    ))

    # ── 余剰側（0より下）: 蓄電池充電・売電 ─────────────────────────────────
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=-plot_df["battery_charge_kwh"],
        name="蓄電池充電", marker_color="#58D68D", opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=-plot_df["grid_export_kwh"],
        name="系統への売電", marker_color="#A569BD", opacity=0.85,
    ))

    # ── 折れ線 ───────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=plot_df[x_col], y=plot_df["demand_kwh"],
        mode="lines", name="需要",
        line=dict(color="black", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=plot_df[x_col], y=plot_df["solar_kwh"],
        mode="lines", name="太陽光発電",
        line=dict(color="#E67E22", width=1.5, dash="dash"),
    ))

    fig.update_layout(
        barmode="relative",   # 正は0から上、負は0から下に正しく展開
        title=title,
        xaxis_title=x_label,
        yaxis=dict(
            title=f"電力量 ({unit})",
            zeroline=True, zerolinewidth=2, zerolinecolor="gray",
        ),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def battery_operation_chart(
    sim_df: pd.DataFrame,
    battery_capacity_kwh: float = 0.0,
    title: str = "蓄電池 充放電・残量推移",
) -> go.Figure:
    """
    蓄電池の充電（正）・放電（負）棒グラフと SOC 折れ線を重ねて表示。
    7日以内: 30分値、それ以降: 日別集計。
    """
    n_days = (sim_df["datetime"].max() - sim_df["datetime"].min()).days

    if n_days <= 7:
        plot_df = sim_df.copy()
        x_col, x_label, unit = "datetime", "日時", "kWh/30min"
    else:
        plot_df = sim_df.copy()
        plot_df["date"] = plot_df["datetime"].dt.date
        plot_df = plot_df.groupby("date", as_index=False).agg(
            battery_charge_kwh=("battery_charge_kwh", "sum"),
            battery_discharge_kwh=("battery_discharge_kwh", "sum"),
            battery_soc_kwh=("battery_soc_kwh", "mean"),
        )
        plot_df["date"] = pd.to_datetime(plot_df["date"])
        x_col, x_label, unit = "date", "日付", "kWh/日"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=plot_df["battery_charge_kwh"],
        name="充電", marker_color="#58D68D", opacity=0.75,
    ))
    fig.add_trace(go.Bar(
        x=plot_df[x_col], y=-plot_df["battery_discharge_kwh"],
        name="放電", marker_color="#5DADE2", opacity=0.75,
    ))
    fig.add_trace(go.Scatter(
        x=plot_df[x_col], y=plot_df["battery_soc_kwh"],
        mode="lines", name="残量 (SOC)",
        line=dict(color="#8E44AD", width=2),
        yaxis="y2",
    ))

    y2_max = battery_capacity_kwh * 1.05 if battery_capacity_kwh > 0 else None
    fig.update_layout(
        barmode="relative",
        title=title,
        xaxis_title=x_label,
        yaxis_title=f"充放電量 ({unit})",
        yaxis2=dict(
            title="残量 (kWh)",
            overlaying="y",
            side="right",
            showgrid=False,
            range=[0, y2_max] if y2_max else None,
        ),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def battery_sweep_chart(
    sweep_df: pd.DataFrame,
    recommended_kwh: float,
    title: str = "蓄電池容量と自給率の関係（適正容量診断）",
) -> go.Figure:
    """
    容量スイープ結果を折れ線で表示し、推奨容量を縦線でマークする。
    sweep_df: battery_kwh, self_consumption_rate, self_sufficiency_rate
    """
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=sweep_df["battery_kwh"], y=sweep_df["self_sufficiency_rate"],
        mode="lines+markers", name="自給率",
        line=dict(color="#5DADE2", width=2.5),
        marker=dict(size=7),
    ))
    fig.add_trace(go.Scatter(
        x=sweep_df["battery_kwh"], y=sweep_df["self_consumption_rate"],
        mode="lines+markers", name="自家消費率",
        line=dict(color="#F4D03F", width=2.5),
        marker=dict(size=7),
    ))

    if recommended_kwh > 0:
        fig.add_vline(
            x=recommended_kwh,
            line=dict(color="#E74C3C", dash="dash", width=2),
            annotation_text=f"推奨容量: {recommended_kwh:.0f} kWh",
            annotation_position="top right",
            annotation_font_color="#E74C3C",
        )

    fig.update_layout(
        title=title,
        xaxis_title="蓄電池容量 (kWh)",
        yaxis=dict(title="割合 (%)", range=[0, 100]),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def monthly_self_consumption_bar(
    sim_df: pd.DataFrame,
    title: str = "月別 自家消費率・自給率",
) -> go.Figure:
    """月別の自家消費率（発電量ベース）と自給率（需要ベース）を棒グラフで表示。"""
    monthly = sim_df.copy()
    monthly["month"] = monthly["datetime"].dt.to_period("M").dt.to_timestamp()
    monthly = monthly.groupby("month", as_index=False).agg(
        solar_kwh=("solar_kwh", "sum"),
        direct_use_kwh=("direct_use_kwh", "sum"),
        battery_discharge_kwh=("battery_discharge_kwh", "sum"),
        demand_kwh=("demand_kwh", "sum"),
    )
    monthly["solar_consumed"] = monthly["direct_use_kwh"] + monthly["battery_discharge_kwh"]
    solar_safe = monthly["solar_kwh"].replace(0, float("nan"))
    demand_safe = monthly["demand_kwh"].replace(0, float("nan"))
    monthly["自家消費率"] = (monthly["solar_consumed"] / solar_safe * 100).round(1)
    monthly["自給率"]    = (monthly["solar_consumed"] / demand_safe * 100).round(1)
    monthly["month_str"] = monthly["month"].dt.strftime("%Y-%m")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly["month_str"], y=monthly["自家消費率"],
        name="自家消費率（発電のうち自家消費した割合）",
        marker_color="#F4D03F", opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=monthly["month_str"], y=monthly["自給率"],
        name="自給率（需要のうち太陽光で賄えた割合）",
        marker_color="#5DADE2", opacity=0.85,
    ))
    fig.update_layout(
        barmode="group",
        title=title,
        xaxis_title="月",
        yaxis=dict(title="割合 (%)", range=[0, 100]),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


# ---------------------------------------------------------------------------
# 需要カーブ + 供給量オーバーレイ
# ---------------------------------------------------------------------------

SOURCE_PALETTE = [
    "#2E86AB", "#A23B72", "#F18F01", "#3BB273", "#7B2D8B",
    "#E94F37", "#44BBA4", "#E8C547",
]


def supply_timeseries(
    supply_df: pd.DataFrame,
    title: str = "発電量（30分値）",
    y_label: str = "発電量 (kWh/30min)",
) -> go.Figure:
    """
    電源別供給量の折れ線グラフ（複数電源は色分け）。
    supply_df: datetime / source_name / supply_kwh
    """
    fig = go.Figure()
    for i, src in enumerate(sorted(supply_df["source_name"].unique())):
        src_data = supply_df[supply_df["source_name"] == src].sort_values("datetime")
        fig.add_trace(go.Scatter(
            x=src_data["datetime"],
            y=src_data["supply_kwh"],
            name=src,
            line=dict(width=1.5, color=SOURCE_PALETTE[i % len(SOURCE_PALETTE)]),
            mode="lines",
            fill="tozeroy",
            opacity=0.7,
        ))
    fig.update_layout(
        title=title,
        xaxis_title="日時",
        yaxis_title=y_label,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def demand_supply_timeseries(
    demand_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    title: str = "需要 vs 供給（30分値）",
) -> go.Figure:
    """
    需要カーブ（ライン）と電源別供給量（積み上げバー）を重ね合わせる。
    demand_df: datetime / consumption_kwh[, facility_name]
    supply_df: datetime / source_name / supply_kwh
    """
    fig = go.Figure()

    # 供給: 電源別積み上げバー
    for i, src in enumerate(sorted(supply_df["source_name"].unique())):
        src_data = supply_df[supply_df["source_name"] == src].sort_values("datetime")
        fig.add_trace(go.Bar(
            x=src_data["datetime"],
            y=src_data["supply_kwh"],
            name=src,
            marker_color=SOURCE_PALETTE[i % len(SOURCE_PALETTE)],
            opacity=0.60,
        ))

    # 需要: 施設別または合計ライン
    has_facility = "facility_name" in demand_df.columns and demand_df["facility_name"].nunique() > 1
    if has_facility:
        for j, fac in enumerate(sorted(demand_df["facility_name"].unique())):
            fac_df = demand_df[demand_df["facility_name"] == fac].sort_values("datetime")
            fig.add_trace(go.Scatter(
                x=fac_df["datetime"],
                y=fac_df["consumption_kwh"],
                name=fac,
                line=dict(width=1.5, color=COLORS[j % len(COLORS)]),
                mode="lines",
            ))
    else:
        fig.add_trace(go.Scatter(
            x=demand_df.sort_values("datetime")["datetime"],
            y=demand_df.sort_values("datetime")["consumption_kwh"],
            name="総需要",
            line=dict(color="#1A1A1A", width=2),
            mode="lines",
        ))

    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis_title="日時",
        yaxis_title="電力量 (kWh/30min)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def supply_demand_balance_chart(
    balance_df: pd.DataFrame,
    source_names: list[str],
    title: str = "需給バランス（30分値）",
) -> go.Figure:
    """
    電源別供給量（積み上げバー）＋JEPX調達（不足分）＋需要（折れ線）。
    balance_df には電源名の列が展開済みであること。
    """
    fig = go.Figure()

    for i, src in enumerate(source_names):
        if src not in balance_df.columns:
            continue
        fig.add_trace(go.Bar(
            x=balance_df["datetime"],
            y=balance_df[src],
            name=src,
            marker_color=SOURCE_PALETTE[i % len(SOURCE_PALETTE)],
            opacity=0.85,
        ))

    fig.add_trace(go.Bar(
        x=balance_df["datetime"],
        y=balance_df["deficit_kwh"],
        name="JEPX調達（不足分）",
        marker_color="#FF6B6B",
        opacity=0.75,
    ))

    fig.add_trace(go.Scatter(
        x=balance_df["datetime"],
        y=balance_df["demand_kwh"],
        name="総需要",
        line=dict(color="#1A1A1A", width=2),
        mode="lines",
    ))

    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis_title="日時",
        yaxis_title="電力量 (kWh/30min)",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


# ---------------------------------------------------------------------------
# 月別P&Lチャート
# ---------------------------------------------------------------------------

def _month_labels(months: pd.Series) -> list[str]:
    """月ラベルを生成する。複数年にまたがる場合のみ年を併記して曖昧さを避ける。"""
    multi_year = months.dt.year.nunique() > 1
    if multi_year:
        return [f"{d.year}年{d.month}月" for d in months]
    return [f"{d.month}月" for d in months]


def monthly_pnl_chart(
    monthly_df: pd.DataFrame,
    title: str = "月別収支",
) -> go.Figure:
    """
    月別収支を 売上高／売上原価／売上総利益（粗利益） の3系列クラスタ棒グラフで表示する。
    売上高は小売販売収入（再エネ賦課金を除く）。売上総利益（粗利益）＝売上高－売上原価。
    """
    df = monthly_df.copy()
    df["month_str"] = _month_labels(df["month"])
    scale = 1_000  # 円 → 千円

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["month_str"], y=df["revenue"] / scale,
        name="売上高", marker_color=FS_REVENUE_COLOR,
        text=[f"{v:,.0f}" for v in df["revenue"] / scale], textposition="outside",
    ))
    fig.add_trace(go.Bar(
        x=df["month_str"], y=df["cost_of_sales"] / scale,
        name="売上原価", marker_color=FS_COST_COLOR,
        text=[f"{v:,.0f}" for v in df["cost_of_sales"] / scale], textposition="outside",
    ))
    fig.add_trace(go.Bar(
        x=df["month_str"], y=df["gross_profit"] / scale,
        name="売上総利益（粗利益）", marker_color=FS_PROFIT_COLOR,
        text=[f"{v:,.0f}" for v in df["gross_profit"] / scale], textposition="outside",
    ))

    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title=dict(text=title, font=dict(size=22, color=_FS_TITLE_COLOR)),
        xaxis=dict(tickangle=-30),
        yaxis=dict(title="千円"),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=60, b=40),
        legend=dict(title=dict(text="区分"), orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )
    return fig


def scenario_comparison_chart(
    summaries: dict[str, dict],
    title: str = "シナリオ比較（年間累計）",
) -> go.Figure:
    """シナリオ名を横軸に、売上高／売上原価／売上総利益（粗利益）を比較する。"""
    names = list(summaries.keys())
    scale = 10_000  # 円 → 万円

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=names, y=[summaries[n].get("revenue", 0) / scale for n in names],
        name="売上高", marker_color=FS_REVENUE_COLOR,
    ))
    fig.add_trace(go.Bar(
        x=names, y=[summaries[n].get("cost_of_sales", 0) / scale for n in names],
        name="売上原価", marker_color=FS_COST_COLOR,
    ))
    fig.add_trace(go.Bar(
        x=names, y=[summaries[n].get("gross_profit", 0) / scale for n in names],
        name="売上総利益（粗利益）", marker_color=FS_PROFIT_COLOR,
    ))

    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title=dict(text=title, font=dict(size=20, color=_FS_TITLE_COLOR)),
        yaxis=dict(title="万円"),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=60, b=40),
        legend=dict(title=dict(text="区分"), orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )
    return fig


# ---------------------------------------------------------------------------
# 時間帯別出力パターンチャート
# ---------------------------------------------------------------------------

def hourly_pattern_bar(
    hourly_pct: list[float],
    source_name: str = "電源",
) -> go.Figure:
    """24時間の出力比率を棒グラフで表示。"""
    hours = [f"{h:02d}:00" for h in range(24)]
    fig = go.Figure(go.Bar(
        x=hours,
        y=hourly_pct,
        marker_color="#2E86AB",
        opacity=0.8,
    ))
    fig.update_layout(
        title=f"{source_name}：時間帯別出力比（%）",
        xaxis_title="時間帯",
        yaxis=dict(title="出力比 (%)", range=[0, 110]),
        margin=dict(l=20, r=20, t=50, b=20),
        height=220,
    )
    return fig
