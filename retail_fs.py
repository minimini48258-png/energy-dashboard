"""
retail_fs.py
小売電気事業の FS（事業性）試算モジュール。

既存の financial_model.py（需給バランス・簡易収支）に対して、
- 施設ごとの契約電力・電圧区分・料金プラン（基本料金＋従量料金）
- 電圧区分別の託送料金（基本＋従量）
- 燃料費調整・再エネ賦課金
- 容量拠出金（簡易：単価×契約kW）
- CO2排出量・地産電源比率
- JEPX市場価格の感度分析
を組み込み、より実務に近い損益計算書ふうの試算を行う。

計算式は「電力小売FS 収支試算ツール 使い方ガイド」12章（計算のしくみ）に準拠：
    売上総利益（粗利益） = 売上高 - 再エネ賦課金（納付） - (電力調達費 + 託送料金 + 容量拠出金)
    売上高 = 基本料金 + 従量料金 + 燃料費調整額 + 再エネ賦課金 + 市場売却収入

料金プランの季節別・累進段階別モードのデフォルト値は、中部電力ミライズの公開料金
（2026年7月 Web調査、※要確認。実際の契約単価は同社公式サイトの最新料金表で確認のこと）:
  - 高圧業務用電力(FRプラン相当): 基本料金 約1,716.26〜2,002.26円/kW、
    電力量料金 夏季(7-9月) 約18.97〜20.30円/kWh、その他季 約18.00〜19.21円/kWh
  - 従量電灯B: 電力量料金 第1段階(〜120kWh)21.20円、第2段階(120〜300kWh)25.67円、
    第3段階(300kWh超)28.62円/kWh
  - 再エネ発電促進賦課金: 経済産業省公表 2026年5月〜2027年4月 4.18円/kWh
を参考値として採用している。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

FACILITY_CONFIG_FILE = Path("/tmp/energy_dashboard/retail_fs_facilities.json")
TARIFF_PLAN_FILE = Path("/tmp/energy_dashboard/retail_fs_tariffs.json")
FS_DESIGN_FILE = Path("/tmp/energy_dashboard/fs_design.json")

VOLTAGE_CLASSES: list[str] = ["低圧", "高圧", "特別高圧"]

# 時間帯別プランで使う昼夜2区分（時）
DAY_HOURS   = list(range(8, 22))   # 8-22時
NIGHT_HOURS = [h for h in range(24) if h not in DAY_HOURS]

# 季節別プランで使う夏季区分（中部電力の標準的な区分：7〜9月）
SUMMER_MONTHS = {7, 8, 9}

# JEPX残差（市場調達分）の排出係数の目安値（kg-CO2/kWh）。ガイド記載の取引所係数を参照。
JEPX_EMISSION_FACTOR = 0.472

# 電源種別ごとのデフォルト排出係数の目安（kg-CO2/kWh）。再エネはゼロとして扱う簡易モデル。
DEFAULT_SOURCE_EMISSION_FACTOR: dict[str, float] = {
    "hydro": 0.0,
    "solar": 0.0,
    "biomass": 0.0,
    "other": 0.437,
}


# ---------------------------------------------------------------------------
# データモデル
# ---------------------------------------------------------------------------

@dataclass
class TariffPlan:
    """販売単価プラン（基本料金＋従量料金）。"""
    name: str
    voltage_class: str = "高圧"
    basic_yen_per_kw: float = 1_000.0        # 基本料金単価（円/kW・月）
    volumetric_mode: str = "flat"             # "flat"一律 | "tou"昼夜2区分 | "seasonal"季節別2区分 | "tiered"累進段階制
    flat_rate: float = 25.0                   # 一律単価（円/kWh）
    day_rate: float = 27.0                    # 時間帯別：昼間（8-22時）単価（円/kWh）
    night_rate: float = 18.0                  # 時間帯別：夜間（22-8時）単価（円/kWh）
    summer_rate: float = 19.6                 # 季節別：夏季（7-9月）単価（円/kWh）※要確認
    other_rate: float = 18.6                  # 季節別：その他季単価（円/kWh）※要確認
    tiered_rates: list[tuple[Optional[float], float]] = field(
        default_factory=lambda: [(120.0, 21.20), (300.0, 25.67), (None, 28.62)]
    )  # 累進段階制：(上限kWh, 単価円/kWh) を段階順に。最終段は上限None ※要確認
    power_factor_discount: bool = True        # 高圧・特別高圧の力率割引/割増（基準85%・1pt=1%）を適用するか


@dataclass
class FacilityConfig:
    """施設ごとの契約情報。"""
    facility_name: str
    contract_kw: float = 0.0
    voltage_class: str = "高圧"
    power_factor_pct: float = 100.0
    tariff_plan_name: str = ""


@dataclass
class TransmissionRate:
    """電圧区分別の託送料金単価。"""
    voltage_class: str
    basic_yen_per_kw: float = 0.0
    volumetric_yen_per_kwh: float = 0.0


def default_tariff_plans() -> list[TariffPlan]:
    """
    電圧区分ごとのサンプル料金プラン。
    低圧・高圧は中部電力ミライズの公開料金（従量電灯B・高圧業務用電力）を参考にした
    目安値、特別高圧は一般的な水準の目安値（いずれも※要確認）。
    """
    return [
        TariffPlan(name="標準プラン（低圧・従量電灯B型）", voltage_class="低圧",
                   basic_yen_per_kw=0.0, volumetric_mode="tiered",
                   tiered_rates=[(120.0, 21.20), (300.0, 25.67), (None, 28.62)],
                   power_factor_discount=False),
        TariffPlan(name="標準プラン（高圧・季節別）", voltage_class="高圧",
                   basic_yen_per_kw=1_860.0, volumetric_mode="seasonal",
                   summer_rate=19.6, other_rate=18.6),
        TariffPlan(name="標準プラン（特別高圧）", voltage_class="特別高圧",
                   basic_yen_per_kw=1_600.0, volumetric_mode="tou", day_rate=16.0, night_rate=11.5),
    ]


def default_transmission_rates() -> dict[str, TransmissionRate]:
    """託送料金の初期値（目安値）。エリア・年度で実際の単価は異なるため必ず確認・編集してください。"""
    return {
        "低圧":    TransmissionRate("低圧",    basic_yen_per_kw=0.0,    volumetric_yen_per_kwh=8.5),
        "高圧":    TransmissionRate("高圧",    basic_yen_per_kw=650.0,  volumetric_yen_per_kwh=3.0),
        "特別高圧": TransmissionRate("特別高圧", basic_yen_per_kw=500.0,  volumetric_yen_per_kwh=1.5),
    }


# ---------------------------------------------------------------------------
# 永続化（/tmp 配下の JSON。他モジュール（grouping.py 等）と同じ方式）
# ---------------------------------------------------------------------------

def save_facility_configs(configs: list[FacilityConfig]) -> None:
    FACILITY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    FACILITY_CONFIG_FILE.write_text(
        json.dumps([asdict(c) for c in configs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_facility_configs() -> list[FacilityConfig]:
    if not FACILITY_CONFIG_FILE.exists():
        return []
    try:
        return [FacilityConfig(**d) for d in json.loads(FACILITY_CONFIG_FILE.read_text("utf-8"))]
    except Exception:
        return []


def save_tariff_plans(plans: list[TariffPlan]) -> None:
    TARIFF_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TARIFF_PLAN_FILE.write_text(
        json.dumps([asdict(p) for p in plans], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_fs_design(design: dict) -> None:
    """シナリオ設計一式（料金プラン・施設設定を除く③〜⑦の前提条件）を保存する。"""
    FS_DESIGN_FILE.parent.mkdir(parents=True, exist_ok=True)
    FS_DESIGN_FILE.write_text(
        json.dumps(design, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_fs_design() -> dict:
    if not FS_DESIGN_FILE.exists():
        return {}
    try:
        return json.loads(FS_DESIGN_FILE.read_text("utf-8"))
    except Exception:
        return {}


def load_tariff_plans() -> list[TariffPlan]:
    if not TARIFF_PLAN_FILE.exists():
        return []
    try:
        return [TariffPlan(**d) for d in json.loads(TARIFF_PLAN_FILE.read_text("utf-8"))]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 契約電力の目安値
# ---------------------------------------------------------------------------

def suggest_contract_kw(demand_df: pd.DataFrame, facility_name: str) -> float:
    """施設の30分値実績からピークkWを推計し、契約電力の目安値（10kW単位で切上げ）を返す。"""
    fac = demand_df[demand_df["facility_name"] == facility_name]
    if fac.empty:
        return 10.0
    peak_kw = float(fac["consumption_kwh"].max()) * 2  # 30分kWh → kW
    if peak_kw <= 0:
        return 10.0
    import math
    return float(max(10, math.ceil(peak_kw / 10) * 10))


def power_factor_multiplier(power_factor_pct: float) -> float:
    """高圧・特別高圧の力率割引/割増率（基準85%・1ポイントごとに1%）。"""
    return 1.0 - (power_factor_pct - 85.0) / 100.0


# ---------------------------------------------------------------------------
# 収入（施設別・料金プラン適用）
# ---------------------------------------------------------------------------

def _rate_series(dt: pd.Series, plan: TariffPlan) -> pd.Series:
    if plan.volumetric_mode == "tou":
        hours = dt.dt.hour
        return hours.map(lambda h: plan.day_rate if h in DAY_HOURS else plan.night_rate).astype(float)
    if plan.volumetric_mode == "seasonal":
        months = dt.dt.month
        return months.map(lambda m: plan.summer_rate if m in SUMMER_MONTHS else plan.other_rate).astype(float)
    return pd.Series(plan.flat_rate, index=dt.index, dtype=float)


def _tiered_energy_charge(total_kwh: float, tiered_rates: list[tuple[Optional[float], float]]) -> float:
    """月間累積kWhに対する累進段階制の電力量料金（円）を計算する。"""
    remaining = total_kwh
    lower = 0.0
    charge = 0.0
    for upper, price in tiered_rates:
        if remaining <= 0:
            break
        band = (upper - lower) if upper is not None else remaining
        used = min(remaining, band)
        charge += used * price
        remaining -= used
        if upper is not None:
            lower = upper
    return charge


def calc_facility_revenue(
    demand_df: pd.DataFrame,
    facility_configs: list[FacilityConfig],
    tariff_plans: list[TariffPlan],
    fuel_adjustment_yen_per_kwh: float,
    renewable_levy_yen_per_kwh: float,
) -> pd.DataFrame:
    """
    施設×月 単位の売上内訳（基本料金・従量料金・燃調・賦課金）を計算する。

    Returns
    -------
    DataFrame: facility_name, month, kwh, basic_revenue, volumetric_revenue,
               fuel_adj_revenue, levy_revenue, total_revenue
    """
    plan_map = {p.name: p for p in tariff_plans}
    cfg_map = {c.facility_name: c for c in facility_configs}
    rows = []

    for facility_name, fac_df in demand_df.groupby("facility_name"):
        cfg = cfg_map.get(facility_name)
        if cfg is None or not cfg.tariff_plan_name or cfg.tariff_plan_name not in plan_map:
            continue
        plan = plan_map[cfg.tariff_plan_name]

        work = fac_df.copy()
        work["month"] = work["datetime"].dt.to_period("M").dt.to_timestamp()
        work["fuel_adj_revenue"] = work["consumption_kwh"] * fuel_adjustment_yen_per_kwh
        work["levy_revenue"] = work["consumption_kwh"] * renewable_levy_yen_per_kwh

        if plan.volumetric_mode == "tiered":
            # 累進段階制：月間累積kWhに対して段階単価を適用するため、月次kWh確定後に計算する
            work["volumetric_revenue"] = 0.0
        else:
            work["rate"] = _rate_series(work["datetime"], plan)
            work["volumetric_revenue"] = work["consumption_kwh"] * work["rate"]

        pf_mult = (
            power_factor_multiplier(cfg.power_factor_pct)
            if plan.power_factor_discount and cfg.voltage_class in ("高圧", "特別高圧")
            else 1.0
        )
        basic_per_month = cfg.contract_kw * plan.basic_yen_per_kw * pf_mult

        monthly = (
            work.groupby("month", as_index=False)
            .agg(
                kwh=("consumption_kwh", "sum"),
                volumetric_revenue=("volumetric_revenue", "sum"),
                fuel_adj_revenue=("fuel_adj_revenue", "sum"),
                levy_revenue=("levy_revenue", "sum"),
            )
        )
        if plan.volumetric_mode == "tiered":
            monthly["volumetric_revenue"] = monthly["kwh"].apply(
                lambda kwh: _tiered_energy_charge(kwh, plan.tiered_rates)
            )
        monthly["facility_name"] = facility_name
        monthly["basic_revenue"] = basic_per_month
        monthly["total_revenue"] = (
            monthly["basic_revenue"] + monthly["volumetric_revenue"]
            + monthly["fuel_adj_revenue"] + monthly["levy_revenue"]
        )
        rows.append(monthly)

    if not rows:
        return pd.DataFrame(columns=[
            "facility_name", "month", "kwh", "basic_revenue", "volumetric_revenue",
            "fuel_adj_revenue", "levy_revenue", "total_revenue",
        ])
    return pd.concat(rows, ignore_index=True).sort_values(["facility_name", "month"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 託送料金・容量拠出金
# ---------------------------------------------------------------------------

def calc_transmission_cost(
    demand_df: pd.DataFrame,
    facility_configs: list[FacilityConfig],
    transmission_rates: dict[str, TransmissionRate],
) -> pd.DataFrame:
    """施設×月 単位の託送料金を計算する。"""
    cfg_map = {c.facility_name: c for c in facility_configs}
    rows = []

    for facility_name, fac_df in demand_df.groupby("facility_name"):
        cfg = cfg_map.get(facility_name)
        if cfg is None:
            continue
        rate = transmission_rates.get(cfg.voltage_class)
        if rate is None:
            continue

        work = fac_df.copy()
        work["month"] = work["datetime"].dt.to_period("M").dt.to_timestamp()
        pf_mult = (
            power_factor_multiplier(cfg.power_factor_pct)
            if cfg.voltage_class in ("高圧", "特別高圧")
            else 1.0
        )
        basic_per_month = cfg.contract_kw * rate.basic_yen_per_kw * pf_mult

        monthly = work.groupby("month", as_index=False)["consumption_kwh"].sum()
        monthly["facility_name"] = facility_name
        monthly["basic_cost"] = basic_per_month
        monthly["volumetric_cost"] = monthly["consumption_kwh"] * rate.volumetric_yen_per_kwh
        monthly["transmission_cost"] = monthly["basic_cost"] + monthly["volumetric_cost"]
        rows.append(monthly[["facility_name", "month", "transmission_cost"]])

    if not rows:
        return pd.DataFrame(columns=["facility_name", "month", "transmission_cost"])
    return pd.concat(rows, ignore_index=True).sort_values(["facility_name", "month"]).reset_index(drop=True)


def calc_capacity_contribution(
    facility_configs: list[FacilityConfig],
    unit_yen_per_kw_year: float,
) -> float:
    """
    容量拠出金の簡易試算（年額）＝ 契約kW合計 × 単価（円/kW・年）。
    OCCTO公表のエリア負担総額×ピークシェア方式の近似（フォールバック方式）。
    """
    total_kw = sum(c.contract_kw for c in facility_configs)
    return total_kw * unit_yen_per_kw_year


# ---------------------------------------------------------------------------
# 販管費・法人税
# ---------------------------------------------------------------------------

def default_sga_items() -> dict[str, float]:
    """販管費の代表的な費目と初期値（年額・円）。実際の水準は事業計画に合わせて入力する。"""
    return {
        "人件費": 0.0,
        "システム費": 0.0,
        "委託費": 0.0,
        "家賃": 0.0,
    }


# 法人税等の実効税率の目安（中小法人、標準的なケース）※要確認。
# 実際の税率は資本金・所得区分・地方税率により変動するため、必ず税理士等に確認のこと。
DEFAULT_CORPORATE_TAX_RATE_PCT = 30.0


# ---------------------------------------------------------------------------
# 電力調達費（自社電源＋JEPX残差、予備費率を上乗せ）
# ---------------------------------------------------------------------------

def calc_procurement_cost(
    balance_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    source_costs: dict[str, float],
    jepx_price_by_month_hour: dict[tuple[int, int], float],
    reserve_margin_pct: float,
    jepx_actual_series: pd.Series | None = None,
    fip_indexed_sources: dict[str, bool] | None = None,
) -> pd.DataFrame:
    """
    30分コマ単位の電力調達費を計算する（月次に集約して返す）。
    電力調達費 = (自社電源コスト + JEPX残差調達費) × (1 + 予備費率)

    jepx_actual_series  : 実績JEPX価格（datetime→円/kWh）。値がある30分コマは
                           こちらを優先し、欠損コマは jepx_price_by_month_hour を使う
    fip_indexed_sources : {電源名: True} の電源は、source_costs の値を固定単価ではなく
                           「その時刻のJEPXスポット価格に上乗せするスプレッド（円/kWh）」として扱う
                           （FIP転した相対電源からの買取などを想定）。
    """
    fip_indexed_sources = fip_indexed_sources or {}
    df = balance_df.copy()
    df["_cal_month"] = df["datetime"].dt.month
    df["hour"] = df["datetime"].dt.hour
    df["jepx_price"] = [
        jepx_price_by_month_hour.get((m, h), 15.0) for m, h in zip(df["_cal_month"], df["hour"])
    ]
    if jepx_actual_series is not None and not jepx_actual_series.empty:
        actual_vals = df["datetime"].map(jepx_actual_series)
        df["jepx_price"] = actual_vals.combine_first(df["jepx_price"])
    df["jepx_cost"] = df["deficit_kwh"] * df["jepx_price"]

    if not supply_df.empty and source_costs:
        _supply = supply_df.copy()
        _fip_names = {name for name, is_fip in fip_indexed_sources.items() if is_fip}
        _is_fip = _supply["source_name"].isin(_fip_names)

        _flat = _supply[~_is_fip].copy()
        _flat["cost"] = _flat["source_name"].map(source_costs).fillna(0.0) * _flat["supply_kwh"]

        _fip = _supply[_is_fip].copy()
        if not _fip.empty:
            _jepx_price_map = df.set_index("datetime")["jepx_price"]
            _fip["jepx_price_at_ts"] = _fip["datetime"].map(_jepx_price_map).fillna(15.0)
            _fip["spread"] = _fip["source_name"].map(source_costs).fillna(0.0)
            _fip["cost"] = (_fip["jepx_price_at_ts"] + _fip["spread"]) * _fip["supply_kwh"]
        else:
            _fip["cost"] = pd.Series(dtype=float)

        _combined = pd.concat([_flat[["datetime", "cost"]], _fip[["datetime", "cost"]]], ignore_index=True)
        gen_cost = (
            _combined.groupby("datetime", as_index=False)["cost"].sum().rename(columns={"cost": "gen_cost"})
        )
        df = pd.merge(df, gen_cost, on="datetime", how="left")
        df["gen_cost"] = df["gen_cost"].fillna(0.0)
    else:
        df["gen_cost"] = 0.0

    df["procurement_cost"] = (df["jepx_cost"] + df["gen_cost"]) * (1 + reserve_margin_pct / 100.0)
    df["market_sale_revenue"] = df["surplus_kwh"] * df["jepx_price"]

    df["month"] = df["datetime"].dt.to_period("M").dt.to_timestamp()
    return df.groupby("month", as_index=False)[
        ["jepx_cost", "gen_cost", "procurement_cost", "market_sale_revenue"]
    ].sum()


# ---------------------------------------------------------------------------
# 統合試算
# ---------------------------------------------------------------------------

def run_fs(
    demand_df: pd.DataFrame,
    balance_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    facility_configs: list[FacilityConfig],
    tariff_plans: list[TariffPlan],
    transmission_rates: dict[str, TransmissionRate],
    source_costs: dict[str, float],
    jepx_price_by_month_hour: dict[tuple[int, int], float],
    fuel_adjustment_yen_per_kwh: float,
    renewable_levy_yen_per_kwh: float,
    capacity_unit_yen_per_kw_year: float,
    reserve_margin_pct: float,
    jepx_actual_series: pd.Series | None = None,
    sga_items: dict[str, float] | None = None,
    corporate_tax_rate_pct: float = DEFAULT_CORPORATE_TAX_RATE_PCT,
    fip_indexed_sources: dict[str, bool] | None = None,
) -> dict:
    """
    小売FSの一括試算。月別・年間サマリーの損益計算書ふうの結果を返す。

    売上総利益（粗利益） = 売上高 - 再エネ賦課金（納付） - (電力調達費 + 託送料金 + 容量拠出金)
    営業利益 = 売上総利益（粗利益） - 販管費
    法人税等 = max(営業利益, 0) × 実効税率（簡易計算。赤字時は0円、繰越欠損金等は考慮しない）
    当期純利益 = 営業利益 - 法人税等

    sga_items            : 販管費の費目別年額（円）。例: {"人件費": ..., "システム費": ..., "委託費": ..., "家賃": ...}
    corporate_tax_rate_pct: 法人税等の実効税率（%）※要確認・簡易計算
    fip_indexed_sources   : {電源名: True} の電源は、source_costs をJEPX価格へのスプレッドとして扱う
                             （FIP転した相対電源の買取などを想定）
    """
    revenue_df = calc_facility_revenue(
        demand_df, facility_configs, tariff_plans,
        fuel_adjustment_yen_per_kwh, renewable_levy_yen_per_kwh,
    )
    transmission_df = calc_transmission_cost(demand_df, facility_configs, transmission_rates)
    procurement_df = calc_procurement_cost(
        balance_df, supply_df, source_costs, jepx_price_by_month_hour, reserve_margin_pct,
        jepx_actual_series=jepx_actual_series, fip_indexed_sources=fip_indexed_sources,
    )

    n_months = max(procurement_df["month"].nunique(), 1) if not procurement_df.empty else 1
    capacity_annual = calc_capacity_contribution(facility_configs, capacity_unit_yen_per_kw_year)
    capacity_monthly = capacity_annual / 12.0

    rev_monthly = revenue_df.groupby("month", as_index=False)[
        ["kwh", "basic_revenue", "volumetric_revenue", "fuel_adj_revenue", "levy_revenue", "total_revenue"]
    ].sum() if not revenue_df.empty else pd.DataFrame(
        columns=["month", "kwh", "basic_revenue", "volumetric_revenue", "fuel_adj_revenue", "levy_revenue", "total_revenue"]
    )
    trans_monthly = transmission_df.groupby("month", as_index=False)["transmission_cost"].sum() \
        if not transmission_df.empty else pd.DataFrame(columns=["month", "transmission_cost"])

    monthly = pd.merge(rev_monthly, trans_monthly, on="month", how="outer")
    monthly = pd.merge(monthly, procurement_df, on="month", how="outer").sort_values("month").fillna(0.0)
    # outer merge で片方が空フレームの場合、"month" や数値列が object 型になることがあるため明示的に型を戻す
    monthly["month"] = pd.to_datetime(monthly["month"])
    _numeric_cols = [c for c in monthly.columns if c != "month"]
    monthly[_numeric_cols] = monthly[_numeric_cols].astype(float)
    monthly["capacity_contribution"] = capacity_monthly
    monthly["sales_revenue"] = monthly["total_revenue"] + monthly["market_sale_revenue"]
    monthly["cost_of_sales"] = (
        monthly["procurement_cost"] + monthly["transmission_cost"] + monthly["capacity_contribution"]
    )
    monthly["gross_profit"] = (
        monthly["sales_revenue"] - monthly["levy_revenue"] - monthly["cost_of_sales"]
    )
    monthly["gross_margin_pct"] = (
        (monthly["gross_profit"] / monthly["sales_revenue"] * 100).where(monthly["sales_revenue"] != 0, 0.0)
    )

    sga_annual_total = sum((sga_items or {}).values())
    monthly["sga_cost"] = sga_annual_total / 12.0
    monthly["operating_profit"] = monthly["gross_profit"] - monthly["sga_cost"]

    annual = {
        "kwh": float(monthly["kwh"].sum()),
        "basic_revenue": float(monthly["basic_revenue"].sum()),
        "volumetric_revenue": float(monthly["volumetric_revenue"].sum()),
        "fuel_adj_revenue": float(monthly["fuel_adj_revenue"].sum()),
        "levy_revenue": float(monthly["levy_revenue"].sum()),
        "market_sale_revenue": float(monthly["market_sale_revenue"].sum()),
        "sales_revenue": float(monthly["sales_revenue"].sum()),
        "jepx_cost": float(monthly["jepx_cost"].sum()),
        "gen_cost": float(monthly["gen_cost"].sum()),
        "procurement_cost": float(monthly["procurement_cost"].sum()),
        "transmission_cost": float(monthly["transmission_cost"].sum()),
        "capacity_contribution": float(capacity_annual) * (n_months / 12.0),
        "cost_of_sales": float(monthly["cost_of_sales"].sum()),
        "gross_profit": float(monthly["gross_profit"].sum()),
        "contract_kw_total": sum(c.contract_kw for c in facility_configs),
        "n_months": n_months,
    }
    annual["gross_margin_pct"] = (
        annual["gross_profit"] / annual["sales_revenue"] * 100 if annual["sales_revenue"] else 0.0
    )

    annual["sga_cost"] = float(monthly["sga_cost"].sum())
    annual["sga_breakdown"] = dict(sga_items or {})
    annual["operating_profit"] = annual["gross_profit"] - annual["sga_cost"]
    annual["corporate_tax"] = max(annual["operating_profit"], 0.0) * (corporate_tax_rate_pct / 100.0)
    annual["net_income"] = annual["operating_profit"] - annual["corporate_tax"]
    annual["operating_margin_pct"] = (
        annual["operating_profit"] / annual["sales_revenue"] * 100 if annual["sales_revenue"] else 0.0
    )
    annual["net_margin_pct"] = (
        annual["net_income"] / annual["sales_revenue"] * 100 if annual["sales_revenue"] else 0.0
    )

    # 法人税等は年間ベースで確定させたうえで、月数で均等按分する（月別クリップによる乖離を避けるため）
    monthly["corporate_tax"] = annual["corporate_tax"] / max(n_months, 1)
    monthly["net_income"] = monthly["operating_profit"] - monthly["corporate_tax"]

    return {
        "monthly": monthly,
        "annual": annual,
        "facility_revenue": revenue_df,
        "facility_transmission": transmission_df,
    }


# ---------------------------------------------------------------------------
# 施設別収支
# ---------------------------------------------------------------------------

def calc_facility_pl(
    facility_revenue_df: pd.DataFrame,
    facility_transmission_df: pd.DataFrame,
    annual: dict,
) -> pd.DataFrame:
    """
    施設別の収支（期間合計）を試算する。
    託送料金は施設ごとの実額、電力調達費・容量拠出金はkWh実績に応じた按分（簡易配賦）。

    Returns
    -------
    DataFrame: facility_name, kwh, revenue, transmission_cost,
               allocated_cost, cost_of_sales, gross_profit, gross_margin_pct
    """
    if facility_revenue_df.empty:
        return pd.DataFrame(columns=[
            "facility_name", "kwh", "revenue", "transmission_cost",
            "allocated_cost", "cost_of_sales", "gross_profit", "gross_margin_pct",
        ])

    rev = facility_revenue_df.groupby("facility_name", as_index=False).agg(
        kwh=("kwh", "sum"), revenue=("total_revenue", "sum"),
    )
    if not facility_transmission_df.empty:
        trans = facility_transmission_df.groupby("facility_name", as_index=False)["transmission_cost"].sum()
    else:
        trans = pd.DataFrame(columns=["facility_name", "transmission_cost"])

    fac_df = pd.merge(rev, trans, on="facility_name", how="left").fillna({"transmission_cost": 0.0})

    total_kwh = float(fac_df["kwh"].sum())
    poolable_cost = float(annual.get("procurement_cost", 0.0)) + float(annual.get("capacity_contribution", 0.0))
    fac_df["allocated_cost"] = (
        (fac_df["kwh"] / total_kwh * poolable_cost) if total_kwh > 0 else 0.0
    )
    fac_df["cost_of_sales"] = fac_df["transmission_cost"] + fac_df["allocated_cost"]
    fac_df["gross_profit"] = fac_df["revenue"] - fac_df["cost_of_sales"]
    fac_df["gross_margin_pct"] = (
        (fac_df["gross_profit"] / fac_df["revenue"] * 100).where(fac_df["revenue"] != 0, 0.0)
    )
    return fac_df.sort_values("revenue", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 資金繰り（月次キャッシュフロー）
# ---------------------------------------------------------------------------

def calc_cash_flow(
    monthly_df: pd.DataFrame,
    capital_yen: float,
    revenue_collection_lag_months: int = 0,
) -> pd.DataFrame:
    """
    月次キャッシュフローの簡易試算。
    売上代金の入金は revenue_collection_lag_months ヶ月遅れて発生すると仮定する
    （利用料回収のタイムラグ）。費用側（電力調達費・託送料金・容量拠出金・販管費・
    再エネ賦課金納付・法人税等）は発生月に支払われるものとする（簡易モデル・※要確認）。
    減価償却・設備投資・売掛金以外の運転資本の変動は考慮しない。
    現金残高は資本金からスタートする：1ヶ月目の期首残高＝資本金、
    期末残高＝期首残高＋当月キャッシュフロー、翌月の期首残高＝前月の期末残高。
    """
    cf = monthly_df[
        ["month", "sales_revenue", "levy_revenue", "cost_of_sales", "sga_cost", "corporate_tax"]
    ].copy().sort_values("month").reset_index(drop=True)

    cf["cash_in"] = cf["sales_revenue"].shift(revenue_collection_lag_months).fillna(0.0)
    cf["cash_out"] = cf["cost_of_sales"] + cf["levy_revenue"] + cf["sga_cost"] + cf["corporate_tax"]
    cf["net_cash_flow"] = cf["cash_in"] - cf["cash_out"]
    cf["opening_balance"] = capital_yen + cf["net_cash_flow"].cumsum().shift(1).fillna(0.0)
    cf["closing_balance"] = cf["opening_balance"] + cf["net_cash_flow"]
    cf["cash_balance"] = cf["closing_balance"]  # 既存呼び出し元との互換用（期末残高と同じ）

    return cf[["month", "cash_in", "cash_out", "net_cash_flow", "opening_balance", "closing_balance", "cash_balance"]]


def sensitivity_jepx_shift(
    balance_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    source_costs: dict[str, float],
    jepx_price_by_month_hour: dict[tuple[int, int], float],
    reserve_margin_pct: float,
    base_gross_profit: float,
    other_revenue: float,
    other_cost: float,
    shifts: list[float] | None = None,
    fip_indexed_sources: dict[str, bool] | None = None,
) -> pd.DataFrame:
    """
    JEPX価格を一律 ±shift 円/kWh 動かした場合の売上総利益（粗利益）の変化を試算する。
    other_revenue = 基本+従量+燃調 の合計（levy は相殺されるため除く）
    other_cost     = 託送料金 + 容量拠出金
    JEPX価格連動電源（fip_indexed_sources）の調達費も、価格シフトに応じて自動的に変動する。
    """
    shifts = shifts if shifts is not None else [-5, -3, -1, 0, 1, 3, 5]
    rows = []
    for shift in shifts:
        shifted_prices = {k: max(p + shift, 0.0) for k, p in jepx_price_by_month_hour.items()}
        proc = calc_procurement_cost(
            balance_df, supply_df, source_costs, shifted_prices, reserve_margin_pct,
            fip_indexed_sources=fip_indexed_sources,
        )
        procurement_cost = float(proc["procurement_cost"].sum())
        market_sale = float(proc["market_sale_revenue"].sum())
        gross_profit = (other_revenue + market_sale) - (other_cost + procurement_cost)
        rows.append({
            "shift_yen": shift,
            "gross_profit": gross_profit,
            "diff_from_base": gross_profit - base_gross_profit,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CO2・地産電源比率
# ---------------------------------------------------------------------------

def calc_co2_and_local_ratio(
    balance_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    source_emission_factors: dict[str, float],
    source_is_local: dict[str, bool],
) -> dict:
    """
    CO2排出量[t-CO2]と地産電源比率を計算する。
    JEPX残差（市場調達分）は目安の取引所係数（JEPX_EMISSION_FACTOR）を使用。
    """
    total_deficit_kwh = float(balance_df["deficit_kwh"].sum())
    jepx_co2_kg = total_deficit_kwh * JEPX_EMISSION_FACTOR

    if not supply_df.empty:
        by_source = supply_df.groupby("source_name", as_index=False)["supply_kwh"].sum()
    else:
        by_source = pd.DataFrame(columns=["source_name", "supply_kwh"])

    owned_co2_kg = 0.0
    local_kwh = 0.0
    total_owned_kwh = float(by_source["supply_kwh"].sum()) if not by_source.empty else 0.0
    for _, row in by_source.iterrows():
        factor = source_emission_factors.get(row["source_name"], 0.0)
        owned_co2_kg += row["supply_kwh"] * factor
        if source_is_local.get(row["source_name"], False):
            local_kwh += row["supply_kwh"]

    total_procured_kwh = total_owned_kwh + total_deficit_kwh
    co2_total_t = (owned_co2_kg + jepx_co2_kg) / 1000.0
    local_ratio_pct = (local_kwh / total_procured_kwh * 100.0) if total_procured_kwh > 0 else 0.0

    return {
        "co2_total_t": round(co2_total_t, 2),
        "local_ratio_pct": round(local_ratio_pct, 1),
        "total_procured_kwh": round(total_procured_kwh, 1),
    }
