"""
supply_loader.py
供給側 Excel ファイルを読み込み、標準供給 DataFrame（datetime / source_name / supply_kwh）に変換する。

対応フォーマット:
  A) 長形式シート「30分値_長形式」: 年月日 / 時刻 / 供給電力量_kWh
  B) 横展開シート「30分値_日別ワイド形式」: 年月日 / 発電所名 / 0:00～0:30 ...
  C) 汎用長形式: datetime/supply 系の列を自動マッピング
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd

# 長形式シートの列エイリアス
_DATETIME_ALIASES = ["年月日", "日時", "datetime", "date", "日付"]
_TIME_ALIASES     = ["時刻", "time", "時間"]
_SUPPLY_KWH_ALIASES = [
    "供給電力量_kWh", "供給電力量(kwh)", "発電電力量_kWh", "発電電力量(kwh)",
    "supply_kwh", "generation_kwh", "kwh", "電力量(kwh)",
]
_SUPPLY_KW_ALIASES = [
    "出力_kW", "出力(kw)", "発電出力_kW", "発電出力(kw)",
    "supply_kw", "generation_kw", "kw",
]

_LONG_SHEET_NAMES  = ["30分値_長形式", "長形式", "30min_long"]
_WIDE_SHEET_NAMES  = ["30分値_日別ワイド形式", "ワイド形式", "30min_wide"]


# ---------------------------------------------------------------------------
# ファイル名から電源名を抽出
# ---------------------------------------------------------------------------

def _source_name_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d{8}_", "", stem)          # 日付プレフィックス除去
    stem = re.sub(r"_30分値.*$", "", stem)         # 後ろのサフィックス除去
    stem = re.sub(r"_供給.*$", "", stem)
    stem = re.sub(r"_発電.*$", "", stem)
    stem = re.sub(r"（[^）]*）", "", stem)          # （）内を除去
    return stem.strip("_　 ") or Path(filename).stem


# ---------------------------------------------------------------------------
# 長形式パーサー
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return str(s).strip().lower().replace(" ", "").replace("　", "").replace("_", "")


def _find_col(columns: list[str], aliases: list[str]) -> str | None:
    norm_map = {_normalize(c): c for c in columns}
    for alias in aliases:
        if _normalize(alias) in norm_map:
            return norm_map[_normalize(alias)]
    return None


def _load_long_form(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """年月日 + 時刻 の組み合わせ、または単一datetime列 から供給DFを構築。"""
    cols = list(df.columns)

    date_col   = _find_col(cols, _DATETIME_ALIASES)
    time_col   = _find_col(cols, _TIME_ALIASES)
    supply_col = _find_col(cols, _SUPPLY_KWH_ALIASES)
    kw_col     = _find_col(cols, _SUPPLY_KW_ALIASES)

    if date_col is None:
        raise ValueError("日時列が見つかりません。")

    # datetime 構築
    if time_col and df[date_col].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}").any():
        # "YYYY-MM-DD" + "HH:MM" 形式
        dt = pd.to_datetime(
            df[date_col].astype(str).str[:10] + " " + df[time_col].astype(str).str.strip(),
            errors="coerce",
        )
    elif time_col and df[date_col].astype(str).str.match(r"^\d{8}").any():
        # "YYYYMMDD" + "HH:MM" 形式
        dt = pd.to_datetime(
            df[date_col].astype(str).str[:8] + " " + df[time_col].astype(str).str.strip(),
            format="%Y%m%d %H:%M",
            errors="coerce",
        )
    else:
        dt = pd.to_datetime(df[date_col], errors="coerce")

    # supply_kwh 決定
    if supply_col:
        kwh = pd.to_numeric(df[supply_col], errors="coerce")
    elif kw_col:
        kwh = pd.to_numeric(df[kw_col], errors="coerce") * 0.5  # kW → kWh(30分)
    else:
        raise ValueError("供給電力量列（kWh または kW）が見つかりません。")

    result = pd.DataFrame({
        "datetime":    dt,
        "source_name": source_name,
        "supply_kwh":  kwh,
    })
    return result.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 横展開パーサー（日別ワイド形式）
# ---------------------------------------------------------------------------

def _is_30min_slot(col: str) -> bool:
    m = re.match(r"^(\d+):(\d+).+(\d+):(\d+)$", str(col).strip())
    if not m:
        return False
    h1, m1, h2, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    end_mins = (24 if h2 == 24 else h2) * 60 + m2
    return (end_mins - h1 * 60 - m1) == 30


def _load_wide_supply(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """横展開（1日1行×48列）→ 長形式に変換。"""
    cols = list(df.columns)
    date_col = _find_col(cols, _DATETIME_ALIASES)
    if not date_col:
        raise ValueError("日付列が見つかりません。")

    half_hour_cols = [c for c in cols if _is_30min_slot(c)]
    if not half_hour_cols:
        raise ValueError("30分値列が見つかりません。")

    # 年月日が有効な行だけ残す
    date_str = df[date_col].astype(str).str.strip()
    valid_mask = (
        date_str.str.match(r"^\d{4}-\d{2}-\d{2}")
        | date_str.str.match(r"^\d{8}")
    )
    df = df[valid_mask].copy()

    work = df[[date_col] + half_hour_cols].copy()
    work["source_name"] = source_name
    melted = work.melt(
        id_vars=[date_col, "source_name"],
        value_vars=half_hour_cols,
        var_name="time_slot",
        value_name="supply_kwh",
    )
    melted["supply_kwh"] = pd.to_numeric(melted["supply_kwh"], errors="coerce")

    # datetime 構築
    date_part = pd.to_datetime(melted[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    ts = melted["time_slot"].str.extract(r"^(\d+):(\d+)", expand=True)
    start_h = ts[0].str.zfill(2)
    start_m = ts[1]
    melted["datetime"] = pd.to_datetime(
        date_part + " " + start_h + ":" + start_m,
        format="%Y-%m-%d %H:%M",
        errors="coerce",
    )
    return (
        melted[["datetime", "source_name", "supply_kwh"]]
        .dropna(subset=["datetime"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# メインエントリポイント
# ---------------------------------------------------------------------------

def load_supply_file(
    source: str | Path | io.BytesIO,
    filename: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    供給側 Excel を読み込み (df, source_name) を返す。
    df の列: datetime / source_name / supply_kwh

    Returns
    -------
    df          : 標準供給 DataFrame
    source_name : 電源名（ファイル名または Excel 内の発電所名）
    """
    is_bytes = isinstance(source, io.BytesIO)
    _filename = filename or (
        Path(source).name if isinstance(source, (str, Path))
        else getattr(source, "name", "不明")
    )

    if is_bytes:
        source.seek(0)
    xl = pd.ExcelFile(source)
    sheet_names = xl.sheet_names

    # 電源名の取得（ワイド形式シートの 発電所名 列が最優先）
    source_name = _source_name_from_filename(_filename)
    for sh in _WIDE_SHEET_NAMES:
        if sh in sheet_names:
            if is_bytes:
                source.seek(0)
            probe = pd.read_excel(source, sheet_name=sh, nrows=2)
            if is_bytes:
                source.seek(0)
            name_col = _find_col(list(probe.columns), ["発電所名", "電源名", "source_name", "name"])
            if name_col and not probe.empty:
                v = str(probe[name_col].iloc[0]).strip()
                if v and v != "nan":
                    source_name = v
            break

    # シート優先順位: 長形式 → ワイド形式 → 先頭シート
    target_sheet = None
    for sh in _LONG_SHEET_NAMES:
        if sh in sheet_names:
            target_sheet = sh
            break

    if target_sheet is None:
        # 先頭シートが長形式かどうか確認
        for sh in sheet_names:
            if is_bytes:
                source.seek(0)
            probe = pd.read_excel(source, sheet_name=sh, nrows=3)
            if is_bytes:
                source.seek(0)
            probe_cols = list(probe.columns)
            has_supply = (
                _find_col(probe_cols, _SUPPLY_KWH_ALIASES) is not None
                or _find_col(probe_cols, _SUPPLY_KW_ALIASES) is not None
            )
            has_date  = _find_col(probe_cols, _DATETIME_ALIASES) is not None
            if has_date and has_supply:
                target_sheet = sh
                break

    if target_sheet is None:
        # ワイド形式を試みる
        for sh in _WIDE_SHEET_NAMES:
            if sh in sheet_names:
                target_sheet = sh
                break

    if target_sheet is None:
        target_sheet = sheet_names[0]

    # 読み込み
    if is_bytes:
        source.seek(0)
    df_raw = pd.read_excel(source, sheet_name=target_sheet, dtype=str)
    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    # 長形式か横展開かを判定して変換
    if any(_is_30min_slot(c) for c in df_raw.columns):
        df = _load_wide_supply(df_raw, source_name)
    else:
        df = _load_long_form(df_raw, source_name)

    return df, source_name


def merge_supply_files(
    sources: list[Any],
    filenames: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """複数の供給ファイルを結合して返す。"""
    dfs, names = [], []
    for i, src in enumerate(sources):
        fname = filenames[i] if filenames else None
        df, name = load_supply_file(src, filename=fname)
        dfs.append(df)
        names.append(name)
    if not dfs:
        return pd.DataFrame(columns=["datetime", "source_name", "supply_kwh"]), []
    return pd.concat(dfs, ignore_index=True), names
