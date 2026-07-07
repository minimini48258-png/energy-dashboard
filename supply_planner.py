"""
supply_planner.py
供給電源の定義・プロファイル生成を管理する。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

SOURCES_FILE = Path("/tmp/energy_dashboard/supply_sources.json")

HOURLY_PRESETS: dict[str, list[float]] = {
    "常時稼働": [100.0] * 24,
    "昼間のみ（6〜18時）": [0.0] * 6 + [100.0] * 12 + [0.0] * 6,
    "朝夕ピーク（6〜9時・17〜22時）": (
        [0.0] * 6 + [100.0] * 3 + [0.0] * 8 + [100.0] * 5 + [0.0] * 2
    ),
}

SOURCE_TYPE_LABELS = {
    "hydro": "水力",
    "solar": "太陽光",
    "biomass": "バイオマス",
    "other": "その他",
}
SOURCE_TYPE_KEYS = {v: k for k, v in SOURCE_TYPE_LABELS.items()}


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
    ).values

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
