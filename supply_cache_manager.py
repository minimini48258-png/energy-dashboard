"""
supply_cache_manager.py
供給側 DataFrame をローカルの parquet ファイルに保存・復元する。
cache_manager.py の供給データ版。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SUPPLY_CACHE_DIR = Path("/tmp/energy_dashboard/supply_cache")
MAX_ENTRIES = 5


def _ensure() -> None:
    SUPPLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save(df: pd.DataFrame, filenames: list[str]) -> str:
    """供給 DataFrame を保存してキャッシュIDを返す。"""
    _ensure()
    cache_id = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    df.to_parquet(SUPPLY_CACHE_DIR / f"{cache_id}.parquet", index=False)
    meta = {
        "cache_id": cache_id,
        "filenames": filenames,
        "saved_at": pd.Timestamp.now().isoformat(),
        "rows": len(df),
        "source_names": sorted(df["source_name"].unique().tolist()),
        "date_min": df["datetime"].min().date().isoformat(),
        "date_max": df["datetime"].max().date().isoformat(),
    }
    (SUPPLY_CACHE_DIR / f"{cache_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    entries = sorted(SUPPLY_CACHE_DIR.glob("*.json"))
    for old in entries[:-MAX_ENTRIES]:
        old.unlink(missing_ok=True)
        old.with_suffix(".parquet").unlink(missing_ok=True)
    return cache_id


def list_entries() -> list[dict]:
    """保存済みキャッシュのメタデータ一覧（新しい順）を返す。"""
    _ensure()
    result = []
    for p in sorted(SUPPLY_CACHE_DIR.glob("*.json"), reverse=True):
        try:
            result.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result


def load(cache_id: str) -> pd.DataFrame:
    """キャッシュIDに対応する DataFrame を返す。"""
    return pd.read_parquet(SUPPLY_CACHE_DIR / f"{cache_id}.parquet")


def delete(cache_id: str) -> None:
    (SUPPLY_CACHE_DIR / f"{cache_id}.parquet").unlink(missing_ok=True)
    (SUPPLY_CACHE_DIR / f"{cache_id}.json").unlink(missing_ok=True)
