"""
grouping.py
施設名から地域・機能種別を自動検出し、グループ管理を行う。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

GROUPS_FILE = Path("/tmp/energy_dashboard/groups.json")

FUNCTION_KEYWORDS: dict[str, list[str]] = {
    "行政": ["役場", "庁舎", "市役所", "町役場", "村役場", "区役所", "支所", "出張所", "行政"],
    "学校": ["小学校", "中学校", "高校", "高等学校", "大学", "学校", "学院"],
    "文化・図書": ["図書館", "文化館", "資料館", "博物館", "美術館", "文化センター", "文化会館"],
    "スポーツ": ["体育館", "スポーツ", "運動場", "プール", "グラウンド", "アリーナ"],
    "保育・幼稚": ["保育園", "幼稚園", "こども園", "保育所", "認定こども"],
    "医療・福祉": ["病院", "診療所", "クリニック", "福祉", "介護", "老人", "デイ", "ホーム"],
    "集会施設": ["公民館", "集会所", "コミュニティ", "会館", "センター"],
}

_REGION_RE = re.compile(r"([^\s　]{2,6}[市町村区郡])")


def auto_detect_region(name: str) -> str:
    m = _REGION_RE.search(name)
    return m.group(1) if m else "不明"


def auto_detect_function(name: str) -> str:
    for func_type, keywords in FUNCTION_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return func_type
    return "その他"


def build_group_df(facility_names: list[str], custom: dict | None = None) -> pd.DataFrame:
    """施設ごとの region / function_type を持つ DataFrame を返す。"""
    custom = custom or {}
    rows = []
    for name in facility_names:
        entry = custom.get(name, {})
        rows.append({
            "facility_name": name,
            "region": entry.get("region", auto_detect_region(name)),
            "function_type": entry.get("function_type", auto_detect_function(name)),
        })
    return pd.DataFrame(rows)


def load_custom_groups() -> dict:
    if GROUPS_FILE.exists():
        try:
            return json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_custom_groups(groups_df: pd.DataFrame) -> None:
    """group DataFrame（facility_name, region, function_type）を JSON に保存する。"""
    custom: dict[str, dict] = {}
    for _, row in groups_df.iterrows():
        custom[row["facility_name"]] = {
            "region": row["region"],
            "function_type": row["function_type"],
        }
    GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GROUPS_FILE.write_text(
        json.dumps(custom, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def filter_by_group(
    df: pd.DataFrame,
    group_df: pd.DataFrame,
    col: str,
    selected: list[str],
) -> pd.DataFrame:
    """col（'region' or 'function_type'）の値が selected に含まれる施設のみ返す。"""
    matched = group_df[group_df[col].isin(selected)]["facility_name"].tolist()
    return df[df["facility_name"].isin(matched)].copy()


def add_group_column(df: pd.DataFrame, group_df: pd.DataFrame, col: str) -> pd.DataFrame:
    """df に 'group_label' 列（region or function_type の値）を追加する。"""
    mapping = group_df.set_index("facility_name")[col].to_dict()
    out = df.copy()
    out["group_label"] = out["facility_name"].map(mapping).fillna("不明")
    return out
