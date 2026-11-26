"""シナリオ機能の改修（集約戸数・余剰の扱い・JEPX加減額・JSONバックアップ・契約電力取り込み）の単体テスト。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import retail_fs
import scenario_manager
import supply_planner


def _ts(days=2):
    return pd.date_range("2026-01-01", periods=48 * days, freq="30min")


def _demand(name, kwh, days=2):
    return pd.DataFrame({"datetime": _ts(days), "facility_name": name, "consumption_kwh": kwh})


def test_detect_n_units():
    assert retail_fs.detect_n_units("住宅_三世代・その他世帯_町内363戸合計(推計)") == 363
    assert retail_fs.detect_n_units("池田町役場") == 1


def test_tiered_aggregate_equals_sum_of_units():
    """363戸の合計行は、1戸分の段階料金×363と同じ売上になる（合計kWhをそのまま段階に当てない）。"""
    plan = [p for p in retail_fs.default_tariff_plans() if p.voltage_class == "低圧"][0]
    one = _demand("1戸", 0.5, days=30)
    agg = _demand("363戸", 0.5 * 363, days=30)
    cfg1 = retail_fs.FacilityConfig("1戸", 6.0, "低圧", 100.0, plan.name, 1)
    cfgN = retail_fs.FacilityConfig("363戸", 6.0 * 363, "低圧", 100.0, plan.name, 363)
    r1 = retail_fs.calc_facility_revenue(one, [cfg1], [plan], 0.0, 0.0)["volumetric_revenue"].sum()
    rN = retail_fs.calc_facility_revenue(agg, [cfgN], [plan], 0.0, 0.0)["volumetric_revenue"].sum()
    assert abs(rN - r1 * 363) < 1e-6 * rN
    # 戸数を指定しない（従来動作）と、第3段階単価が合計kWhに当たるため過大になる
    cfg_bad = retail_fs.FacilityConfig("363戸", 6.0 * 363, "低圧", 100.0, plan.name, 1)
    r_bad = retail_fs.calc_facility_revenue(agg, [cfg_bad], [plan], 0.0, 0.0)["volumetric_revenue"].sum()
    assert r_bad > rN


def test_cap_supply_to_demand_removes_surplus_only():
    demand = _demand("A", 1.0)
    supply = pd.concat([
        pd.DataFrame({"datetime": _ts(), "source_name": "S1", "supply_kwh": 3.0}),
        pd.DataFrame({"datetime": _ts(), "source_name": "S2", "supply_kwh": 1.0}),
    ], ignore_index=True)
    capped = supply_planner.cap_supply_to_demand(supply, demand)
    total = capped.groupby("datetime")["supply_kwh"].sum()
    assert (total <= 1.0 + 1e-9).all() and abs(total.iloc[0] - 1.0) < 1e-9
    # 電源間の比率は保たれる
    first = capped[capped["datetime"] == capped["datetime"].iloc[0]].set_index("source_name")["supply_kwh"]
    assert abs(first["S1"] / first["S2"] - 3.0) < 1e-9
    # 供給が需要より小さいコマは変わらない
    small = pd.DataFrame({"datetime": _ts(), "source_name": "S1", "supply_kwh": 0.4})
    assert abs(supply_planner.cap_supply_to_demand(small, demand)["supply_kwh"].sum() - small["supply_kwh"].sum()) < 1e-9


def _scenario(mode="buy_and_sell", shift=0.0, with_cache_id=False):
    plans = retail_fs.default_tariff_plans()
    high = [p for p in plans if p.voltage_class == "高圧"][0]
    design = {
        "tariff_plans": [retail_fs.asdict(p) for p in plans],
        "facility_configs": [retail_fs.asdict(retail_fs.FacilityConfig("A", 100.0, "高圧", 100.0, high.name))],
        "transmission_rates": {},
        "source_costs": {"S1": 8.0},
        "surplus_mode": mode,
        "jepx_shift_yen_per_kwh": shift,
        "sga_items": {"販管費": 1_000_000.0},
        "capacity_unit_yen_per_kw_year": 1000.0,
    }
    return scenario_manager.Scenario(
        name="t", fs_design=design, supply_data_cache_id="missing" if with_cache_id else None,
        selected_supply_names=["S1"],
    )


def _supply(kwh):
    return pd.DataFrame({"datetime": _ts(30), "source_name": "S1", "supply_kwh": kwh})


def test_run_scenario_surplus_mode_and_scope():
    demand = pd.concat([_demand("A", 1.0, 30), _demand("対象外", 5.0, 30)], ignore_index=True)
    sup = _supply(3.0)
    both = scenario_manager.run_scenario(_scenario("buy_and_sell"), demand, fallback_supply_df=sup)["annual"]
    self_only = scenario_manager.run_scenario(_scenario("self_consumption_only"), demand, fallback_supply_df=sup)["annual"]
    # 施設設定にない施設は需要から除かれ、Aの需要(1kWh/コマ)だけが対象
    assert abs(both["kwh"] - 1.0 * 48 * 30) < 1e-6
    assert both["market_sale_revenue"] > 0
    assert self_only["market_sale_revenue"] == 0
    assert self_only["gen_cost"] < both["gen_cost"]


def test_run_scenario_fallback_warning_and_jepx_shift():
    demand = _demand("A", 1.0, 30)
    res = scenario_manager.run_scenario(_scenario(with_cache_id=True), demand, fallback_supply_df=_supply(3.0))
    assert any("現在読み込み中の供給データ" in w for w in res["warnings"])
    base = scenario_manager.run_scenario(_scenario(shift=0.0), demand, fallback_supply_df=_supply(3.0))["annual"]
    up = scenario_manager.run_scenario(_scenario(shift=5.0), demand, fallback_supply_df=_supply(3.0))["annual"]
    assert up["market_sale_revenue"] > base["market_sale_revenue"]
    assert up["gross_profit"] > base["gross_profit"]  # 余剰を売る構成なのでJEPX上振れは粗利に有利


def test_scenarios_json_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_manager, "SCENARIOS_FILE", tmp_path / "scenarios.json")
    sc = _scenario("self_consumption_only", shift=2.0)
    text = scenario_manager.scenarios_to_json([sc])
    restored = scenario_manager.scenarios_from_json(text)
    assert restored[0].fs_design["surplus_mode"] == "self_consumption_only"
    assert scenario_manager.import_scenarios(restored) == 1
    assert [s.name for s in scenario_manager.load_scenarios()] == ["t"]
    try:
        scenario_manager.scenarios_from_json("{not json")
        assert False
    except ValueError:
        pass


def test_parse_contract_table_and_default_voltage():
    t = pd.DataFrame({"施設名": ["A", "B", " "], "契約電力(kW)": [116, "x", 5]})
    assert retail_fs.parse_contract_table(t) == {"A": 116.0}
    assert retail_fs.default_voltage_class(49.9) == "低圧" and retail_fs.default_voltage_class(50) == "高圧"
    assert retail_fs.default_voltage_class(557, "住宅_三世代_町内363戸合計(推計)", 363) == "低圧"
    assert retail_fs.default_voltage_class(2294, "その他低圧施設(推計)") == "低圧"
    assert retail_fs.default_voltage_class(6419, "その他高圧事業所(推計)") == "高圧"
    try:
        retail_fs.parse_contract_table(pd.DataFrame({"a": [1]}))
        assert False
    except ValueError:
        pass
