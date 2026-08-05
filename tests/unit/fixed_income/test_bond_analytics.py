"""Golden-sample and edge coverage for the R5 fixed-income domain."""

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.fixed_income.domain.entities import (
    AccrualPeriod,
    Bond,
    CanonicalPublicationReference,
    CarryInputs,
    CashFlow,
    CashFlowKind,
    CashFlowSchedule,
    CurveKind,
    CurveNode,
    DayCountConvention,
    InputRole,
    InterpolationMethod,
    YieldCurve,
    YieldSolverSpec,
)
from apps.fixed_income.domain.services import (
    accrued_interest,
    analyze_bond_from_dirty_price,
    estimate_carry,
    estimate_roll_down,
    price_from_yield,
    spread_between_curves_bp,
    tenor_spread_bp,
    yield_from_dirty_price,
)

AS_OF = datetime(2024, 1, 1, 9, tzinfo=UTC)


def _reference(role: InputRole) -> CanonicalPublicationReference:
    curve_kind = {
        InputRole.GOVERNMENT_CURVE: CurveKind.GOVERNMENT,
        InputRole.POLICY_BANK_CURVE: CurveKind.POLICY_BANK,
        InputRole.CREDIT_VALUATION: CurveKind.CREDIT,
        InputRole.FUNDING_CURVE: CurveKind.FUNDING,
        InputRole.POLICY_RATE: CurveKind.POLICY_RATE,
    }.get(role)
    return CanonicalPublicationReference(
        role=role,
        currency="CNY",
        curve_kind=curve_kind,
        semantic_version="fixed-income-semantics.v1",
        owner="data_center",
        dataset_key=f"r5_{role.value}",
        publication_key="research",
        publication_id=f"publication-{role.value}",
        policy_version="policy-v1",
        content_hash=hashlib.sha256(role.value.encode("utf-8")).hexdigest(),
        observed_at=datetime(2023, 12, 31, 9, tzinfo=UTC),
        published_at=datetime(2023, 12, 31, 12, tzinfo=UTC),
        valid_until=datetime(2024, 1, 3, 9, tzinfo=UTC),
    )


def _golden_bond() -> tuple[Bond, CashFlowSchedule]:
    bond = Bond(
        bond_id="GOLD-2Y-5PCT",
        currency="CNY",
        face_value=Decimal("100"),
        issue_date=date(2024, 1, 1),
        maturity_date=date(2026, 1, 1),
        annual_coupon_rate=Decimal("0.05"),
        coupon_frequency=1,
        day_count_convention=DayCountConvention.ACTUAL_ACTUAL_COUPON,
        master_reference=_reference(InputRole.BOND_MASTER),
    )
    schedule = CashFlowSchedule(
        bond_id=bond.bond_id,
        settlement_date=date(2024, 1, 1),
        cash_flows=(
            CashFlow(
                payment_date=date(2025, 1, 1),
                amount=Decimal("5"),
                time_years=Decimal("1"),
                kind=CashFlowKind.COUPON,
            ),
            CashFlow(
                payment_date=date(2026, 1, 1),
                amount=Decimal("105"),
                time_years=Decimal("2"),
                kind=CashFlowKind.PRINCIPAL_AND_COUPON,
            ),
        ),
        accrual_period=AccrualPeriod(
            settlement_date=date(2024, 1, 1),
            previous_coupon_date=date(2024, 1, 1),
            next_coupon_date=date(2025, 1, 1),
            coupon_amount=Decimal("5"),
            day_count_convention=DayCountConvention.ACTUAL_ACTUAL_COUPON,
        ),
        schedule_reference=_reference(InputRole.CASH_FLOW_SCHEDULE),
        calendar_reference=_reference(InputRole.TRADING_CALENDAR),
    )
    return bond, schedule


def test_two_year_coupon_bond_matches_hand_reproducible_golden_sample() -> None:
    """5/1.04 + 105/1.04^2 is the independently reproducible benchmark."""

    bond, schedule = _golden_bond()
    solver = YieldSolverSpec(
        lower_bound=Decimal("-0.50"),
        upper_bound=Decimal("0.50"),
        price_tolerance=Decimal("0.000000000001"),
        yield_tolerance=Decimal("0.000000000001"),
        max_iterations=200,
    )

    dirty_price = price_from_yield(bond=bond, schedule=schedule, annual_yield=Decimal("0.04"))
    solved_yield = yield_from_dirty_price(
        bond=bond,
        schedule=schedule,
        dirty_price=dirty_price,
        solver=solver,
    )
    analytics = analyze_bond_from_dirty_price(
        bond=bond,
        schedule=schedule,
        dirty_price=dirty_price,
        solver=solver,
    )

    assert dirty_price == pytest.approx(Decimal("101.886094674556213017751479290"))
    assert solved_yield == pytest.approx(Decimal("0.04"), abs=Decimal("0.000000000001"))
    assert analytics.clean_price == pytest.approx(dirty_price)
    assert analytics.macaulay_duration_years == pytest.approx(
        Decimal("1.95281306715063520871143375680")
    )
    assert analytics.modified_duration_years == pytest.approx(
        Decimal("1.87770487226022616222253245846")
    )
    assert analytics.convexity_years_squared == pytest.approx(
        Decimal("5.37282939034998228073755087576")
    )


def test_clean_price_subtracts_actual_actual_coupon_accrual() -> None:
    period = AccrualPeriod(
        settlement_date=date(2024, 4, 1),
        previous_coupon_date=date(2024, 1, 1),
        next_coupon_date=date(2024, 7, 1),
        coupon_amount=Decimal("3"),
        day_count_convention=DayCountConvention.ACTUAL_ACTUAL_COUPON,
    )

    assert accrued_interest(period) == Decimal("1.5")


def test_curve_spreads_and_roll_down_use_injected_versioned_curve() -> None:
    government = YieldCurve(
        curve_id="CGB",
        currency="CNY",
        kind=CurveKind.GOVERNMENT,
        nodes=(
            CurveNode(tenor_years=Decimal("1"), annual_yield=Decimal("0.020")),
            CurveNode(tenor_years=Decimal("2"), annual_yield=Decimal("0.022")),
            CurveNode(tenor_years=Decimal("5"), annual_yield=Decimal("0.025")),
            CurveNode(tenor_years=Decimal("10"), annual_yield=Decimal("0.030")),
        ),
        interpolation=InterpolationMethod.LINEAR_ZERO,
        reference=_reference(InputRole.GOVERNMENT_CURVE),
    )
    credit = YieldCurve(
        curve_id="AAA",
        currency="CNY",
        kind=CurveKind.CREDIT,
        nodes=(
            CurveNode(tenor_years=Decimal("2"), annual_yield=Decimal("0.027")),
            CurveNode(tenor_years=Decimal("10"), annual_yield=Decimal("0.038")),
        ),
        interpolation=InterpolationMethod.LINEAR_ZERO,
        reference=_reference(InputRole.CREDIT_VALUATION),
    )

    assert tenor_spread_bp(government, Decimal("10"), Decimal("2")) == Decimal("80")
    assert spread_between_curves_bp(credit, government, Decimal("2")) == Decimal("50")

    roll_down = estimate_roll_down(
        curve=government,
        current_tenor_years=Decimal("10"),
        horizon_years=Decimal("1"),
        modified_duration_years=Decimal("8"),
        convexity_years_squared=Decimal("75"),
    )
    assert roll_down.residual_tenor_years == Decimal("9")
    assert roll_down.yield_change == Decimal("-0.001")
    assert roll_down.estimated_price_return == Decimal("0.0080375")


def test_carry_deducts_all_explicit_cost_inputs() -> None:
    inputs = CarryInputs(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 7, 1),
        start_dirty_price=Decimal("100"),
        coupon_cash_received=Decimal("2"),
        start_accrued_interest=Decimal("0.5"),
        end_accrued_interest=Decimal("1.0"),
        financing_cost=Decimal("0.25"),
        transaction_cost=Decimal("0.10"),
        liquidity_cost=Decimal("0.05"),
        financing_reference=_reference(InputRole.FINANCING_COST),
        transaction_cost_reference=_reference(InputRole.TRANSACTION_COST),
        liquidity_reference=_reference(InputRole.LIQUIDITY_COST),
        calendar_reference=_reference(InputRole.TRADING_CALENDAR),
    )

    result = estimate_carry(inputs)

    assert result.carry_amount == Decimal("2.10")
    assert result.carry_return == Decimal("0.021")


def test_yield_solver_fails_closed_when_price_is_not_bracketed() -> None:
    bond, schedule = _golden_bond()
    solver = YieldSolverSpec(
        lower_bound=Decimal("0.01"),
        upper_bound=Decimal("0.02"),
        price_tolerance=Decimal("0.000001"),
        yield_tolerance=Decimal("0.000001"),
        max_iterations=25,
    )

    with pytest.raises(ValueError, match="not bracketed"):
        yield_from_dirty_price(
            bond=bond,
            schedule=schedule,
            dirty_price=Decimal("80"),
            solver=solver,
        )


def test_publication_reference_rejects_naive_or_future_evidence() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CanonicalPublicationReference(
            role=InputRole.BOND_MASTER,
            currency="CNY",
            curve_kind=None,
            semantic_version="fixed-income-semantics.v1",
            owner="data_center",
            dataset_key="bond_master",
            publication_key="research",
            publication_id="pub",
            policy_version="v1",
            content_hash="a" * 64,
            observed_at=datetime(2024, 1, 1),
            published_at=AS_OF,
            valid_until=datetime(2024, 1, 2, tzinfo=UTC),
        )

    reference = _reference(InputRole.BOND_MASTER)
    assert (
        reference.usability_reason(datetime(2023, 12, 30, tzinfo=UTC)) == "publication_from_future"
    )
    assert reference.usability_reason(datetime(2024, 1, 4, tzinfo=UTC)) == "publication_stale"


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_decimal_inputs_reject_non_finite_values(value: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        CurveNode(tenor_years=Decimal("1"), annual_yield=value)


def test_publication_is_stale_at_exact_valid_until_boundary() -> None:
    reference = _reference(InputRole.BOND_MASTER)

    assert reference.usability_reason(reference.valid_until) == "publication_stale"
