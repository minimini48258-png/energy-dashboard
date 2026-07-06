"""
data_loader.py
Excelまたは CSV ファイルを読み込み、標準形式の DataFrame に変換する。

対応フォーマット：
  A) 標準縦展開形式：datetime / facility_name / consumption_kwh の列を持つ長形式
  B) 横展開日別形式（東北電力）：1行＝1日、30分値が48列
       - 1行目：タイトル（download_siyouryo_30min など）
       - 2行目：列ヘッダー（年月日、ご契約名義、0:00～0:30 … 23:30～24:00 など）
  C) エナリス形式：1行＝1日、30分値が48列（0:00～0:30(kWh) 形式の列名）
       - 1行目：列ヘッダー（お客様番号、需要場所ID、年月日、0:00～0:30(kWh) …）
       - 施設名はファイル名から自動取得
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd

STANDARD_COLUMNS = {
    "datetime": "datetime",
    "facility_name": "facility_name",
    "consumption_kwh": "consumption_kwh",
}

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


# ---------------------------------------------------------------------------
# フォーマット判定
# ---------------------------------------------------------------------------

def _is_enaris_format(peek: pd.DataFrame) -> bool:
    """エナリス形式の判定: 行0がヘッダーで 年月日 列と HH:MM～HH:MM(kWh) 形式の時間帯列がある。
    ～ 文字のUnicodeコード差異（U+FF5E/U+301C）を吸収するため (kWh) suffix で判定する。
    """
    col_strs = peek.columns.astype(str).tolist()
    return "年月日" in col_strs and any(
        re.match(r"^\d+:\d+.+\d+:\d+\(kWh\)$", c) for c in col_strs
    )


def _is_wide_daily_format(peek: pd.DataFrame) -> bool:
    """先頭 3 行を見て横展開（1日1行×48列）形式かどうか判定する。

    想定構造（header=0 で読んだとき）:
      columns   = Excel row 0 (タイトル行): Unnamed: 0, 長門町役場, Unnamed: 2, ...
      iloc[0]   = Excel row 1 (列ヘッダー行): 年月日, お客様番号, ..., 0:00～0:30, ...
      iloc[1]   = Excel row 2 (最初のデータ行): 20210801, ...
    """
    if peek.empty:
        return False

    # ケース1: iloc[0] が実際の列ヘッダー行（=横展開形式の典型パターン）
    # → '年月日' が iloc[0] の値として存在する
    row0_vals = peek.iloc[0].astype(str).tolist()
    if "年月日" in row0_vals:
        return True

    # ケース2: 既に正しいヘッダーで読まれていて、列名に 年月日 と 時間帯列が混在
    col_strs = peek.columns.astype(str).tolist()
    if "年月日" in col_strs and any(re.search(r"\d+:\d+.\d+:\d+", c) for c in col_strs):
        return True

    return False


def _is_30min_timeslot(col: str) -> bool:
    """列名が 30 分間隔の時間帯を表すか判定（例: '0:00～0:30', '23:30～24:00'）。
    ～ のUnicode差異（U+FF5E/U+301C）を吸収するため [^\d:] で任意1文字を許容する。
    """
    m = re.match(r"^(\d+):(\d+)[^\d:](\d+):(\d+)$", str(col).strip())
    if not m:
        return False
    h1, m1, h2, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    end_mins = (24 if h2 == 24 else h2) * 60 + m2
    return (end_mins - h1 * 60 - m1) == 30


# ---------------------------------------------------------------------------
# エナリス形式のパーサー
# ---------------------------------------------------------------------------

def _extract_facility_from_filename(filename: str) -> str:
    """ファイル名から施設名を抽出する。
    例: 【エナリス】202506_使用実績_佐久穂町生涯学習館.xlsx → 佐久穂町生涯学習館
    """
    stem = Path(filename).stem
    stem = re.sub(r"【[^】]*】", "", stem).strip()
    m = re.search(r"使用実績[_＿](.+)$", stem)
    if m:
        return m.group(1).strip("_　 ")
    m = re.search(r"\d{6}[_＿](.+)$", stem)
    if m:
        return m.group(1).strip("_　 ")
    return stem or "不明"


def _load_enaris(source: Any, filename: str = "不明", sheet_name: int | str = 0) -> pd.DataFrame:
    """エナリス形式（1行1日・HH:MM～HH:MM(kWh)×48列）を標準長形式に変換する。
    施設名はファイル名から取得する。
    """
    df = pd.read_excel(source, sheet_name=sheet_name, header=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    if "年月日" not in df.columns:
        raise ValueError("エナリス形式と判定しましたが '年月日' 列が見つかりません。")

    df = df[df["年月日"].notna() & (df["年月日"].astype(str).str.strip() != "")].copy()
    if df.empty:
        raise ValueError("エナリス形式: 有効なデータ行がありません。")

    facility_name = _extract_facility_from_filename(filename)

    half_hour_cols = [c for c in df.columns if re.match(r"^\d+:\d+.+\d+:\d+\(kWh\)$", c)]
    if not half_hour_cols:
        raise ValueError("エナリス形式: 30分値列（例: '0:00～0:30(kWh)'）が見つかりません。")

    work = df[["年月日"] + half_hour_cols].copy()
    work["facility_name"] = facility_name
    melted = work.melt(
        id_vars=["年月日", "facility_name"],
        value_vars=half_hour_cols,
        var_name="time_slot",
        value_name="consumption_kwh",
    )

    date_part = pd.to_datetime(melted["年月日"], errors="coerce").dt.strftime("%Y-%m-%d")
    # 時間を2桁ゼロパディング（pandas 2.x は %H が2桁必須）
    _ts = melted["time_slot"].str.extract(r"^(\d+):(\d+)～", expand=True)
    start_time = _ts[0].str.zfill(2) + ":" + _ts[1]
    melted["datetime"] = pd.to_datetime(
        date_part + " " + start_time,
        format="%Y-%m-%d %H:%M",
        errors="coerce",
    )
    melted["consumption_kwh"] = pd.to_numeric(melted["consumption_kwh"], errors="coerce")

    return (
        melted[["datetime", "facility_name", "consumption_kwh"]]
        .dropna(subset=["datetime"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 横展開形式のパーサー（東北電力）
# ---------------------------------------------------------------------------

def _load_wide_daily(source: Any, sheet_name: int | str = 0) -> pd.DataFrame:
    """
    1行1日・30分値横展開形式のExcelを読み込み、標準長形式に変換する。

    想定カラム：
      年月日（YYYYMMDD）/ ご契約名義 / ... / 0:00～0:30 ～ 23:30～24:00 / 備考
    """
    df = pd.read_excel(source, sheet_name=sheet_name, header=1, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # タイトル行（download_siyouryo… 等）を除去：年月日が8桁数字の行だけ残す
    if "年月日" not in df.columns:
        raise ValueError("横展開形式と判定しましたが '年月日' 列が見つかりません。")
    df = df[df["年月日"].astype(str).str.match(r"^\d{8}$")].copy()

    if df.empty:
        raise ValueError("有効なデータ行がありません（年月日が YYYYMMDD 形式の行が見つからない）。")

    # 施設名の取得（ご契約名義 → なければ ご使用場所住所 → なければ '不明'）
    facility_col = next(
        (c for c in ["ご契約名義", "ご使用場所住所", "名称"] if c in df.columns),
        None,
    )
    if facility_col:
        facility_series = df[facility_col].astype(str).str.strip()
    else:
        facility_series = pd.Series(["不明"] * len(df), index=df.index)

    # 30分値列の抽出
    half_hour_cols = [c for c in df.columns if _is_30min_timeslot(c)]
    if not half_hour_cols:
        raise ValueError("30分値列（例: '0:00～0:30'）が見つかりません。")

    # 横→縦に変換（melt）
    work = df[["年月日"] + half_hour_cols].copy()
    work["facility_name"] = facility_series.values
    melted = work.melt(
        id_vars=["年月日", "facility_name"],
        value_vars=half_hour_cols,
        var_name="time_slot",
        value_name="consumption_kwh",
    )

    # datetime 列の構築（ベクトル化）
    date_str = melted["年月日"].str.zfill(8)
    start_h = melted["time_slot"].str.extract(r"^(\d+):")[0].astype(int).apply(lambda h: f"{h:02d}")
    start_m = melted["time_slot"].str.extract(r"^\d+:(\d+)～")[0]
    melted["datetime"] = pd.to_datetime(
        date_str + " " + start_h + ":" + start_m,
        format="%Y%m%d %H:%M",
        errors="coerce",
    )
    melted["consumption_kwh"] = pd.to_numeric(melted["consumption_kwh"], errors="coerce")

    result = (
        melted[["datetime", "facility_name", "consumption_kwh"]]
        .dropna(subset=["datetime"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )
    return result


# ---------------------------------------------------------------------------
# 標準形式のパーサー
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("　", "")


def _detect_column_mapping(
    columns: list[str],
    alias_map: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    alias_map = alias_map or DEFAULT_ALIAS_MAP
    mapping: dict[str, str] = {}
    normalized_cols = {_normalize(c): c for c in columns}
    for std_col, aliases in alias_map.items():
        for alias in aliases:
            if _normalize(alias) in normalized_cols:
                mapping[normalized_cols[_normalize(alias)]] = std_col
                break
    return mapping


def _parse_standard(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df["consumption_kwh"] = pd.to_numeric(df["consumption_kwh"], errors="coerce")
    df["facility_name"] = df["facility_name"].astype(str).str.strip()
    return df[["datetime", "facility_name", "consumption_kwh"]]


# ---------------------------------------------------------------------------
# 統合エントリポイント
# ---------------------------------------------------------------------------

def load_file(
    source: str | Path | io.BytesIO,
    sheet_name: int | str = 0,
    column_mapping: dict[str, str] | None = None,
    encoding: str = "utf-8",
    filename: str | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Excel または CSV を読み込んで標準 DataFrame を返す。
    フォーマット（縦展開 / 横展開 / エナリス）は自動判定。

    Returns
    -------
    df : 標準化された DataFrame（datetime, facility_name, consumption_kwh）
    applied_mapping : 実際に適用した列マッピング
    """
    is_bytes = isinstance(source, io.BytesIO)

    if isinstance(source, (str, Path)):
        suffix = Path(source).suffix.lower()
        _filename = filename or Path(source).name
    else:
        suffix = ".xlsx"
        _filename = filename or getattr(source, "name", "不明")

    # --- フォーマット判定（Excel のみ）---
    if suffix in {".xlsx", ".xls"}:
        if is_bytes:
            source.seek(0)
        peek = pd.read_excel(source, sheet_name=sheet_name, dtype=str, nrows=3)
        if is_bytes:
            source.seek(0)

        # エナリス形式を先に判定（wide_daily のケース2と重複するため）
        if _is_enaris_format(peek):
            df = _load_enaris(source, filename=_filename, sheet_name=sheet_name)
            return df, {"format": "enaris"}

        if _is_wide_daily_format(peek):
            df = _load_wide_daily(source, sheet_name=sheet_name)
            return df, {"format": "wide_daily"}

        if is_bytes:
            source.seek(0)
        raw = pd.read_excel(source, sheet_name=sheet_name, dtype=str)

    elif suffix == ".csv":
        try:
            raw = pd.read_csv(source, dtype=str, encoding=encoding)
        except UnicodeDecodeError:
            if is_bytes:
                source.seek(0)
            raw = pd.read_csv(source, dtype=str, encoding="shift-jis")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    raw.columns = [str(c).strip() for c in raw.columns]
    applied_mapping = column_mapping or _detect_column_mapping(list(raw.columns))
    df = raw.rename(columns=applied_mapping)

    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        return df, applied_mapping

    df = _parse_standard(df)
    return df, applied_mapping


def merge_multiple_files(
    sources: list[Any],
    sheet_name: int | str = 0,
    column_mappings: list[dict[str, str]] | None = None,
    filenames: list[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    dfs: list[pd.DataFrame] = []
    mappings: list[dict[str, str]] = []

    for i, src in enumerate(sources):
        col_map = column_mappings[i] if column_mappings else None
        fname = filenames[i] if filenames else None
        df, applied = load_file(src, sheet_name=sheet_name, column_mapping=col_map, filename=fname)
        dfs.append(df)
        mappings.append(applied)

    if not dfs:
        return pd.DataFrame(columns=list(STANDARD_COLUMNS)), []

    return pd.concat(dfs, ignore_index=True), mappings


def get_column_suggestions(df: pd.DataFrame) -> dict[str, list[str]]:
    return {
        "datetime": list(df.columns),
        "facility_name": list(df.columns),
        "consumption_kwh": list(df.columns),
    }
