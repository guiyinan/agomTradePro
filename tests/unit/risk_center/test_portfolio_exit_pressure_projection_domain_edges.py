"""Domain boundary cases for source-bound hypothetical exit capacity."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal

import pytest

from apps.risk_center.domain.portfolio_capacity import (
    CapacityParticipationPolicy,
    CapacityUsageSnapshot,
    CapacityValue,
    CapacityWindowObservation,
    PortfolioCapacityDecision,
    evaluate_portfolio_capacity,
)
from apps.risk_center.domain.portfolio_exit_pressure import (
    ExitCapacityWindow,
    ExitPressurePosition,
    PortfolioExitPressureInput,
    evaluate_portfolio_exit_pressure,
)
from apps.risk_center.domain.portfolio_exit_pressure_projection import (
    calculate_current_exit_capacity_window,
    calculate_future_exit_capacity_window,
    matching_exit_pressure_shocks,
    pending_exit_order_quantity,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    HeldPosition,
    OpenOrder,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ParametricShock,
    ParametricShockParameters,
    PortfolioExposure,
    ScenarioImpact,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
    scenario_factor_loading_attribute,
)

_AS_OF = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 10, 30)
_EXECUTION_SESSION = date(2026, 10, 30)
_WINDOW_START = date(2026, 10, 28)
_WINDOW_END = date(2026, 10, 29)
_ACCOUNT_ID = 7
_OWNER_USER_ID = 11
_ASSET_CODE = "000001.SZ"
_SECURITY_ID = "cn-equity:SZ:000001"
_PURPOSE = "ash07_portfolio_capacity"
_LIQUIDITY_SOURCE_ID = "fixture:liquidity"
_LIQUIDITY_RECORD_ID = "daily-bars:2026-10-29"
_STATE_SOURCE_ID = "fixture:session-state"
_STATE_RECORD_ID = "session:2026-10-30"
_SOURCE_IDS = (
    f"{_LIQUIDITY_SOURCE_ID}:{_LIQUIDITY_RECORD_ID}",
    f"{_STATE_SOURCE_ID}:{_STATE_RECORD_ID}",
)


@dataclass(frozen=True, slots=True)
class _CapacityCase:
    """Keep one typed account snapshot and its exact evaluated capacity inputs."""

    snapshot: AccountSnapshot
    observation: CapacityWindowObservation
    decision: PortfolioCapacityDecision
    evidence_by_id: dict[str, PortfolioRiskSourceEvidence]


def _coverage(status: CoverageStatus, *, state: bool = False) -> PortfolioRiskCoverage:
    """Build complete or explicitly incomplete source coverage evidence."""

    if status is CoverageStatus.COMPLETE:
        return PortfolioRiskCoverage(
            status=status,
            precision_basis="session_state" if state else "reported_sessions",
            reported_weight_fraction=Decimal("1"),
        )
    if status is CoverageStatus.PARTIAL:
        return PortfolioRiskCoverage(
            status=status,
            precision_basis="session_state" if state else "reported_sessions",
            reported_weight_fraction=Decimal("0.75"),
            expected_item_count=4,
            observed_item_count=3,
        )
    return PortfolioRiskCoverage(
        status=status,
        precision_basis="session_state" if state else "reported_sessions",
    )


def _source_evidence(
    *,
    source_id: str,
    source_record_id: str,
    effective_on: date,
    coverage: PortfolioRiskCoverage,
    precision: SourceObservationPrecision,
    available_at: datetime | None = _AS_OF - timedelta(minutes=1),
    must_not_use_for_decision: bool = False,
) -> PortfolioRiskSourceEvidence:
    """Retain actual timestamp or date precision without synthesizing a clock."""

    is_timestamp = precision is SourceObservationPrecision.TIMESTAMP
    is_date_only = precision is SourceObservationPrecision.DATE
    return PortfolioRiskSourceEvidence(
        source_id=source_id,
        source_record_id=source_record_id,
        original_payload_sha256="a" * 64,
        observation_precision=precision,
        observed_at=_AS_OF - timedelta(minutes=2) if is_timestamp else None,
        observed_on=effective_on if is_date_only else None,
        available_at=available_at,
        known_at=_AS_OF - timedelta(seconds=30),
        decision_cutoff=_AS_OF,
        decision_date_cutoff=_BUSINESS_DATE,
        valid_until=_AS_OF + timedelta(hours=1),
        source_purpose=_PURPOSE,
        allowed_purposes=(_PURPOSE,),
        restrictions=(),
        must_not_use_for_decision=must_not_use_for_decision,
        coverage=coverage,
        effective_on=effective_on,
    )


def _capacity_case(
    *,
    available_quantity: Decimal | None = Decimal("100"),
    held_quantity: Decimal = Decimal("100"),
    suspended: bool | None = False,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    precision: SourceObservationPrecision = SourceObservationPrecision.TIMESTAMP,
    state_precision: SourceObservationPrecision | None = None,
    available_at: datetime | None = _AS_OF - timedelta(minutes=1),
    must_not_use_for_decision: bool = False,
    include_state_evidence: bool = True,
    executed_usage_complete: bool = True,
    active_orders_complete: bool = True,
    measure: Literal["volume", "amount"] = "volume",
    market_volume: Decimal = Decimal("1000"),
    market_amount: Decimal = Decimal("1000"),
    used_capacity: Decimal = Decimal("0"),
    active_orders: tuple[OpenOrder, ...] = (),
) -> _CapacityCase:
    """Build one explicit, same-account/date/cutoff capacity decision."""

    main_source = _source_evidence(
        source_id=_LIQUIDITY_SOURCE_ID,
        source_record_id=_LIQUIDITY_RECORD_ID,
        effective_on=_WINDOW_END,
        coverage=_coverage(coverage_status),
        precision=precision,
        available_at=available_at,
        must_not_use_for_decision=must_not_use_for_decision,
    )
    state_source = (
        _source_evidence(
            source_id=_STATE_SOURCE_ID,
            source_record_id=_STATE_RECORD_ID,
            effective_on=_EXECUTION_SESSION,
            coverage=_coverage(CoverageStatus.COMPLETE, state=True),
            precision=precision if state_precision is None else state_precision,
        )
        if include_state_evidence
        else None
    )
    observation = CapacityWindowObservation(
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        window_kind="rolling_sessions",
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        window_sessions=2,
        volume=CapacityValue(market_volume, "share"),
        amount=CapacityValue(market_amount, "CNY"),
        execution_session_suspended=suspended,
        execution_session_state_date=(_EXECUTION_SESSION if include_state_evidence else None),
        execution_session_state_evidence=state_source,
        source_evidence=main_source,
    )
    allowed_precisions = (
        (SourceObservationPrecision.TIMESTAMP, SourceObservationPrecision.DATE)
        if precision is SourceObservationPrecision.DATE
        else (SourceObservationPrecision.TIMESTAMP,)
    )
    policy = CapacityParticipationPolicy(
        policy_id="test-capacity-policy",
        version="v1",
        content_hash="b" * 64,
        measure=measure,
        unit="share" if measure == "volume" else "CNY",
        capacity_basis="average_per_session",
        usage_scope="account_security_session",
        usage_date_basis="execution_session",
        max_participation=Decimal("1"),
        capacity_increment=Decimal("1"),
        window_kind="rolling_sessions",
        window_sessions=2,
        effective_from=_AS_OF - timedelta(days=1),
        effective_until=None,
        known_at=_AS_OF - timedelta(minutes=3),
        allowed_observation_precisions=allowed_precisions,
        date_precision_purposes=(_PURPOSE,) if precision is SourceObservationPrecision.DATE else (),
        allowed_source_restrictions=(),
    )
    usage = CapacityUsageSnapshot(
        account_id=_ACCOUNT_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        capacity_date=_EXECUTION_SESSION,
        snapshot_read_at=_AS_OF - timedelta(seconds=1),
        volume=(
            CapacityValue(used_capacity, "share")
            if measure == "volume"
            else CapacityValue(Decimal("0"), "share")
        ),
        amount=(
            CapacityValue(used_capacity, "CNY")
            if measure == "amount"
            else CapacityValue(Decimal("0"), "CNY")
        ),
        executed_usage_complete=executed_usage_complete,
        active_orders_complete=active_orders_complete,
        active_orders=(),
        proposed_orders=(),
    )
    decision = evaluate_portfolio_capacity(
        observation=observation,
        policy=policy,
        usage=usage,
        requested_purpose=_PURPOSE,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    snapshot = AccountSnapshot(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_USER_ID,
        snapshot_id="test-simulated-account-snapshot",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("10000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code=_ASSET_CODE,
                quantity=held_quantity,
                available_quantity=available_quantity,
                security_id=_SECURITY_ID,
            ),
        ),
        active_orders=active_orders,
        executed_usage=(),
        active_orders_complete=active_orders_complete,
        execution_session=_EXECUTION_SESSION,
        executed_usage_complete=executed_usage_complete,
    )
    evidence_by_id = {f"{main_source.source_id}:{main_source.source_record_id}": main_source}
    if state_source is not None:
        evidence_by_id[f"{state_source.source_id}:{state_source.source_record_id}"] = state_source
    return _CapacityCase(
        snapshot=snapshot,
        observation=observation,
        decision=decision,
        evidence_by_id=evidence_by_id,
    )


def _project_current(
    case: _CapacityCase,
    *,
    decisions: tuple[PortfolioCapacityDecision, ...] | None = None,
    evidence_by_id: dict[str, PortfolioRiskSourceEvidence] | None = None,
    price: Decimal | None = None,
    price_unit: str | None = None,
    money_unit: str | None = "CNY",
) -> tuple[ExitCapacityWindow, Decimal | None, tuple[str, ...], tuple[str, ...]]:
    """Project exactly one decision against the account's current session balance."""

    holding = case.snapshot.holdings[0]
    return calculate_current_exit_capacity_window(
        account_snapshot=case.snapshot,
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        held_quantity=holding.quantity,
        available_quantity=holding.available_quantity,
        quantity_unit="share",
        price=price,
        price_unit=price_unit,
        money_unit=money_unit,
        capacity_observation=case.observation,
        decisions=(case.decision,) if decisions is None else decisions,
        evidence_by_id=case.evidence_by_id if evidence_by_id is None else evidence_by_id,
        business_date=_BUSINESS_DATE,
    )


def _shock(
    shock_kind: str,
    magnitude: Decimal,
    *,
    target_kind: str = "asset",
    target: str = _ASSET_CODE,
    unit: ShockUnit = ShockUnit.PERCENT,
    horizon_days: int = 3,
) -> ParametricShock:
    """Construct one explicit typed assumption for a named asset/factor/date range."""

    return ParametricShock(
        target_kind=target_kind,
        target=target,
        shock_kind=shock_kind,
        magnitude=magnitude,
        unit=unit,
        horizon_days=horizon_days,
    )


def _revision(shocks: tuple[ParametricShock, ...]) -> ScenarioRevision:
    """Bind one approved parametric revision to explicit test shock assumptions."""

    return ScenarioRevision(
        revision_id="test-approved-exit-revision",
        scenario_key="test.exit-pressure",
        version=3,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=shocks,
            correlation_assumption="explicit test assumption",
        ),
        assumptions=("synthetic domain fixture only",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test-owner",
        change_reason="cover exit-capacity boundaries",
        created_at=_AS_OF,
    )


def _historical_revision() -> ScenarioRevision:
    """Build a non-parametric revision to prove exit shocks require typed shocks."""

    parameters = HistoricalWindowParameters(
        start_date=date(2026, 10, 20),
        end_date=_WINDOW_END,
        source="explicit-test-source",
        event_description="historical window fixture",
    )
    return ScenarioRevision(
        revision_id="test-historical-revision",
        scenario_key="test.historical",
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=parameters,
        assumptions=("synthetic domain fixture only",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test-owner",
        change_reason="exercise the non-parametric branch",
        created_at=_AS_OF,
    )


def _exit_window_request(
    case: _CapacityCase,
    windows: tuple[ExitCapacityWindow, ...],
    *,
    pending_sell_quantity: Decimal = Decimal("0"),
) -> PortfolioExitPressureInput:
    """Bind projected windows to one existing account snapshot and Scenario result."""

    revision = _revision((_shock("return", Decimal("-0.2")),))
    evidence = tuple(case.evidence_by_id.values())
    return PortfolioExitPressureInput(
        scenario_revision=revision,
        scenario_impact=ScenarioImpact(
            scenario_revision_id=revision.revision_id,
            initial_value=Decimal("1000"),
            final_value=Decimal("800"),
            total_return=Decimal("-0.2"),
            max_drawdown=Decimal("-0.2"),
            recovery_periods=0,
            volatility=Decimal("0"),
            var_95=Decimal("0.2"),
            var_99=Decimal("0.2"),
            period_start=None,
            period_end=None,
            result_hash="c" * 64,
        ),
        portfolio_snapshot_id=case.snapshot.snapshot_id,
        portfolio_snapshot_hash="a" * 64,
        as_of_time=_AS_OF,
        allocation_policy_version="test-policy-v1",
        code_version="test-code-version",
        scenario_market_data_hash="b" * 64,
        source_evidence=evidence,
        source_evidence_ids=tuple(case.evidence_by_id),
        positions=(
            ExitPressurePosition(
                asset_code=_ASSET_CODE,
                quantity=case.snapshot.holdings[0].quantity,
                quantity_unit="share",
                market_value=Decimal("1000"),
                pending_sell_quantity=pending_sell_quantity,
                capacity_windows=windows,
            ),
        ),
    )


def test_current_window_uses_capacity_evidence_and_limits_t1_balance() -> None:
    """Current exit capacity uses the exact session and never exceeds sellable T+1 quantity."""

    case = _capacity_case(available_quantity=Decimal("30"), held_quantity=Decimal("100"))
    window, market_quantity, source_ids, reasons = _project_current(case)

    assert market_quantity == Decimal("30")
    assert window.session_date == _EXECUTION_SESSION
    assert window.exitable_quantity == Decimal("30")
    assert window.source_evidence_ids == _SOURCE_IDS
    assert source_ids == _SOURCE_IDS
    assert "PORTFOLIO_PRESSURE_AVAILABLE_QUANTITY_LIMITED" in reasons


def test_current_window_without_exact_decision_or_source_is_unknown() -> None:
    """Missing or unbound capacity inputs remain unknown rather than becoming zero."""

    case = _capacity_case()
    missing, _, _, missing_reasons = _project_current(case, decisions=())
    duplicated, _, _, duplicate_reasons = _project_current(
        case,
        decisions=(case.decision, case.decision),
    )
    unbound, _, unbound_ids, unbound_reasons = _project_current(case, evidence_by_id={})

    assert missing.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_DECISION_MISSING" in missing_reasons
    assert duplicated.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_DECISION_MISSING" in duplicate_reasons
    assert unbound.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_SOURCE_UNBOUND" in unbound_reasons
    assert unbound_ids == ()


def test_current_window_rejects_a_decision_for_another_account_or_proposal() -> None:
    """Scope and usage-only decisions must match the exact owner snapshot."""

    case = _capacity_case()
    wrong_account = replace(case.decision, account_id=_ACCOUNT_ID + 1)
    has_proposal = replace(case.decision, proposed_capacity=Decimal("1"))

    for decision in (wrong_account, has_proposal):
        window, _, source_ids, reasons = _project_current(case, decisions=(decision,))
        assert window.exitable_quantity is None
        assert source_ids == ()
        assert "PORTFOLIO_PRESSURE_CAPACITY_DECISION_SCOPE_MISMATCH" in reasons


def test_date_precision_uses_source_dates_without_synthetic_observation_times() -> None:
    """A permitted date-only source remains date-only and bound to its observed session."""

    case = _capacity_case(
        precision=SourceObservationPrecision.DATE,
        state_precision=SourceObservationPrecision.TIMESTAMP,
    )
    window, _, source_ids, _ = _project_current(case)

    assert case.observation.source_evidence.observed_at is None
    assert case.observation.source_evidence.observed_on == _WINDOW_END
    assert case.observation.execution_session_state_evidence is not None
    assert case.observation.execution_session_state_evidence.observed_at == (
        _AS_OF - timedelta(minutes=2)
    )
    assert case.observation.execution_session_state_evidence.observed_on is None
    assert window.exitable_quantity == Decimal("500")
    assert source_ids == _SOURCE_IDS


def test_current_date_state_precision_requires_explicit_purpose_and_exact_cutoff() -> None:
    """Date-only state uses the explicit purpose allowlist and exact same-day cutoff."""

    case = _capacity_case(precision=SourceObservationPrecision.DATE)
    window, _, source_ids, _ = _project_current(case)

    assert case.observation.execution_session_state_evidence is not None
    state_evidence = case.observation.execution_session_state_evidence
    assert state_evidence.observed_at is None
    assert state_evidence.observed_on == _EXECUTION_SESSION
    assert _EXECUTION_SESSION == _BUSINESS_DATE
    assert state_evidence.decision_date_cutoff == _BUSINESS_DATE
    assert window.exitable_quantity == Decimal("500")
    assert source_ids == _SOURCE_IDS


def test_unknown_observation_precision_stays_unknown_without_a_fabricated_clock() -> None:
    """Unknown Source precision retains null observation fields and cannot support capacity."""

    case = _capacity_case(precision=SourceObservationPrecision.UNKNOWN)
    window, _, _, reasons = _project_current(case)

    assert case.observation.source_evidence.observed_at is None
    assert case.observation.source_evidence.observed_on is None
    assert window.exitable_quantity is None
    assert any(reason.startswith("RISK_SOURCE_") for reason in reasons)


@pytest.mark.parametrize(
    (
        "coverage_status",
        "available_at",
        "must_not_use_for_decision",
        "executed_usage_complete",
        "active_orders_complete",
        "include_state_evidence",
    ),
    [
        (CoverageStatus.PARTIAL, _AS_OF - timedelta(minutes=1), False, True, True, True),
        (CoverageStatus.COMPLETE, None, False, True, True, True),
        (CoverageStatus.COMPLETE, _AS_OF - timedelta(minutes=1), True, True, True, True),
        (CoverageStatus.COMPLETE, _AS_OF - timedelta(minutes=1), False, False, True, True),
        (CoverageStatus.COMPLETE, _AS_OF - timedelta(minutes=1), False, True, True, False),
        (CoverageStatus.COMPLETE, _AS_OF - timedelta(minutes=1), False, True, False, True),
    ],
    ids=(
        "partial-coverage",
        "unknown-availability",
        "prohibited-source",
        "unknown-usage",
        "missing-session-state",
        "incomplete-active-orders",
    ),
)
def test_unqualified_or_incomplete_current_capacity_is_unknown(
    coverage_status: CoverageStatus,
    available_at: datetime | None,
    must_not_use_for_decision: bool,
    executed_usage_complete: bool,
    active_orders_complete: bool,
    include_state_evidence: bool,
) -> None:
    """Incomplete source, usage, active-order, and session state cannot authorize exits."""

    case = _capacity_case(
        coverage_status=coverage_status,
        available_at=available_at,
        must_not_use_for_decision=must_not_use_for_decision,
        executed_usage_complete=executed_usage_complete,
        active_orders_complete=active_orders_complete,
        include_state_evidence=include_state_evidence,
    )
    window, _, _, reasons = _project_current(case)

    assert case.decision.status in {"unknown", "blocked"}
    assert window.exitable_quantity is None
    assert reasons


def test_blocked_positive_capacity_cannot_be_used_as_a_known_exit_window() -> None:
    """A blocked result with a stale positive remainder fails closed."""

    case = _capacity_case()
    blocked_positive = replace(
        case.decision,
        status="blocked",
        reason_codes=("CAPACITY_BLOCKED_RESULT",),
    )
    window, _, _, reasons = _project_current(case, decisions=(blocked_positive,))

    assert blocked_positive.remaining_capacity == Decimal("500")
    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_DECISION_BLOCKED" in reasons


def test_known_zero_and_unknown_sellable_quantity_remain_distinct() -> None:
    """A verified zero is known blocked, while absent T+1 availability stays unknown."""

    zero_case = _capacity_case(available_quantity=Decimal("0"))
    unknown_case = _capacity_case(available_quantity=None)
    zero_window, _, _, zero_reasons = _project_current(zero_case)
    unknown_window, _, _, unknown_reasons = _project_current(unknown_case)

    assert zero_window.exitable_quantity == Decimal("0")
    assert "CURRENT_POSITION_AVAILABLE_QUANTITY_ZERO" in zero_reasons
    assert unknown_window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_AVAILABLE_QUANTITY_UNKNOWN" in unknown_reasons


def test_suspension_and_exhausted_market_capacity_are_known_zero() -> None:
    """Explicit trading suspension and exhausted capacity return explained zero windows."""

    suspended = _capacity_case(suspended=True)
    suspended_window, _, _, suspended_reasons = _project_current(suspended)
    exhausted = _capacity_case(used_capacity=Decimal("500"))
    exhausted_window, _, _, exhausted_reasons = _project_current(exhausted)
    blocked_zero_case = _capacity_case()
    blocked_zero = replace(
        blocked_zero_case.decision,
        status="blocked",
        reason_codes=("CAPACITY_REMAINDER_EXHAUSTED",),
        remaining_capacity=Decimal("0"),
        allowed_new_capacity=Decimal("0"),
    )
    blocked_zero_window, _, _, blocked_zero_reasons = _project_current(
        blocked_zero_case,
        decisions=(blocked_zero,),
    )

    assert suspended.decision.status == "blocked"
    assert suspended_window.exitable_quantity == Decimal("0")
    assert "CURRENT_SESSION_TRADING_SUSPENDED" in suspended_reasons
    assert exhausted.decision.remaining_capacity == Decimal("0")
    assert exhausted_window.exitable_quantity == Decimal("0")
    assert "PORTFOLIO_PRESSURE_NO_REMAINING_CAPACITY" in exhausted_reasons
    assert blocked_zero_window.exitable_quantity == Decimal("0")
    assert "CAPACITY_REMAINDER_EXHAUSTED" in blocked_zero_reasons


def test_blocked_zero_requires_a_bound_policy_before_it_is_reported_as_known() -> None:
    """A zero remainder without the exact policy binding is not a qualified zero."""

    case = _capacity_case()
    unbound_policy = replace(
        case.decision,
        status="blocked",
        reason_codes=("CAPACITY_REMAINDER_EXHAUSTED",),
        policy_id=None,
        remaining_capacity=Decimal("0"),
    )
    window, _, source_ids, reasons = _project_current(case, decisions=(unbound_policy,))

    assert window.exitable_quantity is None
    assert source_ids == ()
    assert "PORTFOLIO_PRESSURE_CAPACITY_DECISION_BLOCKED" in reasons


def test_negative_remainder_and_volume_unit_mismatch_never_create_capacity() -> None:
    """Malformed remainders or incompatible quantity units stay unknown."""

    case = _capacity_case()
    negative_remainder = replace(case.decision, remaining_capacity=Decimal("-1"))
    wrong_unit = replace(case.decision, unit="board_lot")
    negative_window, _, _, negative_reasons = _project_current(
        case,
        decisions=(negative_remainder,),
    )
    wrong_unit_window, _, _, wrong_unit_reasons = _project_current(
        case,
        decisions=(wrong_unit,),
    )

    assert negative_window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_UNIT_OR_PRICE_UNKNOWN" in negative_reasons
    assert wrong_unit_window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_UNIT_OR_PRICE_UNKNOWN" in wrong_unit_reasons


@pytest.mark.parametrize(
    ("price", "price_unit", "money_unit"),
    [
        (None, "CNY", "CNY"),
        (Decimal("3"), "USD", "CNY"),
        (Decimal("3"), "CNY", None),
    ],
    ids=("missing-price", "currency-mismatch", "unknown-ledger-unit"),
)
def test_amount_capacity_needs_same_currency_and_qualified_price(
    price: Decimal | None,
    price_unit: str | None,
    money_unit: str | None,
) -> None:
    """Money capacity cannot be converted into shares with an unknown or mismatched unit."""

    case = _capacity_case(measure="amount", market_amount=Decimal("1000"))
    window, _, _, reasons = _project_current(
        case,
        price=price,
        price_unit=price_unit,
        money_unit=money_unit,
    )

    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_UNIT_OR_PRICE_UNKNOWN" in reasons


def test_amount_capacity_conversion_rounds_down_exactly() -> None:
    """Fractional share conversion never exceeds the source's exact currency budget."""

    case = _capacity_case(measure="amount", market_amount=Decimal("1000"))
    window, market_quantity, _, _ = _project_current(
        case,
        price=Decimal("3"),
        price_unit="CNY",
        money_unit="CNY",
    )

    assert market_quantity is not None
    assert window.exitable_quantity is not None
    assert Fraction(market_quantity) * 3 <= Fraction(500)
    assert Fraction(market_quantity) <= Fraction(500, 3)


def test_amount_rounding_steps_down_when_decimal_division_rounds_above_source_budget() -> None:
    """An upward-rounded decimal quotient is moved down before it becomes share capacity."""

    case = _capacity_case(measure="amount")
    decision = replace(case.decision, remaining_capacity=Decimal("2"))
    window, market_quantity, _, _ = _project_current(
        case,
        decisions=(decision,),
        price=Decimal("3"),
        price_unit="CNY",
        money_unit="CNY",
    )

    assert market_quantity is not None
    assert window.exitable_quantity is not None
    assert Fraction(market_quantity) * 3 <= Fraction(2)
    assert Fraction(market_quantity.next_plus()) * 3 > Fraction(2)


def test_future_capacity_requires_a_source_and_explicit_exit_assumption() -> None:
    """No calendar session receives positive capacity merely because a date was supplied."""

    session = date(2026, 11, 2)
    shock = _shock("exit_liquidity_change", Decimal("-0.25"))
    no_assumption = calculate_future_exit_capacity_window(
        session_date=session,
        quantity_unit="share",
        base_quantity=Decimal("80"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=_SOURCE_IDS,
        shocks=(),
    )
    no_source = calculate_future_exit_capacity_window(
        session_date=session,
        quantity_unit="share",
        base_quantity=Decimal("80"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=(),
        shocks=(shock,),
    )

    assert no_assumption.session_date == session
    assert no_assumption.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_EXIT_ASSUMPTION_MISSING" in no_assumption.reason_codes
    assert no_source.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_SOURCE_MISSING" in no_source.reason_codes


def test_halt_and_consecutive_limit_down_windows_are_known_zero() -> None:
    """Explicit caller dates remain zero under halt and consecutive lock assumptions."""

    # These dates are typed inputs; this pure helper does not generate a market calendar.
    assumptions = (
        (date(2026, 11, 2), "exit_halt"),
        (date(2026, 11, 3), "exit_limit_down_lock"),
        (date(2026, 11, 4), "exit_limit_down_lock"),
    )
    windows = tuple(
        calculate_future_exit_capacity_window(
            session_date=session,
            quantity_unit="share",
            base_quantity=None,
            held_quantity=Decimal("100"),
            available_quantity=None,
            source_evidence_ids=_SOURCE_IDS,
            shocks=(_shock(kind, Decimal("-1")),),
        )
        for session, kind in assumptions
    )

    assert tuple(window.session_date for window in windows) == tuple(
        session for session, _ in assumptions
    )
    assert all(window.exitable_quantity == Decimal("0") for window in windows)
    assert "SCENARIO_EXIT_HALT_ASSUMED" in windows[0].reason_codes
    assert "SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED" in windows[1].reason_codes
    assert "SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED" in windows[2].reason_codes
    assert all(window.source_evidence_ids == _SOURCE_IDS for window in windows)


def test_explicit_liquidity_decline_scales_capacity_and_factor_is_labeled() -> None:
    """A downside liquidity assumption scales only source capacity and remains disclosed."""

    window = calculate_future_exit_capacity_window(
        session_date=date(2026, 11, 2),
        quantity_unit="share",
        base_quantity=Decimal("80"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=_SOURCE_IDS,
        shocks=(
            _shock(
                "exit_liquidity_change",
                Decimal("-0.5"),
                target_kind="factor",
                target="banking",
            ),
        ),
    )

    assert window.exitable_quantity == Decimal("40.0")
    assert "SCENARIO_EXIT_LIQUIDITY_CHANGE_ASSUMED" in window.reason_codes
    assert "PORTFOLIO_PRESSURE_FACTOR_EXIT_ASSUMPTION_APPLIED_TO_FULL_ASSET" in (
        window.reason_codes
    )
    zero_capacity = calculate_future_exit_capacity_window(
        session_date=date(2026, 11, 3),
        quantity_unit="share",
        base_quantity=Decimal("80"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=_SOURCE_IDS,
        shocks=(_shock("exit_liquidity_change", Decimal("-1")),),
    )
    assert zero_capacity.exitable_quantity == Decimal("0")
    assert "SCENARIO_EXIT_LIQUIDITY_REDUCED_TO_ZERO" in zero_capacity.reason_codes


@pytest.mark.parametrize(
    ("base_quantity", "available_quantity"),
    [
        (Decimal("80"), None),
        (Decimal("80"), Decimal("30")),
        (None, Decimal("100")),
    ],
    ids=("available-unknown", "t1-available-below-holding", "capacity-unknown"),
)
def test_future_capacity_never_fills_unknown_t1_or_capacity_gaps(
    base_quantity: Decimal | None,
    available_quantity: Decimal | None,
) -> None:
    """Future sessions stay unknown when T+1 availability or the exact base is missing."""

    window = calculate_future_exit_capacity_window(
        session_date=date(2026, 11, 2),
        quantity_unit="share",
        base_quantity=base_quantity,
        held_quantity=Decimal("100"),
        available_quantity=available_quantity,
        source_evidence_ids=_SOURCE_IDS,
        shocks=(_shock("exit_liquidity_change", Decimal("-0.1")),),
    )

    assert window.exitable_quantity is None
    assert window.reason_codes
    assert window.source_evidence_ids == _SOURCE_IDS


@pytest.mark.parametrize(
    "shock",
    [
        _shock("exit_liquidity_change", Decimal("0.1")),
        _shock("exit_liquidity_change", Decimal("-0.1"), horizon_days=3651),
        _shock("exit_halt", Decimal("-0.5")),
        _shock("exit_limit_down_lock", Decimal("-1"), unit=ShockUnit.ABSOLUTE),
        _shock("return", Decimal("-0.1")),
    ],
    ids=(
        "positive-liquidity",
        "horizon-over-limit",
        "partial-halt",
        "wrong-lock-unit",
        "return-is-not-lock",
    ),
)
def test_invalid_or_price_shocks_cannot_create_future_exit_capacity(
    shock: ParametricShock,
) -> None:
    """Only bounded explicit exit assumptions may change a future capacity window."""

    window = calculate_future_exit_capacity_window(
        session_date=date(2026, 11, 2),
        quantity_unit="share",
        base_quantity=Decimal("80"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=_SOURCE_IDS,
        shocks=(shock,),
    )

    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_EXIT_ASSUMPTION_INVALID" in window.reason_codes


def test_matching_shocks_use_explicit_etf_factor_loading_not_issuer_industry() -> None:
    """ETF industry exposure is applied only through an explicit conservative loading."""

    revision = _revision(
        (
            _shock("return", Decimal("-0.3"), target_kind="factor", target="banking"),
            _shock("exit_halt", Decimal("-1"), target_kind="factor", target="banking"),
            _shock(
                "exit_liquidity_change",
                Decimal("-0.4"),
                target_kind="factor",
                target="banking",
            ),
            _shock("exit_limit_down_lock", Decimal("-1"), target="510300.SH"),
            _shock("exit_halt", Decimal("-1"), target_kind="factor", target="utilities"),
        )
    )
    etf_with_loading = PortfolioExposure(
        asset_code="510300.SH",
        weight=Decimal("0.5"),
        attributes=(
            ("asset_class", "etf"),
            scenario_factor_loading_attribute("banking", Decimal("0.4")),
        ),
    )
    etf_issuer_only = PortfolioExposure(
        asset_code="510500.SH",
        weight=Decimal("0.5"),
        attributes=(("issuer_industry", "banking"), ("asset_class", "etf")),
    )
    selected = matching_exit_pressure_shocks(revision, etf_with_loading)
    issuer_only = matching_exit_pressure_shocks(revision, etf_issuer_only)

    assert {(item.shock_kind, item.target_kind, item.target) for item in selected} == {
        ("exit_halt", "factor", "banking"),
        ("exit_liquidity_change", "factor", "banking"),
        ("exit_limit_down_lock", "asset", "510300.SH"),
    }
    assert issuer_only == ()


def test_matching_shocks_retains_legacy_exact_factor_match_and_nonparametric_unknown() -> None:
    """Legacy exact factor attributes still match while non-parametric revisions add none."""

    revision = _revision(
        (_shock("exit_halt", Decimal("-1"), target_kind="factor", target="banking"),)
    )
    equity = PortfolioExposure(
        asset_code="600000.SH",
        weight=Decimal("0.25"),
        attributes=(("factor", "banking"),),
    )
    historical = _historical_revision()

    assert matching_exit_pressure_shocks(revision, equity) == revision.parameters.shocks
    assert matching_exit_pressure_shocks(historical, equity) == ()


def test_pending_sells_are_scoped_and_unknown_holds_keep_capacity_unknown() -> None:
    """Only SELL reservations count, and incomplete active orders remain explicitly unknown."""

    sell = OpenOrder(
        order_id="pending-sell",
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        side="sell",
        remaining_quantity=Decimal("12"),
        remaining_amount=Decimal("120"),
    )
    buy_with_unknown_quantity = OpenOrder(
        order_id="pending-buy",
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        side="buy",
        remaining_quantity=None,
        remaining_amount=None,
    )
    complete = _capacity_case(active_orders=(sell, buy_with_unknown_quantity))
    total, incomplete = pending_exit_order_quantity(complete.snapshot, _ASSET_CODE)
    unknown_sell = replace(sell, order_id="unknown-sell", remaining_quantity=None)
    incomplete_case = _capacity_case(active_orders=(unknown_sell,))
    known_with_unknown_scope = _capacity_case(
        active_orders=(sell,),
        active_orders_complete=False,
    )

    assert total == Decimal("12")
    assert incomplete is False
    assert pending_exit_order_quantity(incomplete_case.snapshot, _ASSET_CODE) == (
        Decimal("0"),
        True,
    )
    assert pending_exit_order_quantity(known_with_unknown_scope.snapshot, _ASSET_CODE) == (
        Decimal("12"),
        True,
    )
    assert pending_exit_order_quantity(_capacity_case().snapshot, _ASSET_CODE) == (
        Decimal("0"),
        False,
    )


def test_cumulative_exit_does_not_exceed_available_balance_or_release_pending_exposure() -> None:
    """Large multi-session capacities cannot exceed sellable shares or shrink held exposure."""

    case = _capacity_case(available_quantity=Decimal("100"), held_quantity=Decimal("100"))
    current, _, _, _ = _project_current(case)
    future = calculate_future_exit_capacity_window(
        session_date=date(2026, 11, 2),
        quantity_unit="share",
        base_quantity=Decimal("500"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=_SOURCE_IDS,
        shocks=(_shock("exit_liquidity_change", Decimal("0")),),
    )
    request = _exit_window_request(
        case,
        (current, future),
        pending_sell_quantity=Decimal("20"),
    )
    finding = evaluate_portfolio_exit_pressure(request).findings[0]

    assert current.exitable_quantity == Decimal("500")
    assert future.exitable_quantity == Decimal("500")
    assert finding.hypothetical_exitable_quantity == Decimal("100")
    assert finding.pending_sell_quantity == Decimal("20")
    assert finding.unreleased_exposure_quantity == Decimal("100")
    assert finding.unreleased_exposure_market_value == Decimal("1000")


def test_later_session_without_sellable_balance_does_not_repeat_capacity() -> None:
    """A later date with unavailable T+1 quantity is unknown instead of repeated capacity."""

    case = _capacity_case(available_quantity=Decimal("30"), held_quantity=Decimal("100"))
    current, _, _, _ = _project_current(case)
    future = calculate_future_exit_capacity_window(
        session_date=date(2026, 11, 2),
        quantity_unit="share",
        base_quantity=Decimal("500"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("30"),
        source_evidence_ids=_SOURCE_IDS,
        shocks=(_shock("exit_liquidity_change", Decimal("0")),),
    )
    finding = evaluate_portfolio_exit_pressure(
        _exit_window_request(case, (current, future))
    ).findings[0]

    assert current.exitable_quantity == Decimal("30")
    assert future.session_date == date(2026, 11, 2)
    assert future.exitable_quantity is None
    assert finding.hypothetical_exitable_quantity == Decimal("30")
    assert finding.stress_window_residual_quantity is None
