"""
ppa_retail_calc.py
「小売電気＋オンサイトPPA一体単価」事業の採算性計算エンジン。

設計方針（詳細は README_ppa.md 参照）：
  太陽光設備を事業者が自己所有し、顧客には太陽光由来／系統由来を区別しない
  一体単価（円/kWh）で課金するビジネスモデルを、「小売電気＋PPA＋余剰電力価値＋
  長期設備保有＋ファイナンス」を統合した事業モデルとして計算する。

二重計上防止の核（電力・お金の流れ）：
  恒等式①: 太陽光発電量 = 自家消費量 + 余剰電力量
  恒等式②: 顧客使用量   = 自家消費量 + 外部調達電力量
  顧客への請求は「顧客使用量 × 一体単価」の1本のみ。外部調達原価は外部調達電力量にのみ適用し、
  自家消費分の太陽光電力には適用しない（CapEx償却・O&M側で既にコストを計上しているため）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

GenerationInputMode = Literal["capacity_x_yield", "direct_input"]
TerminalTreatment = Literal["removal", "replacement", "residual_value"]
RepaymentMethod = Literal["equal_payment", "equal_principal"]
TerminationHandling = Literal["succession", "resell_surplus", "removal", "termination_fee"]
SurplusDestination = Literal["self_retail_portfolio", "market", "battery_charge"]
CustomerSegment = Literal["residential", "business"]


# =============================================================================
# 入力データモデル
#
# SolarAssetInputs（発電設備）と CustomerContractInputs（需要家契約）を分離している。
# MVPでは1設備=1契約で組み合わせて計算するが、将来「1設備の発電量を複数契約に配分する」
# ポートフォリオ型の拡張（§7）を妨げないための意図的な設計。
# =============================================================================


@dataclass
class CustomerContractInputs:
    segment: CustomerSegment = "residential"
    simulation_years: int = 20
    contract_years: int = 20
    unified_rate: float = 25.0            # PPA/小売一体単価 (円/kWh)
    tax_mode: Literal["tax_included", "tax_excluded"] = "tax_included"
    current_unit_price: float = 28.0      # 現在の顧客の平均電力単価 (円/kWh)
    current_price_escalation_rate_pct: float = 1.0
    annual_consumption_kwh: float = 6000.0
    consumption_growth_rate_pct: float = 0.0


@dataclass
class SolarAssetInputs:
    generation_input_mode: GenerationInputMode = "capacity_x_yield"
    capacity_kw: float = 6.0
    unit_cost_per_kw: float = 250_000.0
    subsidy_amount: float = 0.0
    annual_yield_per_kw: float = 1100.0
    direct_annual_generation_kwh: float = 6600.0
    degradation_rate_pct: float = 0.5
    self_consumption_rate_pct: float = 50.0
    useful_life_years: int = 20

    battery_enabled: bool = False
    battery_self_consumption_boost_pct: float = 15.0
    battery_cost: float = 1_200_000.0
    battery_annual_om: float = 5000.0

    heat_pump_enabled: bool = False
    heat_pump_self_consumption_boost_pct: float = 8.0
    heat_pump_cost: float = 450_000.0


@dataclass
class RetailCostInputs:
    grid_procurement_price: float = 15.0
    transmission_fee: float = 8.0
    capacity_contribution_fee: float = 1.0
    other_retail_cost: float = 1.0
    apply_renewable_levy: bool = True
    renewable_levy_rate: float = 3.5
    retail_cost_escalation_rate_pct: float = 1.0


@dataclass
class SurplusInputs:
    surplus_price: float = 8.0
    surplus_price_escalation_rate_pct: float = 0.0
    destination: SurplusDestination = "market"


@dataclass
class RepairScheduleItem:
    year: int
    amount: float
    label: str = ""


@dataclass
class MaintenanceInputs:
    om_mode: Literal["fixed", "pct_of_capex"] = "pct_of_capex"
    om_fixed_amount: float = 0.0
    om_pct_of_capex: float = 1.0

    inverter_replacement_year: Optional[int] = 12
    inverter_replacement_cost: float = 0.0

    repair_schedule: list[dict] = field(default_factory=list)  # [{"year", "amount", "label"}]

    insurance_mode: Literal["fixed", "pct_of_capex"] = "pct_of_capex"
    insurance_fixed_amount: float = 0.0
    insurance_pct_of_capex: float = 0.3

    management_fee_annual: float = 5000.0

    removal_cost: float = 150_000.0
    recycling_cost: float = 50_000.0
    replacement_cost: float = 1_500_000.0
    residual_value: float = 150_000.0

    terminal_treatment: TerminalTreatment = "residual_value"


@dataclass
class FinanceInputs:
    equity_ratio_pct: float = 40.0
    interest_rate_pct: float = 1.5
    loan_term_years: int = 15
    repayment_method: RepaymentMethod = "equal_payment"
    grace_period_years: int = 1
    loan_fee_pct: float = 1.0
    discount_rate_pct: float = 4.0
    target_project_irr_pct: float = 5.0
    target_equity_irr_pct: float = 8.0
    target_min_dscr: float = 1.2


@dataclass
class RiskInputs:
    annual_cancel_prob_pct: float = 0.0
    annual_bankruptcy_prob_pct: float = 0.0
    annual_relocation_prob_pct: float = 1.0
    termination_handling: TerminationHandling = "resell_surplus"
    succession_success_rate_pct: float = 50.0
    termination_fee_amount: float = 0.0


@dataclass
class SimulationInputs:
    customer: CustomerContractInputs = field(default_factory=CustomerContractInputs)
    solar: SolarAssetInputs = field(default_factory=SolarAssetInputs)
    retail: RetailCostInputs = field(default_factory=RetailCostInputs)
    surplus: SurplusInputs = field(default_factory=SurplusInputs)
    maintenance: MaintenanceInputs = field(default_factory=MaintenanceInputs)
    finance: FinanceInputs = field(default_factory=FinanceInputs)
    risk: RiskInputs = field(default_factory=RiskInputs)


def inputs_to_dict(inputs: SimulationInputs) -> dict:
    return asdict(inputs)


def inputs_from_dict(d: dict) -> SimulationInputs:
    return SimulationInputs(
        customer=CustomerContractInputs(**d.get("customer", {})),
        solar=SolarAssetInputs(**d.get("solar", {})),
        retail=RetailCostInputs(**d.get("retail", {})),
        surplus=SurplusInputs(**d.get("surplus", {})),
        maintenance=MaintenanceInputs(**d.get("maintenance", {})),
        finance=FinanceInputs(**d.get("finance", {})),
        risk=RiskInputs(**d.get("risk", {})),
    )


# =============================================================================
# 発電量・使用量
# =============================================================================


def compute_initial_investment(solar: SolarAssetInputs) -> float:
    """初期設備費 = 容量×単価 − 補助金（＋蓄電池・エコキュート費用）。"""
    solar_capex = solar.capacity_kw * solar.unit_cost_per_kw
    battery_capex = solar.battery_cost if solar.battery_enabled else 0.0
    heat_pump_capex = solar.heat_pump_cost if solar.heat_pump_enabled else 0.0
    return solar_capex - solar.subsidy_amount + battery_capex + heat_pump_capex


def compute_effective_self_consumption_rate_pct(solar: SolarAssetInputs) -> float:
    """自家消費率（蓄電池・エコキュートによる上乗せ込み、0〜100にクリップ）。"""
    rate = solar.self_consumption_rate_pct
    if solar.battery_enabled:
        rate += solar.battery_self_consumption_boost_pct
    if solar.heat_pump_enabled:
        rate += solar.heat_pump_self_consumption_boost_pct
    return min(100.0, max(0.0, rate))


def compute_annual_generation(solar: SolarAssetInputs, simulation_years: int) -> list[float]:
    """年間発電量(kWh)の配列。t年目 = 初年度発電量 × (1-経年劣化率)^(t-1)。"""
    if solar.generation_input_mode == "capacity_x_yield":
        year1 = solar.capacity_kw * solar.annual_yield_per_kw
    else:
        year1 = solar.direct_annual_generation_kwh
    degradation = solar.degradation_rate_pct / 100
    return [year1 * (1 - degradation) ** (t - 1) for t in range(1, simulation_years + 1)]


def compute_annual_consumption(customer: CustomerContractInputs) -> list[float]:
    """年間使用量(kWh)の配列。t年目 = 初年度使用量 × (1+増減率)^(t-1)。"""
    growth = customer.consumption_growth_rate_pct / 100
    return [
        customer.annual_consumption_kwh * (1 + growth) ** (t - 1)
        for t in range(1, customer.simulation_years + 1)
    ]


@dataclass
class EnergyFlowYear:
    generation_kwh: float
    consumption_kwh: float
    self_consumed_kwh: float
    surplus_kwh: float
    external_procurement_kwh: float


def compute_energy_flow(generation_kwh: float, consumption_kwh: float, self_consumption_rate_pct: float) -> EnergyFlowYear:
    """
    恒等式①: generation_kwh = self_consumed_kwh + surplus_kwh
    恒等式②: consumption_kwh = self_consumed_kwh + external_procurement_kwh
    """
    rate = min(100.0, max(0.0, self_consumption_rate_pct)) / 100
    raw_self_consumed = generation_kwh * rate
    self_consumed = min(raw_self_consumed, generation_kwh, consumption_kwh)
    surplus = generation_kwh - self_consumed
    external = consumption_kwh - self_consumed
    return EnergyFlowYear(generation_kwh, consumption_kwh, self_consumed, surplus, external)


def compute_energy_flow_series(
    generation_series: list[float], consumption_series: list[float], self_consumption_rate_pct: float
) -> list[EnergyFlowYear]:
    return [
        compute_energy_flow(gen, cons, self_consumption_rate_pct)
        for gen, cons in zip(generation_series, consumption_series)
    ]


# =============================================================================
# 顧客経済性
# =============================================================================


@dataclass
class CustomerEconomicsYear:
    year: int
    consumption_kwh: float
    current_cost: float
    new_cost: float
    saving: float


def compute_customer_economics(
    customer: CustomerContractInputs, consumption_series: list[float]
) -> list[CustomerEconomicsYear]:
    """現在: 使用量×現在単価×(1+上昇率)^(t-1) / 新プラン: 使用量×一体単価（契約期間中は固定）。"""
    escalation = customer.current_price_escalation_rate_pct / 100
    result = []
    for i, kwh in enumerate(consumption_series):
        year = i + 1
        current_price = customer.current_unit_price * (1 + escalation) ** (year - 1)
        current_cost = kwh * current_price
        new_cost = kwh * customer.unified_rate
        result.append(CustomerEconomicsYear(year, kwh, current_cost, new_cost, current_cost - new_cost))
    return result


# =============================================================================
# 外部調達原価・余剰電力単価
# =============================================================================


def compute_procurement_unit_cost_series(retail: RetailCostInputs, simulation_years: int) -> list[float]:
    """外部調達電力量にのみ適用する単価系列（再エネ賦課金も外部調達分のみという前提）。"""
    base = (
        retail.grid_procurement_price
        + retail.transmission_fee
        + retail.capacity_contribution_fee
        + retail.other_retail_cost
        + (retail.renewable_levy_rate if retail.apply_renewable_levy else 0.0)
    )
    escalation = retail.retail_cost_escalation_rate_pct / 100
    return [base * (1 + escalation) ** (t - 1) for t in range(1, simulation_years + 1)]


def compute_surplus_price_series(surplus: SurplusInputs, simulation_years: int) -> list[float]:
    escalation = surplus.surplus_price_escalation_rate_pct / 100
    return [surplus.surplus_price * (1 + escalation) ** (t - 1) for t in range(1, simulation_years + 1)]


# =============================================================================
# 維持管理費・最終年度処理
# =============================================================================


@dataclass
class OpexYear:
    om_cost: float
    insurance_cost: float
    management_cost: float
    repair_cost: float
    inverter_replacement_cost: float
    removal_recycling_cost: float
    replacement_cost: float
    residual_value_inflow: float


def compute_opex_series(
    maintenance: MaintenanceInputs, solar: SolarAssetInputs, initial_investment: float, simulation_years: int
) -> list[OpexYear]:
    battery_om = solar.battery_annual_om if solar.battery_enabled else 0.0
    om_annual = (
        maintenance.om_fixed_amount
        if maintenance.om_mode == "fixed"
        else initial_investment * (maintenance.om_pct_of_capex / 100)
    ) + battery_om
    insurance_annual = (
        maintenance.insurance_fixed_amount
        if maintenance.insurance_mode == "fixed"
        else initial_investment * (maintenance.insurance_pct_of_capex / 100)
    )

    repair_by_year: dict[int, float] = {}
    for item in maintenance.repair_schedule:
        y = int(item["year"])
        repair_by_year[y] = repair_by_year.get(y, 0.0) + float(item["amount"])

    result = []
    for t in range(1, simulation_years + 1):
        is_last_year = t == simulation_years
        inverter_cost = (
            maintenance.inverter_replacement_cost
            if maintenance.inverter_replacement_year == t
            else 0.0
        )

        removal_recycling_cost = 0.0
        replacement_cost = 0.0
        residual_value_inflow = 0.0
        if is_last_year:
            if maintenance.terminal_treatment == "removal":
                removal_recycling_cost = maintenance.removal_cost + maintenance.recycling_cost
            elif maintenance.terminal_treatment == "replacement":
                replacement_cost = maintenance.replacement_cost
            elif maintenance.terminal_treatment == "residual_value":
                residual_value_inflow = maintenance.residual_value

        result.append(
            OpexYear(
                om_cost=om_annual,
                insurance_cost=insurance_annual,
                management_cost=maintenance.management_fee_annual,
                repair_cost=repair_by_year.get(t, 0.0),
                inverter_replacement_cost=inverter_cost,
                removal_recycling_cost=removal_recycling_cost,
                replacement_cost=replacement_cost,
                residual_value_inflow=residual_value_inflow,
            )
        )
    return result


# =============================================================================
# ファイナンス
# =============================================================================


@dataclass
class FinancingYear:
    loan_balance_start: float
    principal_payment: float
    interest_payment: float
    debt_service: float
    loan_balance_end: float


def compute_financing_series(finance: FinanceInputs, debt_amount: float, simulation_years: int) -> list[FinancingYear]:
    """
    据置期間中は利払いのみ。据置後、元利均等（アニュイティ）または元金均等で返済する。
    借入期間がシミュレーション期間より短ければ完済後は0で埋める。
    """
    rate = finance.interest_rate_pct / 100
    grace = max(0, min(finance.grace_period_years, finance.loan_term_years))
    amort_years = max(0, finance.loan_term_years - grace)

    balance = debt_amount
    equal_payment_amount = 0.0
    if finance.repayment_method == "equal_payment" and amort_years > 0:
        if rate == 0:
            equal_payment_amount = balance / amort_years
        else:
            equal_payment_amount = (balance * rate * (1 + rate) ** amort_years) / ((1 + rate) ** amort_years - 1)
    equal_principal_amount = balance / amort_years if amort_years > 0 else 0.0

    result = []
    for t in range(1, simulation_years + 1):
        loan_balance_start = balance

        if t > finance.loan_term_years or balance <= 0:
            result.append(FinancingYear(loan_balance_start, 0.0, 0.0, 0.0, max(0.0, balance)))
            continue

        interest_payment = balance * rate

        if t <= grace:
            result.append(FinancingYear(loan_balance_start, 0.0, interest_payment, interest_payment, balance))
            continue

        if finance.repayment_method == "equal_payment":
            principal_payment = min(equal_payment_amount - interest_payment, balance)
        else:
            principal_payment = min(equal_principal_amount, balance)
        principal_payment = max(0.0, principal_payment)

        balance = max(0.0, balance - principal_payment)
        result.append(
            FinancingYear(loan_balance_start, principal_payment, interest_payment, principal_payment + interest_payment, balance)
        )
    return result


# =============================================================================
# 途中解約・倒産・移転リスク（期待値ベースの簡略モデル）
# =============================================================================


@dataclass
class RiskAdjustedFlow:
    customer_revenue: float
    procurement_cost: float
    surplus_revenue: float
    termination_fee_income: float
    survival_prob: float


def compute_risk_adjusted_flow(
    risk: RiskInputs,
    year: int,
    customer_revenue_nominal: float,
    procurement_cost_nominal: float,
    surplus_revenue_nominal: float,
    self_consumed_kwh: float,
    surplus_price: float,
) -> RiskAdjustedFlow:
    """
    年間ハザード率 h = 解約確率+倒産確率+移転確率。生存確率 survival(t)=(1-h)^t。
    途中終了分は処理方法（A契約承継/B余剰販売/C撤去/D解約金）に応じて収入・費用を調整する。
    1設備=1契約のMVPでの近似であり、本来ポートフォリオで初めて意味を持つ（README参照）。
    """
    hazard = (risk.annual_cancel_prob_pct + risk.annual_bankruptcy_prob_pct + risk.annual_relocation_prob_pct) / 100
    survival_prev = (1 - hazard) ** (year - 1)
    survival = (1 - hazard) ** year
    terminated_share = max(0.0, 1 - survival)
    marginal_termination_prob = max(0.0, survival_prev - survival)

    if risk.termination_handling == "removal":
        return RiskAdjustedFlow(
            customer_revenue_nominal * survival,
            procurement_cost_nominal * survival,
            surplus_revenue_nominal * survival,
            0.0,
            survival,
        )

    if risk.termination_handling == "succession":
        resell_share = terminated_share * (1 - risk.succession_success_rate_pct / 100)
    else:
        resell_share = terminated_share
    effective_survival = 1 - resell_share

    extra_surplus_revenue = resell_share * self_consumed_kwh * surplus_price

    termination_fee_income = (
        marginal_termination_prob * risk.termination_fee_amount
        if risk.termination_handling == "termination_fee"
        else 0.0
    )

    return RiskAdjustedFlow(
        customer_revenue_nominal * effective_survival,
        procurement_cost_nominal * effective_survival,
        surplus_revenue_nominal + extra_surplus_revenue,
        termination_fee_income,
        effective_survival,
    )


# =============================================================================
# 評価指標（NPV・IRR・単純回収年・DSCR統計）
# =============================================================================


def npv(discount_rate_pct: float, cashflows: list[float]) -> float:
    """NPV = Σ CF_t / (1+r)^t  (t=0,1,2,...; cashflows[0]がt=0)。"""
    r = discount_rate_pct / 100
    return sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))


def irr(cashflows: list[float]) -> Optional[float]:
    """IRR。Newton法で求め、収束しなければ二分法にフォールバック。符号反転が無ければNone。"""
    has_positive = any(c > 0 for c in cashflows)
    has_negative = any(c < 0 for c in cashflows)
    if not has_positive or not has_negative:
        return None

    def npv_at(rate_pct: float) -> float:
        return npv(rate_pct, cashflows)

    rate = 10.0
    for _ in range(100):
        f = npv_at(rate)
        h = 1e-4
        derivative = (npv_at(rate + h) - npv_at(rate - h)) / (2 * h)
        if abs(derivative) < 1e-9:
            break
        nxt = rate - f / derivative
        if not _is_finite(nxt):
            break
        if abs(nxt - rate) < 1e-7:
            rate = nxt
            if abs(npv_at(rate)) < 1e-3:
                return rate
            break
        rate = nxt
    if _is_finite(rate) and abs(npv_at(rate)) < 1e-3:
        return rate

    lo, hi = -99.0, 1000.0
    f_lo = npv_at(lo)
    f_hi = npv_at(hi)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if _sign(f_lo) == _sign(f_hi):
        steps = 200
        found = False
        prev_rate, prev_val = lo, f_lo
        for i in range(1, steps + 1):
            r = lo + (hi - lo) * i / steps
            v = npv_at(r)
            if _sign(v) != _sign(prev_val):
                lo, hi, f_lo = prev_rate, r, prev_val
                found = True
                break
            prev_rate, prev_val = r, v
        if not found:
            return None

    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv_at(mid)
        if abs(f_mid) < 1e-3:
            return mid
        if _sign(f_mid) == _sign(f_lo):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def _is_finite(v: float) -> bool:
    return v == v and v not in (float("inf"), float("-inf"))


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def simple_payback_years(cashflows: list[float]) -> Optional[float]:
    """単純投資回収年（割引なし累積CFが初めて0以上になる年。端数年を線形補間）。"""
    cumulative = cashflows[0]
    if cumulative >= 0:
        return 0.0
    for t in range(1, len(cashflows)):
        prev = cumulative
        cumulative += cashflows[t]
        if cumulative >= 0:
            frac = 0.0 if cashflows[t] == 0 else -prev / cashflows[t]
            return (t - 1) + frac
    return None


def dscr_stats(dscr_series: list[Optional[float]]) -> tuple[Optional[float], Optional[float]]:
    valid = [d for d in dscr_series if d is not None and _is_finite(d)]
    if not valid:
        return None, None
    return min(valid), sum(valid) / len(valid)


# =============================================================================
# 年次結果・サマリー
# =============================================================================


@dataclass
class YearlyResult:
    year: int
    generation_kwh: float
    consumption_kwh: float
    self_consumed_kwh: float
    surplus_kwh: float
    external_procurement_kwh: float

    customer_current_cost: float
    customer_new_cost: float
    customer_saving: float

    customer_revenue: float
    surplus_revenue: float
    other_income: float
    total_revenue: float

    procurement_cost: float
    om_cost: float
    insurance_cost: float
    management_cost: float
    repair_cost: float
    inverter_replacement_cost: float
    removal_recycling_cost: float
    replacement_cost: float
    total_opex: float

    loan_balance_start: float
    principal_payment: float
    interest_payment: float
    debt_service: float
    loan_balance_end: float

    ebitda: float
    cf_before_debt: float
    cf_after_debt: float
    cumulative_cf_after_debt: float
    residual_value_inflow: float

    dscr: Optional[float]
    survival_prob: float


@dataclass
class SimulationSummary:
    initial_investment: float
    equity_amount: float
    debt_amount: float
    loan_fee_amount: float

    customer_annual_saving_year1: float
    customer_saving_rate_pct: float
    customer_cumulative_saving_20y: float

    project_irr_pct: Optional[float]
    equity_irr_pct: Optional[float]
    npv_project: float
    npv_equity: float
    simple_payback_years: Optional[float]
    cumulative_cf_breakeven_year: Optional[int]
    min_dscr: Optional[float]
    avg_dscr: Optional[float]


@dataclass
class SimulationResult:
    yearly: list[YearlyResult]
    summary: SimulationSummary


def simulate(inputs: SimulationInputs) -> SimulationResult:
    customer, solar, retail, surplus, maintenance, finance, risk = (
        inputs.customer, inputs.solar, inputs.retail, inputs.surplus,
        inputs.maintenance, inputs.finance, inputs.risk,
    )
    n = customer.simulation_years

    initial_investment = compute_initial_investment(solar)
    equity_amount = initial_investment * (finance.equity_ratio_pct / 100)
    debt_amount = initial_investment - equity_amount
    loan_fee_amount = debt_amount * (finance.loan_fee_pct / 100)

    generation_series = compute_annual_generation(solar, n)
    consumption_series = compute_annual_consumption(customer)
    effective_self_consumption_rate = compute_effective_self_consumption_rate_pct(solar)
    energy_flow = compute_energy_flow_series(generation_series, consumption_series, effective_self_consumption_rate)

    customer_economics = compute_customer_economics(customer, consumption_series)
    procurement_unit_cost_series = compute_procurement_unit_cost_series(retail, n)
    surplus_price_series = compute_surplus_price_series(surplus, n)
    opex_series = compute_opex_series(maintenance, solar, initial_investment, n)
    financing_series = compute_financing_series(finance, debt_amount, n)

    yearly: list[YearlyResult] = []
    cumulative_cf = -(equity_amount + loan_fee_amount)

    for i in range(n):
        year = i + 1
        flow = energy_flow[i]

        customer_revenue_nominal = flow.consumption_kwh * customer.unified_rate
        procurement_cost_nominal = flow.external_procurement_kwh * procurement_unit_cost_series[i]
        surplus_revenue_nominal = flow.surplus_kwh * surplus_price_series[i]

        within_contract = year <= customer.contract_years
        if within_contract:
            ra = compute_risk_adjusted_flow(
                risk, year, customer_revenue_nominal, procurement_cost_nominal,
                surplus_revenue_nominal, flow.self_consumed_kwh, surplus_price_series[i],
            )
        else:
            # 契約期間満了後: 顧客請求は終了し、自家消費相当分も余剰電力として売却すると仮定
            ra = RiskAdjustedFlow(
                customer_revenue=0.0,
                procurement_cost=0.0,
                surplus_revenue=surplus_revenue_nominal + flow.self_consumed_kwh * surplus_price_series[i],
                termination_fee_income=0.0,
                survival_prob=0.0,
            )

        opex = opex_series[i]
        fin = financing_series[i]

        total_revenue = ra.customer_revenue + ra.surplus_revenue + ra.termination_fee_income
        total_opex = (
            ra.procurement_cost + opex.om_cost + opex.insurance_cost + opex.management_cost
            + opex.repair_cost + opex.inverter_replacement_cost + opex.removal_recycling_cost
            + opex.replacement_cost
        )

        ebitda = total_revenue - total_opex
        cf_before_debt = ebitda + opex.residual_value_inflow
        cf_after_debt = cf_before_debt - fin.debt_service
        cumulative_cf += cf_after_debt

        dscr = cf_before_debt / fin.debt_service if fin.debt_service > 0 else None

        yearly.append(
            YearlyResult(
                year=year,
                generation_kwh=flow.generation_kwh,
                consumption_kwh=flow.consumption_kwh,
                self_consumed_kwh=flow.self_consumed_kwh,
                surplus_kwh=flow.surplus_kwh,
                external_procurement_kwh=flow.external_procurement_kwh,
                customer_current_cost=customer_economics[i].current_cost,
                customer_new_cost=customer_economics[i].new_cost,
                customer_saving=customer_economics[i].saving,
                customer_revenue=ra.customer_revenue,
                surplus_revenue=ra.surplus_revenue,
                other_income=ra.termination_fee_income,
                total_revenue=total_revenue,
                procurement_cost=ra.procurement_cost,
                om_cost=opex.om_cost,
                insurance_cost=opex.insurance_cost,
                management_cost=opex.management_cost,
                repair_cost=opex.repair_cost,
                inverter_replacement_cost=opex.inverter_replacement_cost,
                removal_recycling_cost=opex.removal_recycling_cost,
                replacement_cost=opex.replacement_cost,
                total_opex=total_opex,
                loan_balance_start=fin.loan_balance_start,
                principal_payment=fin.principal_payment,
                interest_payment=fin.interest_payment,
                debt_service=fin.debt_service,
                loan_balance_end=fin.loan_balance_end,
                ebitda=ebitda,
                cf_before_debt=cf_before_debt,
                cf_after_debt=cf_after_debt,
                cumulative_cf_after_debt=cumulative_cf,
                residual_value_inflow=opex.residual_value_inflow,
                dscr=dscr,
                survival_prob=ra.survival_prob,
            )
        )

    summary = _build_summary(yearly, initial_investment, equity_amount, debt_amount, loan_fee_amount, finance.discount_rate_pct)
    return SimulationResult(yearly=yearly, summary=summary)


def _build_summary(
    yearly: list[YearlyResult],
    initial_investment: float,
    equity_amount: float,
    debt_amount: float,
    loan_fee_amount: float,
    discount_rate_pct: float,
) -> SimulationSummary:
    project_cf = [-initial_investment] + [y.cf_before_debt for y in yearly]
    equity_cf = [-(equity_amount + loan_fee_amount)] + [y.cf_after_debt for y in yearly]

    min_dscr, avg_dscr = dscr_stats([y.dscr for y in yearly])

    cumulative_cf_breakeven_year = None
    for y in yearly:
        if y.cumulative_cf_after_debt >= 0:
            cumulative_cf_breakeven_year = y.year
            break

    saving_20y = sum(y.customer_saving for y in yearly[: min(20, len(yearly))])
    year1 = yearly[0] if yearly else None

    return SimulationSummary(
        initial_investment=initial_investment,
        equity_amount=equity_amount,
        debt_amount=debt_amount,
        loan_fee_amount=loan_fee_amount,
        customer_annual_saving_year1=year1.customer_saving if year1 else 0.0,
        customer_saving_rate_pct=(
            (year1.customer_saving / year1.customer_current_cost) * 100
            if year1 and year1.customer_current_cost > 0
            else 0.0
        ),
        customer_cumulative_saving_20y=saving_20y,
        project_irr_pct=irr(project_cf),
        equity_irr_pct=irr(equity_cf),
        npv_project=npv(discount_rate_pct, project_cf),
        npv_equity=npv(discount_rate_pct, equity_cf),
        simple_payback_years=simple_payback_years(project_cf),
        cumulative_cf_breakeven_year=cumulative_cf_breakeven_year,
        min_dscr=min_dscr,
        avg_dscr=avg_dscr,
    )


# =============================================================================
# 損益分岐PPA単価（本アプリの中心機能）
# =============================================================================


@dataclass
class BreakevenResult:
    rate_for_npv_zero: Optional[float]
    rate_for_project_irr_target: Optional[float]
    rate_for_equity_irr_target: Optional[float]
    rate_for_min_dscr_target: Optional[float]
    breakeven_rate: Optional[float]


_RATE_MIN = 0.0
_RATE_MAX = 200.0


def _solve_breakeven_rate(inputs: SimulationInputs, predicate) -> Optional[float]:
    """
    一体単価を上げる→収入が一様に増える→NPV/IRR/DSCRは単調に改善、という関係を利用し
    二分法で条件を満たす最低単価を逆算する（README §3.11参照）。
    """
    import copy

    def make_result(rate: float) -> SimulationResult:
        adjusted = copy.deepcopy(inputs)
        adjusted.customer.unified_rate = rate
        return simulate(adjusted)

    if predicate(make_result(_RATE_MIN)):
        return _RATE_MIN
    if not predicate(make_result(_RATE_MAX)):
        return None

    lo, hi = _RATE_MIN, _RATE_MAX
    for _ in range(60):
        mid = (lo + hi) / 2
        if predicate(make_result(mid)):
            hi = mid
        else:
            lo = mid
    return hi


def compute_breakeven(inputs: SimulationInputs) -> BreakevenResult:
    finance = inputs.finance

    rate_npv0 = _solve_breakeven_rate(inputs, lambda r: r.summary.npv_equity >= 0)
    rate_irr = _solve_breakeven_rate(
        inputs, lambda r: (r.summary.project_irr_pct if r.summary.project_irr_pct is not None else float("-inf")) >= finance.target_project_irr_pct
    )
    rate_eq_irr = _solve_breakeven_rate(
        inputs, lambda r: (r.summary.equity_irr_pct if r.summary.equity_irr_pct is not None else float("-inf")) >= finance.target_equity_irr_pct
    )
    rate_dscr = _solve_breakeven_rate(
        inputs, lambda r: (r.summary.min_dscr if r.summary.min_dscr is not None else float("-inf")) >= finance.target_min_dscr
    )

    candidates = [v for v in [rate_npv0, rate_irr, rate_eq_irr, rate_dscr] if v is not None]
    breakeven_rate = max(candidates) if candidates else None

    return BreakevenResult(
        rate_for_npv_zero=rate_npv0,
        rate_for_project_irr_target=rate_irr,
        rate_for_equity_irr_target=rate_eq_irr,
        rate_for_min_dscr_target=rate_dscr,
        breakeven_rate=breakeven_rate,
    )


# =============================================================================
# 感度分析
# =============================================================================


SENSITIVITY_VARIABLES: list[tuple[str, str]] = [
    ("unified_rate", "PPA/小売料金"),
    ("unit_cost_per_kw", "設備費"),
    ("annual_yield_per_kw", "年間発電量"),
    ("self_consumption_rate_pct", "自家消費率"),
    ("grid_procurement_price", "外部電力調達単価"),
    ("interest_rate_pct", "金利"),
    ("subsidy_amount", "補助金"),
    ("contract_years", "契約期間"),
    ("om_fixed_amount", "O&M費"),
    ("removal_recycling_cost", "撤去・リサイクル費"),
    ("annual_cancel_prob_pct", "解約率"),
]

_CHANGE_PCTS = [-20, -10, 10, 20]


@dataclass
class SensitivityPoint:
    variable_key: str
    variable_label: str
    change_pct: int
    project_irr_pct: Optional[float]
    npv_project: float
    min_dscr: Optional[float]


def _apply_sensitivity(inputs: SimulationInputs, key: str, multiplier: float) -> SimulationInputs:
    import copy

    adjusted = copy.deepcopy(inputs)
    if key == "unified_rate":
        adjusted.customer.unified_rate *= multiplier
    elif key == "unit_cost_per_kw":
        adjusted.solar.unit_cost_per_kw *= multiplier
    elif key == "annual_yield_per_kw":
        if adjusted.solar.generation_input_mode == "capacity_x_yield":
            adjusted.solar.annual_yield_per_kw *= multiplier
        else:
            adjusted.solar.direct_annual_generation_kwh *= multiplier
    elif key == "self_consumption_rate_pct":
        adjusted.solar.self_consumption_rate_pct *= multiplier
    elif key == "grid_procurement_price":
        adjusted.retail.grid_procurement_price *= multiplier
    elif key == "interest_rate_pct":
        adjusted.finance.interest_rate_pct *= multiplier
    elif key == "subsidy_amount":
        adjusted.solar.subsidy_amount *= multiplier
    elif key == "contract_years":
        adjusted.customer.contract_years = max(1, round(adjusted.customer.contract_years * multiplier))
    elif key == "om_fixed_amount":
        adjusted.maintenance.om_fixed_amount *= multiplier
    elif key == "removal_recycling_cost":
        adjusted.maintenance.removal_cost *= multiplier
        adjusted.maintenance.recycling_cost *= multiplier
    elif key == "annual_cancel_prob_pct":
        adjusted.risk.annual_cancel_prob_pct *= multiplier
    return adjusted


def compute_sensitivity(inputs: SimulationInputs) -> list[SensitivityPoint]:
    points = []
    for key, label in SENSITIVITY_VARIABLES:
        for change_pct in _CHANGE_PCTS:
            multiplier = 1 + change_pct / 100
            adjusted = _apply_sensitivity(inputs, key, multiplier)
            result = simulate(adjusted)
            points.append(
                SensitivityPoint(
                    variable_key=key,
                    variable_label=label,
                    change_pct=change_pct,
                    project_irr_pct=result.summary.project_irr_pct,
                    npv_project=result.summary.npv_project,
                    min_dscr=result.summary.min_dscr,
                )
            )
    return points


def rank_sensitivity_impact(points: list[SensitivityPoint]) -> list[dict]:
    """各変数についてNPV(事業)の変化幅（±20%時の最大-最小）を計算し、影響度順にソートする。"""
    by_var: dict[str, list[SensitivityPoint]] = {}
    for p in points:
        by_var.setdefault(p.variable_key, []).append(p)
    rows = []
    for key, pts in by_var.items():
        npvs = [p.npv_project for p in pts]
        rows.append({"key": key, "label": pts[0].variable_label, "npv_range": max(npvs) - min(npvs)})
    rows.sort(key=lambda r: r["npv_range"], reverse=True)
    return rows


# =============================================================================
# サンプル値（§13）
# =============================================================================


def _common_maintenance(capex: float, removal_base: float, recycling_base: float, mgmt_annual: float) -> MaintenanceInputs:
    return MaintenanceInputs(
        om_mode="pct_of_capex", om_fixed_amount=0.0, om_pct_of_capex=1.0,
        inverter_replacement_year=12, inverter_replacement_cost=capex * 0.08,
        repair_schedule=[],
        insurance_mode="pct_of_capex", insurance_fixed_amount=0.0, insurance_pct_of_capex=0.3,
        management_fee_annual=mgmt_annual,
        removal_cost=removal_base, recycling_cost=recycling_base,
        replacement_cost=capex, residual_value=capex * 0.1,
        terminal_treatment="residual_value",
    )


def _common_finance(equity_ratio_pct: float) -> FinanceInputs:
    return FinanceInputs(
        equity_ratio_pct=equity_ratio_pct, interest_rate_pct=1.5, loan_term_years=15,
        repayment_method="equal_payment", grace_period_years=1, loan_fee_pct=1.0,
        discount_rate_pct=4.0, target_project_irr_pct=5.0, target_equity_irr_pct=8.0, target_min_dscr=1.2,
    )


def _common_retail() -> RetailCostInputs:
    return RetailCostInputs(
        grid_procurement_price=15.0, transmission_fee=8.0, capacity_contribution_fee=1.0,
        other_retail_cost=1.0, apply_renewable_levy=True, renewable_levy_rate=3.5,
        retail_cost_escalation_rate_pct=1.0,
    )


def _common_surplus() -> SurplusInputs:
    return SurplusInputs(surplus_price=8.0, surplus_price_escalation_rate_pct=0.0, destination="market")


def create_residential_sample() -> SimulationInputs:
    capacity_kw = 6.0
    unit_cost_per_kw = 250_000.0
    capex = capacity_kw * unit_cost_per_kw
    return SimulationInputs(
        customer=CustomerContractInputs(
            segment="residential", simulation_years=20, contract_years=20, unified_rate=25.0,
            tax_mode="tax_included", current_unit_price=28.0, current_price_escalation_rate_pct=1.0,
            annual_consumption_kwh=6000.0, consumption_growth_rate_pct=0.0,
        ),
        solar=SolarAssetInputs(
            generation_input_mode="capacity_x_yield", capacity_kw=capacity_kw, unit_cost_per_kw=unit_cost_per_kw,
            subsidy_amount=0.0, annual_yield_per_kw=1100.0, direct_annual_generation_kwh=capacity_kw * 1100.0,
            degradation_rate_pct=0.5, self_consumption_rate_pct=50.0, useful_life_years=20,
            battery_enabled=False, battery_self_consumption_boost_pct=15.0, battery_cost=1_200_000.0, battery_annual_om=5000.0,
            heat_pump_enabled=False, heat_pump_self_consumption_boost_pct=8.0, heat_pump_cost=450_000.0,
        ),
        retail=_common_retail(),
        surplus=_common_surplus(),
        # 単体の住宅1件では高レバレッジの単独プロジェクトファイナンスは成立しにくいため、
        # 自己資本比率は高め(40%)に設定（※仮定値）。
        maintenance=_common_maintenance(capex, 150_000.0, 50_000.0, 5000.0),
        finance=_common_finance(40.0),
        risk=RiskInputs(
            annual_cancel_prob_pct=0.0, annual_bankruptcy_prob_pct=0.0, annual_relocation_prob_pct=1.0,
            termination_handling="resell_surplus", succession_success_rate_pct=50.0, termination_fee_amount=0.0,
        ),
    )


def create_business_sample() -> SimulationInputs:
    capacity_kw = 50.0
    unit_cost_per_kw = 180_000.0
    capex = capacity_kw * unit_cost_per_kw
    return SimulationInputs(
        customer=CustomerContractInputs(
            segment="business", simulation_years=20, contract_years=20, unified_rate=24.0,
            tax_mode="tax_excluded", current_unit_price=26.0, current_price_escalation_rate_pct=1.0,
            annual_consumption_kwh=100_000.0, consumption_growth_rate_pct=0.0,
        ),
        solar=SolarAssetInputs(
            generation_input_mode="capacity_x_yield", capacity_kw=capacity_kw, unit_cost_per_kw=unit_cost_per_kw,
            subsidy_amount=0.0, annual_yield_per_kw=1100.0, direct_annual_generation_kwh=capacity_kw * 1100.0,
            degradation_rate_pct=0.5, self_consumption_rate_pct=80.0, useful_life_years=20,
            battery_enabled=False, battery_self_consumption_boost_pct=10.0, battery_cost=6_000_000.0, battery_annual_om=30_000.0,
            heat_pump_enabled=False, heat_pump_self_consumption_boost_pct=5.0, heat_pump_cost=2_000_000.0,
        ),
        retail=_common_retail(),
        surplus=_common_surplus(),
        maintenance=_common_maintenance(capex, 800_000.0, 400_000.0, 30_000.0),
        # 50kW規模・複数事業所を束ねる前提でプロジェクトファイナンス色を強め、自己資本比率は低め(20%)（※仮定値）。
        finance=_common_finance(20.0),
        risk=RiskInputs(
            annual_cancel_prob_pct=1.0, annual_bankruptcy_prob_pct=1.0, annual_relocation_prob_pct=2.0,
            termination_handling="resell_surplus", succession_success_rate_pct=50.0, termination_fee_amount=500_000.0,
        ),
    )


def create_sample_inputs(segment: CustomerSegment) -> SimulationInputs:
    return create_residential_sample() if segment == "residential" else create_business_sample()
