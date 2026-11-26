"""
grouping.py
施設名から地域・機能種別を自動検出し、グループ管理を行う。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

import storage

GROUPS_FILE = storage.DATA_DIR / "groups.json"

FUNCTION_KEYWORDS: dict[str, list[str]] = {
    "行政": ["役場", "庁舎", "市役所", "町役場", "村役場", "区役所", "支所", "出張所", "行政"],
    "学校": ["小学校", "中学校", "高校", "高等学校", "大学", "学校", "学院"],
    "文化・図書": ["図書館", "文化館", "資料館", "博物館", "美術館", "文化センター", "文化会館"],
    "スポーツ": ["体育館", "スポーツ", "運動場", "プール", "グラウンド", "アリーナ"],
    "保育・幼稚": ["保育園", "幼稚園", "こども園", "保育所", "認定こども"],
    "医療・福祉": ["病院", "診療所", "クリニック", "福祉", "介護", "老人", "デイ", "ホーム"],
    "集会施設": ["公民館", "集会所", "コミュニティ", "会館", "センター"],
    "住宅": ["住宅", "邸", "様宅", "アパート", "マンション", "団地", "社宅", "寮"],
    "事業所": ["事業所", "工場", "店舗", "オフィス", "事務所", "営業所", "株式会社", "有限会社", "(株)", "（株）", "㈱"],
}
FUNCTION_TYPE_OPTIONS: list[str] = list(FUNCTION_KEYWORDS.keys()) + ["その他"]

# 画面から追加した独自の種別（機能種別・電源種別）の保存先
EXTRA_TYPES_FILE = storage.DATA_DIR / "extra_types.json"


def load_extra_types() -> dict[str, list[str]]:
    """{"function_types": [...], "source_types": [...]} を返す（未保存なら空リスト）。"""
    data: dict = {}
    if EXTRA_TYPES_FILE.exists():
        try:
            data = json.loads(EXTRA_TYPES_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    return {
        "function_types": list(data.get("function_types", [])),
        "source_types": list(data.get("source_types", [])),
    }


def add_extra_type(kind: str, name: str) -> bool:
    """
    独自の種別を追加して保存する。kind は "function_types" または "source_types"。
    追加した場合 True、空文字・既存の種別なら False。
    """
    name = name.strip()
    builtin = FUNCTION_TYPE_OPTIONS if kind == "function_types" else SOURCE_TYPE_OPTIONS
    extras = load_extra_types()
    if not name or name in builtin or name in extras[kind]:
        return False
    extras[kind].append(name)
    EXTRA_TYPES_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXTRA_TYPES_FILE.write_text(json.dumps(extras, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def type_options(kind: str, in_use: list[str] | None = None) -> list[str]:
    """
    表の選択肢：既定の種別 ＋ 画面から追加した種別 ＋ 現在設定に使われている種別（重複なし）。
    「その他」は末尾に置く。
    """
    builtin = FUNCTION_TYPE_OPTIONS if kind == "function_types" else SOURCE_TYPE_OPTIONS
    opts = [o for o in builtin if o != "その他"]
    for o in load_extra_types()[kind] + sorted(set(in_use or [])):
        if o not in opts and o != "その他":
            opts.append(o)
    return opts + ["その他"]

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


# ---------------------------------------------------------------------------
# 供給側（電源）のグループ管理：電源種別（住宅太陽光・小水力など）と地域
# ---------------------------------------------------------------------------

SUPPLY_GROUPS_FILE = storage.DATA_DIR / "supply_groups.json"

# 判定は上から順に行う（「住宅」「屋根」を含む太陽光を事業用太陽光より先に判定するため）
SOURCE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "住宅太陽光": ["住宅", "家庭", "屋根", "卒FIT", "卒fit", "宅"],
    "事業用太陽光": ["メガソーラー", "ソーラー", "太陽光", "PV", "pv"],
    "小水力": ["小水力", "水力", "水車"],
    "バイオマス": ["バイオマス", "木質", "バイオガス"],
    "風力": ["風力"],
    "相対電源": ["相対"],
}
SOURCE_TYPE_OPTIONS: list[str] = list(SOURCE_TYPE_KEYWORDS.keys()) + ["その他"]


def auto_detect_source_type(name: str) -> str:
    for source_type, keywords in SOURCE_TYPE_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return source_type
    return "その他"


def build_supply_group_df(source_names: list[str], custom: dict | None = None) -> pd.DataFrame:
    """
    電源ごとの source_type（電源種別）/ region（地域）を持つ DataFrame を返す。
    列名 facility_name は需要側と揃えている（集計関数を共用するため。中身は電源名）。
    """
    custom = custom or {}
    rows = []
    for name in source_names:
        entry = custom.get(name, {})
        rows.append({
            "facility_name": name,
            "source_type": entry.get("source_type", auto_detect_source_type(name)),
            "region": entry.get("region", auto_detect_region(name)),
        })
    return pd.DataFrame(rows)


def load_supply_groups() -> dict:
    if SUPPLY_GROUPS_FILE.exists():
        try:
            return json.loads(SUPPLY_GROUPS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_supply_groups(groups_df: pd.DataFrame) -> None:
    """供給グループ DataFrame（facility_name, source_type, region）を JSON に保存する。"""
    custom = {
        row["facility_name"]: {"source_type": row["source_type"], "region": row["region"]}
        for _, row in groups_df.iterrows()
    }
    SUPPLY_GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUPPLY_GROUPS_FILE.write_text(json.dumps(custom, ensure_ascii=False, indent=2), encoding="utf-8")
