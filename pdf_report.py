"""
pdf_report.py
シミュレーション結果を印刷対応 HTML レポートに変換する。
ブラウザで開いて Ctrl+P（⌘P）→「PDF として保存」でそのまま PDF 出力可能。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# ---------------------------------------------------------------------------
# スタイルシート
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont,
                 'Hiragino Kaku Gothic Pro', 'Hiragino Sans',
                 'YuGothic', 'Yu Gothic', 'Meiryo', sans-serif;
    font-size: 13px;
    color: #1a1a2e;
    background: #ffffff;
    padding: 28px 36px;
    max-width: 960px;
    margin: 0 auto;
}

/* ── ヘッダー ── */
.report-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 14px;
    margin-bottom: 22px;
    border-bottom: 4px solid #F4D03F;
}
.report-header h1 {
    font-size: 21px;
    font-weight: 800;
    letter-spacing: -0.3px;
    margin-bottom: 4px;
}
.report-header .sub {
    font-size: 12px;
    color: #666;
    line-height: 1.7;
}
.report-header .meta {
    text-align: right;
    font-size: 11px;
    color: #888;
    line-height: 1.8;
}

/* ── セクション見出し ── */
h2 {
    font-size: 14px;
    font-weight: 700;
    color: #444;
    margin: 24px 0 10px;
    padding-left: 10px;
    border-left: 4px solid #F4D03F;
}

/* ── 導入設定グリッド ── */
.settings-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 4px;
}
.setting-card {
    background: #f7f8fa;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: center;
}
.setting-label { font-size: 11px; color: #888; margin-bottom: 5px; }
.setting-value { font-size: 18px; font-weight: 800; color: #1a1a2e; }
.setting-unit  { font-size: 11px; font-weight: 400; color: #555; margin-left: 2px; }

/* ── KPI グリッド ── */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 4px;
}
.kpi-card {
    border: 1.5px solid #e8eaed;
    border-radius: 10px;
    padding: 14px 16px;
    text-align: center;
}
.kpi-label { font-size: 11px; color: #888; margin-bottom: 6px; }
.kpi-value {
    font-size: 28px;
    font-weight: 800;
    color: #1a1a2e;
    line-height: 1;
}
.kpi-unit  { font-size: 12px; color: #888; margin-top: 4px; }

/* ── チャート ── */
.chart-section {
    margin: 28px 0 0;
}
.chart-title {
    font-size: 13px;
    font-weight: 600;
    color: #555;
    margin-bottom: 6px;
}

/* ── 印刷ボタン ── */
.print-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 20px;
    padding: 9px 24px;
    background: #1a1a2e;
    color: #F4D03F;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    letter-spacing: 0.3px;
}
.print-btn:hover { background: #2c2c4e; }
.print-hint {
    display: inline-block;
    margin-left: 12px;
    font-size: 11px;
    color: #999;
}

/* ── フッター ── */
.report-footer {
    margin-top: 32px;
    padding-top: 12px;
    border-top: 1px solid #eee;
    font-size: 11px;
    color: #bbb;
    text-align: center;
}

/* ── 印刷スタイル ── */
@media print {
    body { padding: 0; font-size: 12px; max-width: 100%; }
    .no-print { display: none !important; }
    h2 { margin: 16px 0 8px; }
    .kpi-grid  { grid-template-columns: repeat(3, 1fr); }
    .settings-grid { grid-template-columns: repeat(4, 1fr); }
    .chart-section { page-break-before: always; }
    @page {
        size: A4 portrait;
        margin: 14mm 16mm 14mm 16mm;
    }
}
"""

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _fmt_kwh(v: float) -> tuple[str, str]:
    """(値文字列, 単位) を返す。"""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}", "MWh"
    if v >= 1_000:
        return f"{v / 1_000:.1f}", "MWh"
    return f"{v:.1f}", "kWh"


def _chart_div(fig: go.Figure, include_js: bool, height: int = 400) -> str:
    """Plotly 図を HTML div 文字列に変換する（レポート用レイアウト調整済み）。"""
    report_fig = go.Figure(fig)
    report_fig.update_layout(
        height=height,
        margin=dict(l=48, r=24, t=48, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return pio.to_html(
        report_fig,
        include_plotlyjs=include_js,
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------

def build_html_report(
    sim_df: pd.DataFrame,
    kpis: dict,
    figures: list[tuple[go.Figure, str]],
    solar_kw: float,
    battery_kwh: float,
    battery_eff: float,
    mode_label: str,
    analysis_period: str,
) -> bytes:
    """
    シミュレーション結果をブラウザ印刷対応の HTML レポートに変換して bytes で返す。

    Parameters
    ----------
    figures : [(go.Figure, チャートタイトル), ...] のリスト
    """
    period_start = sim_df["datetime"].min().strftime("%Y/%m/%d")
    period_end   = sim_df["datetime"].max().strftime("%Y/%m/%d")
    today        = datetime.now().strftime("%Y年%m月%d日 %H:%M 作成")

    # ── 導入設定 ─────────────────────────────────────────────────────────────
    settings_html = f"""
<div class="settings-grid">
  <div class="setting-card">
    <div class="setting-label">太陽光容量</div>
    <div class="setting-value">{solar_kw:.0f}<span class="setting-unit">kWp</span></div>
  </div>
  <div class="setting-card">
    <div class="setting-label">蓄電池容量</div>
    <div class="setting-value">{battery_kwh:.0f}<span class="setting-unit">kWh</span></div>
  </div>
  <div class="setting-card">
    <div class="setting-label">充放電往復効率</div>
    <div class="setting-value">{battery_eff * 100:.0f}<span class="setting-unit">%</span></div>
  </div>
  <div class="setting-card">
    <div class="setting-label">充放電モード</div>
    <div class="setting-value" style="font-size:14px;line-height:1.3">{mode_label}</div>
  </div>
</div>"""

    # ── KPI ──────────────────────────────────────────────────────────────────
    scr_val, scr_unit = f"{kpis['self_consumption_rate']:.1f}", "%"
    ssr_val, ssr_unit = f"{kpis['self_sufficiency_rate']:.1f}", "%"
    sol_val, sol_unit = _fmt_kwh(kpis["total_solar_kwh"])
    red_val, red_unit = _fmt_kwh(kpis["grid_reduction_kwh"])
    rrt_val, rrt_unit = f"{kpis['grid_reduction_rate']:.1f}", "%"
    exp_val, exp_unit = _fmt_kwh(kpis["total_grid_export_kwh"])

    kpi_html = f"""
<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-label">自家消費率</div>
    <div class="kpi-value">{scr_val}</div>
    <div class="kpi-unit">{scr_unit}　発電量のうち自家消費した割合</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">自給率</div>
    <div class="kpi-value">{ssr_val}</div>
    <div class="kpi-unit">{ssr_unit}　需要のうち太陽光＋蓄電池で賄えた割合</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">発電量合計</div>
    <div class="kpi-value">{sol_val}</div>
    <div class="kpi-unit">{sol_unit}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">グリッド買電削減量</div>
    <div class="kpi-value">{red_val}</div>
    <div class="kpi-unit">{red_unit}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">グリッド買電削減率</div>
    <div class="kpi-value">{rrt_val}</div>
    <div class="kpi-unit">{rrt_unit}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">系統への売電量</div>
    <div class="kpi-value">{exp_val}</div>
    <div class="kpi-unit">{exp_unit}</div>
  </div>
</div>"""

    # ── チャート ─────────────────────────────────────────────────────────────
    chart_parts: list[str] = []
    for i, (fig, title) in enumerate(figures):
        div = _chart_div(fig, include_js=(i == 0))
        chart_parts.append(f"""
<div class="chart-section">
  <div class="chart-title">{title}</div>
  {div}
</div>""")

    charts_html = "\n".join(chart_parts)

    # ── 組み立て ──────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PPAシミュレーションレポート</title>
<style>{_CSS}</style>
</head>
<body>

<div class="report-header">
  <div>
    <h1>⚡ PPAシミュレーションレポート</h1>
    <div class="sub">
      分析期間: {period_start} 〜 {period_end}　｜　{analysis_period}<br>
      日射量モデル: 上田市（NEDO 概算値）
    </div>
  </div>
  <div class="meta">{today}</div>
</div>

<div class="no-print">
  <button class="print-btn" onclick="window.print()">🖨️ 印刷してPDF保存</button>
  <span class="print-hint">Ctrl+P（Mac: ⌘P）→「PDF として保存」でも出力できます</span>
</div>

<h2>導入設定</h2>
{settings_html}

<h2>シミュレーション結果 KPI</h2>
{kpi_html}

{charts_html}

<div class="report-footer no-print">
  このレポートは上田市民エネルギー 電力需給分析ダッシュボードで生成されました
</div>

</body>
</html>"""

    return html.encode("utf-8")
