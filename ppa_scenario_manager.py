"""
ppa_scenario_manager.py
「PPA採算性」シナリオ（ppa_retail_calc.SimulationInputs一式）の保存・読込・比較実行。
retail_fs.save_fs_design / scenario_manager.Scenario と同じ永続化パターン
（/tmp/energy_dashboard/ 配下のJSONファイル）に揃えている。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import ppa_retail_calc as calc

_DIR = Path("/tmp/energy_dashboard")
_DESIGN_FILE = _DIR / "ppa_design.json"
_SCENARIOS_FILE = _DIR / "ppa_scenarios.json"


def save_design(inputs: calc.SimulationInputs) -> None:
    """現在編集中の入力一式をドラフトとして保存する（ページ遷移後も復元できるように）。"""
    _DIR.mkdir(parents=True, exist_ok=True)
    _DESIGN_FILE.write_text(
        json.dumps(calc.inputs_to_dict(inputs), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_design() -> calc.SimulationInputs | None:
    if not _DESIGN_FILE.exists():
        return None
    try:
        return calc.inputs_from_dict(json.loads(_DESIGN_FILE.read_text("utf-8")))
    except Exception:
        return None


@dataclass
class PpaScenario:
    name: str
    inputs: dict = field(default_factory=dict)  # calc.inputs_to_dict(...)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def save_scenario(scenario: PpaScenario) -> None:
    scenarios = [s for s in load_scenarios() if s.name != scenario.name]
    scenarios.append(scenario)
    _DIR.mkdir(parents=True, exist_ok=True)
    _SCENARIOS_FILE.write_text(
        json.dumps([asdict(s) for s in scenarios], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_scenarios() -> list[PpaScenario]:
    if not _SCENARIOS_FILE.exists():
        return []
    try:
        return [PpaScenario(**d) for d in json.loads(_SCENARIOS_FILE.read_text("utf-8"))]
    except Exception:
        return []


def delete_scenario(name: str) -> None:
    scenarios = [s for s in load_scenarios() if s.name != name]
    _DIR.mkdir(parents=True, exist_ok=True)
    _SCENARIOS_FILE.write_text(
        json.dumps([asdict(s) for s in scenarios], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_scenario(scenario: PpaScenario) -> calc.SimulationResult:
    inputs = calc.inputs_from_dict(scenario.inputs)
    return calc.simulate(inputs)
