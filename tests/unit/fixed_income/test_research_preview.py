"""Fail-closed application coverage for R5 research-only previews."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from apps.fixed_income.application.use_cases import (
    FixedIncomeResearchRequest,
    RunFixedIncomeResearchPreview,
)
from apps.fixed_income.domain.entities import (
    AccrualPeriod,
    AnalyticsReconciliationSpec,
    Bond,
    CanonicalPublicationReference,
    CarryInputs,
    CashFlow,
    CashFlowKind,
    CashFlowSchedule,
    CurveKind,
    CurveNode,
    DayCountConvention,
    FixedIncomeResearchInputs,
    InputRole,
    InterpolationMethod,
    ResearchPreviewStatus,
    YieldCurve,
    YieldSolverSpec,
)

AS_OF = datetime(2024, 1, 1, 9, tzinfo=UTC)


def _ref(role: InputRole) -> CanonicalPublicationReference:
    return CanonicalPublicationReference(
        role=role,
        owner="data_center",
        dataset_key=f"r5_{role.value}",
        publication_key="research",
        publication_id=f"pub-{role.value}",
        policy_version="policy-v1",
        content_hash="a" * 64,
        observed_at=datetime(2023, 12, 31, 9, tzinfo=UTC),
        published_at=datetime(2023, 12, 31, 12, tzinfo=UTC),
        valid_until=datetime(2024, 1, 3, 9, tzinfo=UTC),
    )


def _request() -> FixedIncomeResearchRequest:
    bond = Bond(
        bond_id="GOLD-2Y-5PCT",
        currency="CNY",
        face_value=Decimal("100"),
        issue_date=date(2024, 1, 1),
        maturity_date=date(2026, 1, 1),
        annual_coupon_rate=Decimal("0.05"),
        coupon_frequency=1,
        day_count_convention=DayCountConvention.ACTUAL_ACTUAL_COUPON,
        master_reference=_ref(InputRole.BOND_MASTER),
    )
    schedule = CashFlowSchedule(
        bond_id=bond.bond_id,
        settlement_date=date(2024, 1, 1),
        cash_flows=(
            CashFlow(date(2025, 1, 1), Decimal("5"), Decimal("1"), CashFlowKind.COUPON),
            CashFlow(
                date(2026, 1, 1),
                Decimal("105"),
                Decimal("2"),
                CashFlowKind.PRINCIPAL_AND_COUPON,
            ),
        ),
        accrual_period=AccrualPeriod(
            settlement_date=date(2024, 1, 1),
            previous_coupon_date=date(2024, 1, 1),
            next_coupon_date=date(2025, 1, 1),
            coupon_amount=Decimal("5"),
            day_count_convention=DayCountConvention.ACTUAL_ACTUAL_COUPON,
        ),
        schedule_reference=_ref(InputRole.CASH_FLOW_SCHEDULE),
        calendar_reference=_ref(InputRole.TRADING_CALENDAR),
    )
    government_curve = YieldCurve(
        curve_id="CGB",
        currency="CNY",
        kind=CurveKind.GOVERNMENT,
        nodes=(
            CurveNode(Decimal("1"), Decimal("0.03")),
            CurveNode(Decimal("2"), Decimal("0.04")),
        ),
        interpolation=InterpolationMethod.LINEAR_ZERO,
        reference=_ref(InputRole.GOVERNMENT_CURVE),
    )
    policy_bank_curve = YieldCurve(
        curve_id="CDB",
        currency="CNY",
        kind=CurveKind.POLICY_BANK,
        nodes=(
            CurveNode(Decimal("1"), Decimal("0.032")),
            CurveNode(Decimal("2"), Decimal("0.043")),
        ),
        interpolation=InterpolationMethod.LINEAR_ZERO,
        reference=_ref(InputRole.POLICY_BANK_CURVE),
    )
    credit_curve = YieldCurve(
        curve_id="AAA",
        currency="CNY",
        kind=CurveKind.CREDIT,
        nodes=(
            CurveNode(Decimal("1"), Decimal("0.035")),
            CurveNode(Decimal("2"), Decimal("0.045")),
        ),
        interpolation=InterpolationMethod.LINEAR_ZERO,
        reference=_ref(InputRole.CREDIT_VALUATION),
    )
    carry = CarryInputs(
        start_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
        start_dirty_price=Decimal("101.886094674556213017751479290"),
        coupon_cash_received=Decimal("5"),
        start_accrued_interest=Decimal("0"),
        end_accrued_interest=Decimal("0"),
        financing_cost=Decimal("1"),
        transaction_cost=Decimal("0.1"),
        liquidity_cost=Decimal("0.2"),
        financing_reference=_ref(InputRole.FINANCING_COST),
        transaction_cost_reference=_ref(InputRole.TRANSACTION_COST),
        liquidity_reference=_ref(InputRole.LIQUIDITY_COST),
        calendar_reference=_ref(InputRole.TRADING_CALENDAR),
    )
    inputs = FixedIncomeResearchInputs(
        bond=bond,
        schedule=schedule,
        government_curve=government_curve,
        policy_bank_curve=policy_bank_curve,
        credit_curve=credit_curve,
        carry_inputs=carry,
        market_dirty_price=Decimal("101.886094674556213017751479290"),
        roll_down_horizon_years=Decimal("1"),
    )
    return FixedIncomeResearchRequest(
        valuation_at=AS_OF,
        method_version="fixed-income-research-v1",
        inputs=inputs,
        solver=YieldSolverSpec(
            lower_bound=Decimal("-0.50"),
            upper_bound=Decimal("0.50"),
            price_tolerance=Decimal("0.000000000001"),
            yield_tolerance=Decimal("0.000000000001"),
            max_iterations=200,
        ),
        reconciliation=AnalyticsReconciliationSpec(
            benchmark_id="manual-gold-2y-5pct",
            benchmark_version="v1",
            evidence_hash="b" * 64,
            expected_dirty_price=Decimal("101.886094674556213017751479290"),
            expected_macaulay_duration=Decimal("1.95281306715063520871143375680"),
            expected_modified_duration=Decimal("1.87770487226022616222253245846"),
            expected_convexity=Decimal("5.37282939034998228073755087576"),
            price_tolerance=Decimal("0.000000001"),
            duration_tolerance=Decimal("0.000000001"),
            convexity_tolerance=Decimal("0.000000001"),
        ),
    )


def test_preview_is_available_but_never_executable() -> None:
    preview = RunFixedIncomeResearchPreview().execute(_request())

    assert preview.status is ResearchPreviewStatus.AVAILABLE
    assert preview.blocked_reasons == ()
    assert preview.research_only is True
    assert preview.must_not_execute is True
    assert preview.must_not_use_for_decision is True
    assert preview.analytics is not None
    assert preview.relative_value is not None
    assert preview.reconciliation is not None
    assert preview.reconciliation.is_reconciled is True
    assert set(preview.publication_ids) == {
        f"pub-{role.value}"
        for role in (
            InputRole.BOND_MASTER,
            InputRole.CASH_FLOW_SCHEDULE,
            InputRole.TRADING_CALENDAR,
            InputRole.GOVERNMENT_CURVE,
            InputRole.POLICY_BANK_CURVE,
            InputRole.CREDIT_VALUATION,
            InputRole.FINANCING_COST,
            InputRole.TRANSACTION_COST,
            InputRole.LIQUIDITY_COST,
        )
    }
    assert preview.relative_value.policy_bank_spread_bp == Decimal("30")


def test_missing_bond_master_fails_closed_without_running_calculation() -> None:
    request = _request()
    missing_inputs = replace(request.inputs, bond=None)

    preview = RunFixedIncomeResearchPreview().execute(replace(request, inputs=missing_inputs))

    assert preview.status is ResearchPreviewStatus.BLOCKED
    assert preview.analytics is None
    assert "bond_master_missing" in preview.blocked_reasons


def test_stale_curve_publication_fails_closed() -> None:
    request = _request()
    curve = request.inputs.government_curve
    assert curve is not None
    stale_reference = replace(
        curve.reference,
        valid_until=datetime(2023, 12, 31, 23, tzinfo=UTC),
    )
    stale_inputs = replace(
        request.inputs,
        government_curve=replace(curve, reference=stale_reference),
    )

    preview = RunFixedIncomeResearchPreview().execute(replace(request, inputs=stale_inputs))

    assert preview.status is ResearchPreviewStatus.BLOCKED
    assert "government_curve_publication_stale" in preview.blocked_reasons


def test_missing_second_reliable_curve_fails_closed() -> None:
    request = _request()
    missing_inputs = replace(request.inputs, policy_bank_curve=None)

    preview = RunFixedIncomeResearchPreview().execute(replace(request, inputs=missing_inputs))

    assert preview.status is ResearchPreviewStatus.BLOCKED
    assert "policy_bank_curve_missing" in preview.blocked_reasons


def test_failed_duration_reconciliation_fails_closed() -> None:
    request = _request()
    failed_benchmark = replace(
        request.reconciliation,
        expected_modified_duration=Decimal("9"),
    )

    preview = RunFixedIncomeResearchPreview().execute(
        replace(request, reconciliation=failed_benchmark)
    )

    assert preview.status is ResearchPreviewStatus.BLOCKED
    assert preview.analytics is not None
    assert preview.reconciliation is not None
    assert preview.reconciliation.is_reconciled is False
    assert "duration_convexity_reconciliation_failed" in preview.blocked_reasons
