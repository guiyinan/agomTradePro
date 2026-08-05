"""Pure fixed-income valuation and relative-value calculations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from .entities import (
    AccrualPeriod,
    AnalyticsReconciliationResult,
    AnalyticsReconciliationSpec,
    Bond,
    BondAnalytics,
    CarryEstimate,
    CarryInputs,
    CashFlowKind,
    CashFlowSchedule,
    DayCountConvention,
    RollDownEstimate,
    YieldCurve,
    YieldSolverSpec,
)


def _require_finite(value: Decimal, field_name: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")


def _decimal_power(base: Decimal, exponent: Decimal) -> Decimal:
    _require_finite(base, "discount base")
    _require_finite(exponent, "discount exponent")
    if base <= 0:
        raise ValueError("discount base must be positive")
    with localcontext() as context:
        context.prec = 40
        return (exponent * base.ln()).exp()


def _thirty_e_360_days(start: date, end: date) -> int:
    start_day = min(start.day, 30)
    end_day = min(end.day, 30)
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + end_day - start_day


def _day_count_days(start: date, end: date, convention: DayCountConvention) -> int:
    if convention is DayCountConvention.THIRTY_E_360:
        return _thirty_e_360_days(start, end)
    return (end - start).days


def accrued_interest(period: AccrualPeriod) -> Decimal:
    """Calculate coupon accrued interest using the explicitly selected convention."""

    elapsed = _day_count_days(
        period.previous_coupon_date,
        period.settlement_date,
        period.day_count_convention,
    )
    total = _day_count_days(
        period.previous_coupon_date,
        period.next_coupon_date,
        period.day_count_convention,
    )
    if total <= 0 or elapsed < 0 or elapsed > total:
        raise ValueError("invalid accrued-interest day-count interval")
    return period.coupon_amount * Decimal(elapsed) / Decimal(total)


def validate_bond_schedule(bond: Bond, schedule: CashFlowSchedule) -> None:
    """Fail closed when the injected schedule cannot represent the bond terms."""

    if bond.bond_id != schedule.bond_id:
        raise ValueError("bond and cash-flow schedule identifiers do not match")
    if schedule.settlement_date < bond.issue_date or schedule.settlement_date >= bond.maturity_date:
        raise ValueError("settlement_date falls outside the bond life")
    if schedule.cash_flows[-1].payment_date != bond.maturity_date:
        raise ValueError("cash-flow schedule does not reach bond maturity")
    principal_flows = tuple(
        flow
        for flow in schedule.cash_flows
        if flow.payment_date == bond.maturity_date
        and flow.kind in {CashFlowKind.PRINCIPAL, CashFlowKind.PRINCIPAL_AND_COUPON}
    )
    if (
        not principal_flows
        or sum((flow.amount for flow in principal_flows), Decimal("0")) < bond.face_value
    ):
        raise ValueError("cash-flow schedule lacks maturity principal")


def price_from_yield(
    *,
    bond: Bond,
    schedule: CashFlowSchedule,
    annual_yield: Decimal,
) -> Decimal:
    """Return dirty price under nominal annual yield and explicit coupon frequency."""

    validate_bond_schedule(bond, schedule)
    _require_finite(annual_yield, "annual_yield")
    frequency = Decimal(bond.coupon_frequency)
    periodic_base = Decimal("1") + annual_yield / frequency
    if periodic_base <= 0:
        raise ValueError("annual_yield is outside the supported compounding domain")
    with localcontext() as context:
        context.prec = 40
        return sum(
            (
                flow.amount / _decimal_power(periodic_base, flow.time_years * frequency)
                for flow in schedule.cash_flows
            ),
            Decimal("0"),
        )


def yield_from_dirty_price(
    *,
    bond: Bond,
    schedule: CashFlowSchedule,
    dirty_price: Decimal,
    solver: YieldSolverSpec,
) -> Decimal:
    """Solve nominal annual yield by a bounded, deterministic bisection."""

    _require_finite(dirty_price, "dirty_price")
    if dirty_price <= 0:
        raise ValueError("dirty_price must be positive")
    lower = solver.lower_bound
    upper = solver.upper_bound
    lower_error = price_from_yield(bond=bond, schedule=schedule, annual_yield=lower) - dirty_price
    upper_error = price_from_yield(bond=bond, schedule=schedule, annual_yield=upper) - dirty_price
    if abs(lower_error) <= solver.price_tolerance:
        return lower
    if abs(upper_error) <= solver.price_tolerance:
        return upper
    if lower_error * upper_error > 0:
        raise ValueError("dirty price is not bracketed by the supplied yield solver bounds")

    for _ in range(solver.max_iterations):
        midpoint = (lower + upper) / Decimal("2")
        midpoint_error = (
            price_from_yield(bond=bond, schedule=schedule, annual_yield=midpoint) - dirty_price
        )
        if abs(midpoint_error) <= solver.price_tolerance or upper - lower <= solver.yield_tolerance:
            return midpoint
        if midpoint_error > 0:
            lower = midpoint
        else:
            upper = midpoint
    raise ValueError("yield solver did not converge within max_iterations")


def analyze_bond_from_dirty_price(
    *,
    bond: Bond,
    schedule: CashFlowSchedule,
    dirty_price: Decimal,
    solver: YieldSolverSpec,
) -> BondAnalytics:
    """Calculate clean/dirty price, YTM, Macaulay/modified duration and convexity."""

    annual_yield = yield_from_dirty_price(
        bond=bond,
        schedule=schedule,
        dirty_price=dirty_price,
        solver=solver,
    )
    frequency = Decimal(bond.coupon_frequency)
    periodic_base = Decimal("1") + annual_yield / frequency
    present_values = tuple(
        flow.amount / _decimal_power(periodic_base, flow.time_years * frequency)
        for flow in schedule.cash_flows
    )
    modeled_dirty_price = sum(present_values, Decimal("0"))
    if modeled_dirty_price <= 0:
        raise ValueError("modeled dirty price must be positive")
    macaulay = (
        sum(
            (
                flow.time_years * present_value
                for flow, present_value in zip(schedule.cash_flows, present_values, strict=True)
            ),
            Decimal("0"),
        )
        / modeled_dirty_price
    )
    modified = macaulay / periodic_base
    convexity_numerator = Decimal("0")
    for flow, present_value in zip(schedule.cash_flows, present_values, strict=True):
        periods = flow.time_years * frequency
        convexity_numerator += present_value * periods * (periods + Decimal("1"))
    convexity = convexity_numerator / (
        modeled_dirty_price * frequency * frequency * periodic_base * periodic_base
    )
    accrued = accrued_interest(schedule.accrual_period)
    if dirty_price <= accrued:
        raise ValueError("dirty_price must exceed accrued interest")
    return BondAnalytics(
        dirty_price=dirty_price,
        accrued_interest=accrued,
        clean_price=dirty_price - accrued,
        annual_yield=annual_yield,
        macaulay_duration_years=macaulay,
        modified_duration_years=modified,
        convexity_years_squared=convexity,
    )


def curve_yield(curve: YieldCurve, tenor_years: Decimal) -> Decimal:
    """Return linearly interpolated zero yield without extrapolation."""

    _require_finite(tenor_years, "tenor_years")
    if tenor_years <= 0:
        raise ValueError("tenor_years must be positive")
    nodes = curve.nodes
    if tenor_years < nodes[0].tenor_years or tenor_years > nodes[-1].tenor_years:
        raise ValueError("requested tenor lies outside the published curve")
    for node in nodes:
        if node.tenor_years == tenor_years:
            return node.annual_yield
    for left, right in zip(nodes, nodes[1:], strict=False):
        if left.tenor_years < tenor_years < right.tenor_years:
            weight = (tenor_years - left.tenor_years) / (right.tenor_years - left.tenor_years)
            return left.annual_yield + weight * (right.annual_yield - left.annual_yield)
    raise ValueError("curve interpolation failed")


def tenor_spread_bp(curve: YieldCurve, long_tenor: Decimal, short_tenor: Decimal) -> Decimal:
    """Return long-minus-short spread in basis points."""

    _require_finite(long_tenor, "long_tenor")
    _require_finite(short_tenor, "short_tenor")
    if long_tenor <= short_tenor:
        raise ValueError("long_tenor must exceed short_tenor")
    return (curve_yield(curve, long_tenor) - curve_yield(curve, short_tenor)) * Decimal("10000")


def spread_between_curves_bp(
    upper_curve: YieldCurve,
    lower_curve: YieldCurve,
    tenor_years: Decimal,
) -> Decimal:
    """Return upper-minus-lower yield spread at one matching currency tenor."""

    if upper_curve.currency != lower_curve.currency:
        raise ValueError("curve currencies do not match")
    return (
        curve_yield(upper_curve, tenor_years) - curve_yield(lower_curve, tenor_years)
    ) * Decimal("10000")


def estimate_carry(inputs: CarryInputs) -> CarryEstimate:
    """Calculate holding-period carry after financing, transaction and liquidity costs."""

    amount = (
        inputs.coupon_cash_received
        + inputs.end_accrued_interest
        - inputs.start_accrued_interest
        - inputs.financing_cost
        - inputs.transaction_cost
        - inputs.liquidity_cost
    )
    return CarryEstimate(carry_amount=amount, carry_return=amount / inputs.start_dirty_price)


def estimate_roll_down(
    *,
    curve: YieldCurve,
    current_tenor_years: Decimal,
    horizon_years: Decimal,
    modified_duration_years: Decimal,
    convexity_years_squared: Decimal,
) -> RollDownEstimate:
    """Approximate unchanged-curve roll-down using duration and convexity."""

    for name, value in (
        ("current_tenor_years", current_tenor_years),
        ("horizon_years", horizon_years),
        ("modified_duration_years", modified_duration_years),
        ("convexity_years_squared", convexity_years_squared),
    ):
        _require_finite(value, name)
    if horizon_years <= 0 or horizon_years >= current_tenor_years:
        raise ValueError("roll-down horizon must be positive and shorter than tenor")
    if modified_duration_years < 0 or convexity_years_squared < 0:
        raise ValueError("duration and convexity cannot be negative")
    residual_tenor = current_tenor_years - horizon_years
    current_yield = curve_yield(curve, current_tenor_years)
    residual_yield = curve_yield(curve, residual_tenor)
    yield_change = residual_yield - current_yield
    estimated_return = (
        -modified_duration_years * yield_change
        + Decimal("0.5") * convexity_years_squared * yield_change * yield_change
    )
    return RollDownEstimate(
        current_tenor_years=current_tenor_years,
        residual_tenor_years=residual_tenor,
        current_yield=current_yield,
        residual_yield=residual_yield,
        yield_change=yield_change,
        estimated_price_return=estimated_return,
    )


def reconcile_analytics(
    analytics: BondAnalytics,
    spec: AnalyticsReconciliationSpec,
) -> AnalyticsReconciliationResult:
    """Compare computed analytics with a versioned manual or third-party benchmark."""

    comparisons = (
        ("dirty_price", analytics.dirty_price, spec.expected_dirty_price, spec.price_tolerance),
        (
            "macaulay_duration",
            analytics.macaulay_duration_years,
            spec.expected_macaulay_duration,
            spec.duration_tolerance,
        ),
        (
            "modified_duration",
            analytics.modified_duration_years,
            spec.expected_modified_duration,
            spec.duration_tolerance,
        ),
        (
            "convexity",
            analytics.convexity_years_squared,
            spec.expected_convexity,
            spec.convexity_tolerance,
        ),
    )
    failed = tuple(
        name
        for name, actual, expected, tolerance in comparisons
        if abs(actual - expected) > tolerance
    )
    return AnalyticsReconciliationResult(
        benchmark_id=spec.benchmark_id,
        benchmark_version=spec.benchmark_version,
        is_reconciled=not failed,
        failed_fields=failed,
    )
