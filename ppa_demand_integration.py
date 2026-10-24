"""
ppa_demand_integration.py
PPA採算性シミュレーターを、実際にアップロードされた30分値需要データと
solar_simulator（太陽光＋蓄電池の技術シミュレーション）に接続するための橋渡しロジック。

ppa_retail_calc.py（財務計算エンジン）は年間kWh・自家消費率(%)という集計値だけを
入力として受け取る設計になっている。ここでは、実需要データ×太陽光容量から
solar_simulator.run_simulation()で30分値の自家消費・余剰・外部調達を実際に計算し、
その実績値を年間kWh・自家消費率(%)に変換してppa_retail_calc側へ受け渡す。

これにより、ppa_retail_calc.py自体（二重計上防止の核となる計算式）には一切手を
加えずに、「自家消費率は仮定値」から「自家消費率は実データからの算出値」へ
置き換えることができる。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import solar_simulator


@dataclass
class RealDataMetrics:
    sim_df: pd.DataFrame            # 30分値シミュレーション結果（solar_simulator.run_simulation()の戻り値）
    n_days_in_data: int              # 実データの対象日数
    annual_consumption_kwh: float    # 実績使用量を年換算した値
    annual_generation_kwh: float     # 実績発電量を年換算した値
    self_consumption_rate_pct: float  # 発電量に対する自家消費（直接消費＋蓄電池放電）の割合
    self_sufficiency_rate_pct: float  # 使用量に対する太陽光＋蓄電池での充足率
    grid_import_kwh_annual: float    # 外部調達電力量（年換算）
    grid_export_kwh_annual: float    # 余剰電力量（年換算）


def run_real_data_simulation(
    demand_df: pd.DataFrame,
    solar_capacity_kw: float,
    battery_capacity_kwh: float = 0.0,
    battery_efficiency_pct: float = 95.0,
    mode: str = "basic",
    min_soc_pct: float = 30.0,
    peak_threshold_kw: float | None = None,
) -> RealDataMetrics:
    """
    実需要データ(demand_df: datetime, facility_name, consumption_kwh)に対して太陽光＋蓄電池の
    30分値シミュレーションを実行し、年換算した集計値を返す。

    年換算: 実データの対象日数が365日に満たない／超える場合、合計値に (365/対象日数) を乗じる。
    自家消費率・自給率は比率のため年換算の影響を受けない（実績の比率をそのまま使用）。
    """
    sim_df = solar_simulator.run_simulation(
        demand_df,
        solar_capacity_kw=solar_capacity_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        battery_efficiency=battery_efficiency_pct / 100.0,
        mode=mode,
        min_soc_pct=min_soc_pct,
        peak_threshold_kw=peak_threshold_kw,
    )
    kpis = solar_simulator.calc_kpis(sim_df)

    n_days = max(1, (sim_df["datetime"].max() - sim_df["datetime"].min()).days + 1)
    annualize = 365.0 / n_days

    return RealDataMetrics(
        sim_df=sim_df,
        n_days_in_data=n_days,
        annual_consumption_kwh=kpis["total_demand_kwh"] * annualize,
        annual_generation_kwh=kpis["total_solar_kwh"] * annualize,
        self_consumption_rate_pct=kpis["self_consumption_rate"],
        self_sufficiency_rate_pct=kpis["self_sufficiency_rate"],
        grid_import_kwh_annual=kpis["total_grid_import_kwh"] * annualize,
        grid_export_kwh_annual=kpis["total_grid_export_kwh"] * annualize,
    )


def apply_real_data_metrics(inputs_dict: dict, metrics: RealDataMetrics) -> dict:
    """
    RealDataMetricsの実績値を、ppa_retail_calc.SimulationInputsのdict表現に書き込む。
    customer.annual_consumption_kwh / solar.generation_input_mode / direct_annual_generation_kwh /
    self_consumption_rate_pct を実績ベースの値で上書きする。

    注意: self_consumption_rate_pct には蓄電池による効果が実績値として既に反映されているため、
    蓄電池・エコキュート等の「自家消費率への上乗せ(pp)」は二重計上を避けるためゼロにする
    （エコキュートの自家消費効果はsolar_simulatorでモデル化されていないため、実データモードでは
    反映されない。これは既知の簡略化）。
    """
    inputs_dict["customer"]["annual_consumption_kwh"] = metrics.annual_consumption_kwh
    inputs_dict["solar"]["generation_input_mode"] = "direct_input"
    inputs_dict["solar"]["direct_annual_generation_kwh"] = metrics.annual_generation_kwh
    inputs_dict["solar"]["self_consumption_rate_pct"] = metrics.self_consumption_rate_pct
    inputs_dict["solar"]["battery_self_consumption_boost_pct"] = 0.0
    inputs_dict["solar"]["heat_pump_self_consumption_boost_pct"] = 0.0
    return inputs_dict
