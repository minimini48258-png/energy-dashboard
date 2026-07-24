"""
jepx_loader.py
JEPX（日本卸電力取引所）スポット市場の実績価格ファイルを読み込み、
標準価格 DataFrame（datetime / jepx_price_yen）に変換する。

対応フォーマット:
  A) JEPX公式CSV「スポット取引結果」形式:
     受渡日 / 時刻コード(1〜48) / システムプライス(円/kWh) / エリアプライス中部(円/kWh) 等
  B) 汎用形式: datetime 列 + price 系の列（列名は自動マッピング）
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd

_DATE_ALIASES = ["受渡日", "年月日", "日付", "date"]
_TIMECODE_ALIASES = ["時刻コード", "コマ", "time_code", "slot"]
_TIME_ALIASES = ["時刻", "time", "時間"]
_PRICE_ALIASES = [
    "jepx_price_yen", "jepx_price", "price", "単価",
    "システムプライス(円/kwh)", "システムプライス",
]
# エリアプライス列（中部電力管内なので「中部」を優先的に探す）
_AREA_PRICE_CANDIDATES = ["エリアプライス中部(円/kwh)", "エリアプライス中部", "中部エリアプライス"]


def _normalize(s: str) -> str:
    return str(s).strip().lower().replace(" ", "").replace("　", "").replace("_", "")


def _find_col(columns: list[str], aliases: list[str]) -> str | None:
    norm_map = {_normalize(c): c for c in columns}
    for alias in aliases:
        if _normalize(alias) in norm_map:
            return norm_map[_normalize(alias)]
    return None


def _read_table(source: Any) -> pd.DataFrame:
    """CSV / Excel を判定して読み込む（JEPX公式CSVはShift-JISのことが多いため両対応）。"""
    is_bytes = isinstance(source, io.BytesIO)
    filename = getattr(source, "name", "") if not isinstance(source, (str, Path)) else str(source)
    is_csv = str(filename).lower().endswith(".csv") or is_bytes

    if is_bytes:
        source.seek(0)
    if str(filename).lower().endswith(".xlsx") or str(filename).lower().endswith(".xls"):
        return pd.read_excel(source, dtype=str)

    # CSV として読み込む（エンコーディングを順に試す）
    raw = source.read() if is_bytes else Path(source).read_bytes()
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, encoding=enc)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError("CSVファイルの読み込みに失敗しました。文字コードを確認してください。")


def _load_official_format(df: pd.DataFrame) -> pd.DataFrame:
    """JEPX公式CSV形式（受渡日 + 時刻コード + エリア/システムプライス）を解析。"""
    cols = list(df.columns)
    date_col = _find_col(cols, _DATE_ALIASES)
    code_col = _find_col(cols, _TIMECODE_ALIASES)
    if date_col is None or code_col is None:
        raise ValueError("受渡日／時刻コード列が見つかりません。")

    price_col = _find_col(cols, _AREA_PRICE_CANDIDATES) or _find_col(cols, _PRICE_ALIASES)
    if price_col is None:
        raise ValueError("価格列（エリアプライス中部 または システムプライス）が見つかりません。")

    code = pd.to_numeric(df[code_col], errors="coerce")
    minutes_from_midnight = (code - 1).clip(lower=0) * 30
    date_part = pd.to_datetime(df[date_col], errors="coerce")
    dt = date_part + pd.to_timedelta(minutes_from_midnight, unit="m")

    price = pd.to_numeric(df[price_col], errors="coerce")
    result = pd.DataFrame({"datetime": dt, "jepx_price_yen": price})
    return result.dropna(subset=["datetime", "jepx_price_yen"]).sort_values("datetime").reset_index(drop=True)


def _load_generic_format(df: pd.DataFrame) -> pd.DataFrame:
    """汎用形式（datetime列 + price列、または 年月日+時刻 + price列）を解析。"""
    cols = list(df.columns)
    date_col = _find_col(cols, _DATE_ALIASES + ["datetime"])
    time_col = _find_col(cols, _TIME_ALIASES)
    price_col = _find_col(cols, _PRICE_ALIASES)

    if date_col is None or price_col is None:
        raise ValueError("日時列または価格列が見つかりません。")

    if time_col:
        dt = pd.to_datetime(
            df[date_col].astype(str).str[:10] + " " + df[time_col].astype(str).str.strip(),
            errors="coerce",
        )
    else:
        dt = pd.to_datetime(df[date_col], errors="coerce")

    price = pd.to_numeric(df[price_col], errors="coerce")
    result = pd.DataFrame({"datetime": dt, "jepx_price_yen": price})
    return result.dropna(subset=["datetime", "jepx_price_yen"]).sort_values("datetime").reset_index(drop=True)


def load_jepx_price_file(
    source: str | Path | io.BytesIO,
    filename: str | None = None,
) -> pd.DataFrame:
    """
    JEPX実績価格ファイルを読み込み、datetime / jepx_price_yen の DataFrame を返す。
    30分値（受渡日+時刻コード）または datetime+price の汎用形式に対応。
    """
    if filename and not getattr(source, "name", None):
        try:
            source.name = filename  # type: ignore[attr-defined]
        except Exception:
            pass

    df_raw = _read_table(source)
    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    cols = list(df_raw.columns)
    if _find_col(cols, _TIMECODE_ALIASES) is not None:
        return _load_official_format(df_raw)
    return _load_generic_format(df_raw)


def price_series_for_period(jepx_df: pd.DataFrame, timestamps: pd.DatetimeIndex) -> pd.Series:
    """アップロード済みJEPX実績価格を、対象期間のタイムスタンプに合わせたSeriesとして返す。"""
    s = jepx_df.set_index("datetime")["jepx_price_yen"]
    return s.reindex(timestamps)
