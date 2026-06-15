"""
data_loader.py
Excelまたは CSV ファイルを読み込み、標準形式の DataFrame に変換する。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd

STANDARD_COLUMNS = {
    "datetime": "datetime",
    "facility_name": "facility_name",
    "consumption_kwh": "consumption_kwh",
}

# よくある列名のエイリアスマッピング（大文字小文字を正規化して照合）
DEFAULT_ALIAS_MAP: dict[str, list[str]] = {
    "datetime": [
        "日時", "datetime", "date_time", "timestamp", "time", "時刻", "年月日時刻",
        "date", "日付", "取得時刻",
    ],
    "facility_name": [
        "施設名", "facility_name", "facility", "name", "施設", "建物名", "site",
    ],
    "consumption_kwh": [
        "消費電力量(kwh)", "使用電力量", "consumption_kwh", "kwh", "電力量",
        "使用量", "消費量", "電力使用量", "demand_kwh", "energy_kwh",
        "電力量(kwh)", "使用電力量(kwh)",
    ],
}


def _normalize(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("　", "")


def _detect_column_mapping(
    columns: list[str],
    alias_map: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """DataFrame の列名 → 標準列名 のマッピングを推測して返す。"""
    alias_map = alias_map or DEFAULT_ALIAS_MAP
    mapping: dict[str, str] = {}
    normalized_cols = {_normalize(c): c for c in columns}

    for std_col, aliases in alias_map.items():
        for alias in aliases:
            key = _normalize(alias)
            if key in normalized_cols:
                mapping[normalized_cols[key]] = std_col
                break

    return mapping


def load_file(
    source: str | Path | io.BytesIO,
    sheet_name: int | str = 0,
    column_mapping: dict[str, str] | None = None,
    encoding: str = "utf-8",
) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Excel または CSV を読み込んで標準 DataFrame を返す。

    Returns
    -------
    df : 標準化された DataFrame（datetime, facility_name, consumption_kwh）
    applied_mapping : 実際に適用した列マッピング {元の列名: 標準列名}
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        suffix = path.suffix.lower()
    else:
        suffix = ".xlsx"  # BytesIO はデフォルト Excel 扱い

    if suffix in {".xlsx", ".xls"}:
        raw = pd.read_excel(source, sheet_name=sheet_name, dtype=str)
    elif suffix == ".csv":
        try:
            raw = pd.read_csv(source, dtype=str, encoding=encoding)
        except UnicodeDecodeError:
            if hasattr(source, "seek"):
                source.seek(0)
            raw = pd.read_csv(source, dtype=str, encoding="shift-jis")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    raw.columns = [str(c).strip() for c in raw.columns]

    applied_mapping = column_mapping or _detect_column_mapping(list(raw.columns))

    df = raw.rename(columns=applied_mapping)

    # 標準列がそろっているか確認
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        return df, applied_mapping  # 呼び出し元でマッピング補正できるよう生データを返す

    df = _parse_standard(df)
    return df, applied_mapping


def _parse_standard(df: pd.DataFrame) -> pd.DataFrame:
    """型変換・不要列の除去を行う。"""
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df["consumption_kwh"] = pd.to_numeric(df["consumption_kwh"], errors="coerce")
    df["facility_name"] = df["facility_name"].astype(str).str.strip()
    return df[["datetime", "facility_name", "consumption_kwh"]]


def merge_multiple_files(
    sources: list[Any],
    sheet_name: int | str = 0,
    column_mappings: list[dict[str, str]] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """
    複数ファイルを読み込んで縦結合する。
    Returns merged DataFrame と各ファイルの applied_mapping リスト。
    """
    dfs: list[pd.DataFrame] = []
    mappings: list[dict[str, str]] = []

    for i, src in enumerate(sources):
        col_map = column_mappings[i] if column_mappings else None
        df, applied = load_file(src, sheet_name=sheet_name, column_mapping=col_map)
        dfs.append(df)
        mappings.append(applied)

    if not dfs:
        return pd.DataFrame(columns=list(STANDARD_COLUMNS)), []

    merged = pd.concat(dfs, ignore_index=True)
    return merged, mappings


def get_column_suggestions(df: pd.DataFrame) -> dict[str, list[str]]:
    """
    列が自動マッピングできなかった場合に、候補一覧を返す（UI 上のセレクトボックス用）。
    """
    return {
        "datetime": list(df.columns),
        "facility_name": list(df.columns),
        "consumption_kwh": list(df.columns),
    }
