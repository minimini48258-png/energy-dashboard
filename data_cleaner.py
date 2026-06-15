"""
data_cleaner.py
標準化後の DataFrame に対して品質チェックと修正を行う。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CleanReport:
    total_rows: int = 0
    rows_after: int = 0
    missing_datetime: int = 0
    missing_consumption: int = 0
    duplicate_rows: int = 0
    negative_values: int = 0
    datetime_gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return any([
            self.missing_datetime,
            self.missing_consumption,
            self.duplicate_rows,
            self.negative_values,
            self.datetime_gaps,
        ])


def clean(df: pd.DataFrame, fill_missing: bool = False) -> tuple[pd.DataFrame, CleanReport]:
    """
    データクレンジングを実施し、クリーン済み DataFrame とレポートを返す。

    Parameters
    ----------
    df : 標準形式 DataFrame (datetime, facility_name, consumption_kwh)
    fill_missing : True の場合、欠損消費量を前後の平均で補完する
    """
    report = CleanReport(total_rows=len(df))
    df = df.copy()

    # datetime パース（文字列が混入している場合）
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    report.missing_datetime = int(df["datetime"].isna().sum())
    df = df.dropna(subset=["datetime"])

    # 消費量の数値変換
    df["consumption_kwh"] = pd.to_numeric(df["consumption_kwh"], errors="coerce")
    report.missing_consumption = int(df["consumption_kwh"].isna().sum())

    # 負の値
    report.negative_values = int((df["consumption_kwh"] < 0).sum())

    # 重複（同一施設・同一日時）
    dup_mask = df.duplicated(subset=["datetime", "facility_name"], keep="first")
    report.duplicate_rows = int(dup_mask.sum())
    df = df[~dup_mask]

    if fill_missing:
        df["consumption_kwh"] = (
            df.sort_values("datetime")
            .groupby("facility_name")["consumption_kwh"]
            .transform(lambda s: s.interpolate(method="linear", limit_direction="both"))
        )
    else:
        df = df.dropna(subset=["consumption_kwh"])

    # タイムスタンプの抜けチェック（施設ごとに 30 分間隔を期待）
    for fac, grp in df.groupby("facility_name"):
        grp_sorted = grp.sort_values("datetime")
        diffs = grp_sorted["datetime"].diff().dropna()
        expected = pd.Timedelta("30min")
        gaps = diffs[diffs > expected * 1.5]
        if not gaps.empty:
            first_gap_label = gaps.index[0]
            pos = grp_sorted.index.get_loc(first_gap_label)
            gap_start = grp_sorted.iloc[pos - 1]["datetime"] if pos > 0 else "?"
            report.datetime_gaps.append(
                f"{fac}: {len(gaps)} 箇所の抜け（最初の欠落前後: {gap_start}）"
            )

    report.rows_after = len(df)
    return df.reset_index(drop=True), report


def validate_standard_columns(df: pd.DataFrame) -> list[str]:
    """必須列の存在チェック。問題があれば説明メッセージのリストを返す。"""
    required = ["datetime", "facility_name", "consumption_kwh"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [f"必須列が見つかりません: {', '.join(missing)}"]
    return []
