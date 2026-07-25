"""
supply_planner.py
供給電源の定義・プロファイル生成を管理する。
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

SOURCES_FILE = Path("/tmp/energy_dashboard/supply_sources.json")


def _solar_bell_curve(sunrise: int = 6, sunset: int = 18) -> list[float]:
    """晴天日を想定した太陽光の時間帯別出力比（%）。日の出〜日の入りを正弦波で近似。"""
    daylight_h = sunset - sunrise
    curve = [0.0] * 24
    for h in range(sunrise, sunset):
        progress = (h + 0.5 - sunrise) / daylight_h
        curve[h] = round(100.0 * math.sin(math.pi * progress), 1)
    return curve


HOURLY_PRESETS: dict[str, list[float]] = {
    "常時稼働": [100.0] * 24,
    "昼間のみ（6〜18時）": [0.0] * 6 + [100.0] * 12 + [0.0] * 6,
    "朝夕ピーク（6〜9時・17〜22時）": (
        [0.0] * 6 + [100.0] * 3 + [0.0] * 8 + [100.0] * 5 + [0.0] * 2
    ),
    "太陽光（晴天日カーブ・6〜18時）": _solar_bell_curve(6, 18),
    "小水力（終日安定出力）": [100.0] * 24,
    "バイオマス（終日安定出力）": [100.0] * 24,
}

SOURCE_TYPE_LABELS = {
    "hydro": "水力",
    "solar": "太陽光",
    "biomass": "バイオマス",
    "bilateral": "相対電源",
    "other": "その他",
}
SOURCE_TYPE_KEYS = {v: k for k, v in SOURCE_TYPE_LABELS.items()}

# 電源種別ごとに初期選択する時間帯プリセット
DEFAULT_HOURLY_PRESET_BY_TYPE: dict[str, str] = {
    "solar": "太陽光（晴天日カーブ・6〜18時）",
    "hydro": "小水力（終日安定出力）",
    "biomass": "バイオマス（終日安定出力）",
    "bilateral": "常時稼働",
    "other": "常時稼働",
}

# 電源種別ごとの月別稼働率の目安値（%）※要確認・一般的な傾向に基づく目安であり実績値ではない
DEFAULT_MONTHLY_UTILIZATION_BY_TYPE: dict[str, list[float]] = {
    # 太陽光: 夏季高め・冬季低め（日照時間・積雪の影響）
    "solar":    [55.0, 65.0, 75.0, 85.0, 90.0, 85.0, 90.0, 90.0, 80.0, 70.0, 60.0, 50.0],
    # 小水力: 融雪期（春）に高く、渇水期（冬）に低い
    "hydro":    [65.0, 70.0, 90.0, 95.0, 85.0, 75.0, 70.0, 65.0, 65.0, 70.0, 70.0, 65.0],
    # バイオマス: 燃料供給が安定していれば年間を通じほぼ一定（定期点検分を差し引いた目安）
    "biomass":  [85.0] * 12,
    "bilateral": [80.0] * 12,
    "other":    [80.0] * 12,
}


@dataclass
class SupplySource:
    name: str
    source_type: str          # "hydro" | "solar" | "biomass" | "other"
    capacity_kw: float
    monthly_utilization_pct: list[float] = field(
        default_factory=lambda: [80.0] * 12
    )
    hourly_pattern_pct: list[float] = field(
        default_factory=lambda: [100.0] * 24
    )
    cost_per_kwh: float = 8.0
    start_date: Optional[str] = None  # "YYYY-MM-DD"


def generate_supply_profile(
    source: SupplySource,
    timestamps: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    タイムスタンプ列に対して 30 分値の供給量(kWh)を生成する。
    output_kWh = capacity_kW × monthly_factor × hourly_factor × 0.5
    """
    ts_series = pd.Series(timestamps)
    months = ts_series.dt.month.values - 1   # 0-11
    hours  = ts_series.dt.hour.values         # 0-23

    monthly_factors = [source.monthly_utilization_pct[m] / 100.0 for m in months]
    hourly_factors  = [source.hourly_pattern_pct[h] / 100.0 for h in hours]

    supply_kwh = (
        source.capacity_kw
        * pd.Series(monthly_factors, dtype=float)
        * pd.Series(hourly_factors, dtype=float)
        * 0.5   # kW → kWh (30分)
    ).to_numpy(copy=True)  # pandasのCopy-on-Write下では .values が読み取り専用になり得るため明示的にコピーする

    # 運転開始日より前はゼロ
    if source.start_date:
        start_ts = pd.Timestamp(source.start_date)
        mask = timestamps < start_ts
        supply_kwh[mask] = 0.0

    return pd.DataFrame({
        "datetime":   timestamps,
        "source_name": source.name,
        "supply_kwh":  supply_kwh,
    })


def combine_supply_profiles(
    sources: list[SupplySource],
    timestamps: pd.DatetimeIndex,
) -> pd.DataFrame:
    """全電源の供給プロファイルを縦方向に結合（datetime, source_name, supply_kwh）。"""
    if not sources:
        return pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"])
    return pd.concat(
        [generate_supply_profile(s, timestamps) for s in sources],
        ignore_index=True,
    )


def apply_procurement_ratios(
    supply_df: pd.DataFrame,
    ratios_pct: dict[str, float],
) -> pd.DataFrame:
    """
    電源ごとの調達比率（%）を supply_kwh に乗じる。
    未指定の電源は100%（そのまま）として扱う。
    """
    if supply_df.empty or not ratios_pct:
        return supply_df
    df = supply_df.copy()
    df["supply_kwh"] = df["supply_kwh"] * (
        df["source_name"].map(ratios_pct).fillna(100.0) / 100.0
    )
    return df


def save_sources(sources: list[SupplySource]) -> None:
    SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(
        json.dumps([asdict(s) for s in sources], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_sources() -> list[SupplySource]:
    if not SOURCES_FILE.exists():
        return []
    try:
        return [SupplySource(**d) for d in json.loads(SOURCES_FILE.read_text("utf-8"))]
    except Exception:
        return []
