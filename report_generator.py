"""
report_generator.py
シミュレーション結果を Excel レポート（bytes）に変換する。
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd


def build_excel_report(
    sim_df: pd.DataFrame,
    kpis: dict,
    solar_kw: float,
    battery_kwh: float,
    battery_eff: float,
    mode_label: str,
    analysis_period: str,
) -> bytes:
    """
    シミュレーション結果を Excel ファイルに変換して bytes で返す。

    Sheets
    ------
    1. サマリー   — 導入設定・KPI まとめ
    2. 月別集計   — 月ごとの発電・消費・充放電・売電量と自家消費率
    3. 30分値データ — シミュレーション全行
    """
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:

        # ── Sheet 1: サマリー ────────────────────────────────────────────────
        period_start = sim_df["datetime"].min().strftime("%Y/%m/%d")
        period_end   = sim_df["datetime"].max().strftime("%Y/%m/%d")
        summary_rows = [
            ["■ シミュレーション設定", ""],
            ["レポート作成日時",   datetime.now().strftime("%Y-%m-%d %H:%M")],
            ["分析期間",          f"{period_start} 〜 {period_end}  （{analysis_period}）"],
            ["太陽光容量 (kWp)",   solar_kw],
            ["蓄電池容量 (kWh)",   battery_kwh],
            ["充放電往復効率 (%)", round(battery_eff * 100, 1)],
            ["充放電モード",       mode_label],
            ["", ""],
            ["■ シミュレーション結果 KPI", ""],
            ["自家消費率 (%)",              kpis["self_consumption_rate"]],
            ["自給率 (%)",                  kpis["self_sufficiency_rate"]],
            ["太陽光発電量合計 (kWh)",      kpis["total_solar_kwh"]],
            ["需要量合計 (kWh)",            kpis["total_demand_kwh"]],
            ["太陽光直接消費量 (kWh)",      kpis["total_direct_kwh"]],
            ["蓄電池放電量 (kWh)",          kpis["total_discharge_kwh"]],
            ["蓄電池充電量 (kWh)",          kpis["total_charge_kwh"]],
            ["グリッド買電削減量 (kWh)",    kpis["grid_reduction_kwh"]],
            ["グリッド買電削減率 (%)",      kpis["grid_reduction_rate"]],
            ["系統への売電量 (kWh)",        kpis["total_grid_export_kwh"]],
        ]
        df_summary = pd.DataFrame(summary_rows, columns=["項目", "値"])
        df_summary.to_excel(writer, sheet_name="サマリー", index=False)

        ws = writer.sheets["サマリー"]
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 28
        _bold_rows = [1, 9]  # セクション見出し行（1-indexed + header = +2）
        from openpyxl.styles import Font
        for r_offset in _bold_rows:
            ws.cell(row=r_offset + 1, column=1).font = Font(bold=True)

        # ── Sheet 2: 月別集計 ────────────────────────────────────────────────
        monthly = sim_df.copy()
        monthly["月"] = monthly["datetime"].dt.to_period("M").dt.to_timestamp()
        monthly_agg = (
            monthly.groupby("月")
            .agg(
                発電量_kWh=("solar_kwh", "sum"),
                需要量_kWh=("demand_kwh", "sum"),
                直接消費量_kWh=("direct_use_kwh", "sum"),
                蓄電池充電量_kWh=("battery_charge_kwh", "sum"),
                蓄電池放電量_kWh=("battery_discharge_kwh", "sum"),
                グリッド買電量_kWh=("grid_import_kwh", "sum"),
                売電量_kWh=("grid_export_kwh", "sum"),
            )
            .reset_index()
        )
        monthly_agg["月"] = monthly_agg["月"].dt.strftime("%Y-%m")

        solar_safe  = monthly_agg["発電量_kWh"].replace(0, float("nan"))
        demand_safe = monthly_agg["需要量_kWh"].replace(0, float("nan"))
        consumed    = monthly_agg["直接消費量_kWh"] + monthly_agg["蓄電池放電量_kWh"]
        monthly_agg["自家消費率_%"] = (consumed / solar_safe  * 100).round(1)
        monthly_agg["自給率_%"]     = (consumed / demand_safe * 100).round(1)

        # 数値列を丸める
        num_cols = [c for c in monthly_agg.columns if c.endswith("_kWh")]
        monthly_agg[num_cols] = monthly_agg[num_cols].round(1)

        monthly_agg.to_excel(writer, sheet_name="月別集計", index=False)
        ws2 = writer.sheets["月別集計"]
        for col in ws2.columns:
            ws2.column_dimensions[col[0].column_letter].width = 20

        # ── Sheet 3: 30分値データ ─────────────────────────────────────────────
        col_map = {
            "datetime":             "日時",
            "demand_kwh":           "需要量_kWh",
            "solar_kwh":            "発電量_kWh",
            "direct_use_kwh":       "直接消費量_kWh",
            "battery_charge_kwh":   "蓄電池充電量_kWh",
            "battery_discharge_kwh":"蓄電池放電量_kWh",
            "battery_soc_kwh":      "蓄電池残量_kWh",
            "grid_import_kwh":      "グリッド買電量_kWh",
            "grid_export_kwh":      "売電量_kWh",
        }
        df_raw = sim_df[list(col_map)].rename(columns=col_map).copy()
        num_raw = [c for c in df_raw.columns if c.endswith("_kWh")]
        df_raw[num_raw] = df_raw[num_raw].round(3)
        df_raw.to_excel(writer, sheet_name="30分値データ", index=False)
        ws3 = writer.sheets["30分値データ"]
        ws3.column_dimensions["A"].width = 20
        for col in list(ws3.columns)[1:]:
            ws3.column_dimensions[col[0].column_letter].width = 18

    return buf.getvalue()
