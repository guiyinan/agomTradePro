"""Contract tests for source-qualified portfolio capacity decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_capacity import (
    CapacityBasis,
    CapacityMeasure,
    CapacityOrderUsage,
    CapacityParticipationPolicy,
    CapacityUsageSnapshot,
    CapacityValue,
    CapacityWindowKind,
    CapacityWindowObservation,
    OrderSide,
    PortfolioCapacityDecision,
    evaluate_portfolio_capacity,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_AS_OF = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
_WINDOW_START = date(2026, 10, 23)
_WINDOW_END = date(2026, 10, 29)
_BUSINESS_DATE = date(2026, 10, 30)
_EXECUTION_DATE = date(2026, 10, 30)
_ACCOUNT_ID = 7
_ASSET_CODE = "000001.SZ"
_SECURITY_ID = "cn-equity:SZ:000001"
_PURPOSE = "ash07_portfolio_capacity"


def _source_evidence(
    *,
    precision: SourceObservationPrecision = SourceObservationPrecision.TIMESTAMP,
    observed_at: datetime | None = _AS_OF - timedelta(minutes=2),
    observed_on: date | None = None,
    available_at: datetime | None = _AS_OF - timedelta(minutes=1),
    known_at: datetime | None = _AS_OF - timedelta(minutes=1),
    valid_until: datetime | None = _AS_OF + timedelta(hours=1),
    restrictions: tuple[str, ...] = (),
    decision_date_cutoff: date | None = _BUSINESS_DATE,
) -> PortfolioRiskSourceEvidence:
    """Build one source record with real clocks and explicit complete coverage."""

    if precision is SourceObservationPrecision.DATE:
        observed_on = observed_on or _WINDOW_END
        observed_at = None
    return PortfolioRiskSourceEvidence(
        source_id="fixture:daily-bars",
        source_record_id="record:2026-10-29",
        original_payload_sha256="a" * 64,
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=observed_on,
        available_at=available_at,
        known_at=known_at,
        decision_cutoff=_AS_OF,
        decision_date_cutoff=decision_date_cutoff,
        valid_until=valid_until,
        source_purpose=_PURPOSE,
        allowed_purposes=(_PURPOSE,),
        restrictions=restrictions,
        must_not_use_for_decision=False,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="complete_capacity_window",
            reported_weight_fraction=Decimal("1"),
        ),
        effective_on=_WINDOW_END,
        effective_until=None,
    )


def _state_evidence(
    *,
    precision: SourceObservationPrecision = SourceObservationPrecision.TIMESTAMP,
    effective_on: date | None = _EXECUTION_DATE,
    observed_at: datetime | None = _AS_OF - timedelta(minutes=1),
    observed_on: date | None = None,
    available_at: datetime | None = _AS_OF - timedelta(seconds=30),
    known_at: datetime | None = _AS_OF - timedelta(seconds=30),
    valid_until: datetime | None = _AS_OF + timedelta(minutes=5),
    restrictions: tuple[str, ...] = (),
    must_not_use_for_decision: bool = False,
    decision_date_cutoff: date | None = _BUSINESS_DATE,
) -> PortfolioRiskSourceEvidence:
    """Build separate current-session trading-state evidence and clocks."""

    if precision is SourceObservationPrecision.DATE:
        observed_on = observed_on or _EXECUTION_DATE
        observed_at = None
    return PortfolioRiskSourceEvidence(
        source_id="fixture:trading-status",
        source_record_id="status:2026-10-30",
        original_payload_sha256="f" * 64,
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=observed_on,
        available_at=available_at,
        known_at=known_at,
        decision_cutoff=_AS_OF,
        decision_date_cutoff=decision_date_cutoff,
        valid_until=valid_until,
        source_purpose=_PURPOSE,
        allowed_purposes=(_PURPOSE,),
        restrictions=restrictions,
        must_not_use_for_decision=must_not_use_for_decision,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="execution_session_trading_state",
            expected_item_count=1,
            observed_item_count=1,
        ),
        effective_on=effective_on,
        effective_until=None,
    )


def _observation(
    *,
    window_kind: CapacityWindowKind = "rolling_sessions",
    window_sessions: int = 5,
    volume: CapacityValue = CapacityValue(Decimal("10000"), "share"),
    amount: CapacityValue = CapacityValue(Decimal("100000"), "CNY"),
    suspended: bool | None = False,
    evidence: PortfolioRiskSourceEvidence | None = None,
    state_date: date | None = _EXECUTION_DATE,
    state_evidence: PortfolioRiskSourceEvidence | None = None,
    include_state_evidence: bool = True,
) -> CapacityWindowObservation:
    """Build a five-session source window; tests override one contract at a time."""

    return CapacityWindowObservation(
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        window_kind=window_kind,
        window_start=(_WINDOW_END if window_kind == "session_cumulative" else _WINDOW_START),
        window_end=_WINDOW_END,
        window_sessions=window_sessions,
        volume=volume,
        amount=amount,
        execution_session_suspended=suspended,
        execution_session_state_date=state_date,
        execution_session_state_evidence=(
            state_evidence
            if state_evidence is not None
            else (_state_evidence() if include_state_evidence else None)
        ),
        source_evidence=evidence or _source_evidence(),
    )


def _policy(
    *,
    measure: CapacityMeasure = "volume",
    unit: str = "share",
    participation: Decimal = Decimal("0.10"),
    window_kind: CapacityWindowKind = "rolling_sessions",
    window_sessions: int = 5,
    increment: Decimal = Decimal("1"),
    allowed_precisions: tuple[SourceObservationPrecision, ...] = (
        SourceObservationPrecision.TIMESTAMP,
    ),
    effective_until: datetime | None = None,
    date_precision_purposes: tuple[str, ...] = (),
    allowed_source_restrictions: tuple[str, ...] = (),
) -> CapacityParticipationPolicy:
    """Build an immutable versioned participation policy."""

    capacity_basis: CapacityBasis = (
        "session_total" if window_kind == "session_cumulative" else "average_per_session"
    )
    return CapacityParticipationPolicy(
        policy_id="ash07-capacity",
        version="v1",
        content_hash="b" * 64,
        measure=measure,
        unit=unit,
        capacity_basis=capacity_basis,
        usage_scope="account_security_session",
        usage_date_basis="execution_session",
        max_participation=participation,
        capacity_increment=increment,
        window_kind=window_kind,
        window_sessions=window_sessions,
        effective_from=_AS_OF - timedelta(days=1),
        effective_until=effective_until,
        known_at=_AS_OF - timedelta(minutes=3),
        allowed_observation_precisions=allowed_precisions,
        date_precision_purposes=date_precision_purposes,
        allowed_source_restrictions=allowed_source_restrictions,
    )


def _order(
    order_id: str,
    *,
    side: OrderSide,
    volume: CapacityValue | None = None,
    amount: CapacityValue | None = None,
    account_id: int = _ACCOUNT_ID,
    asset_code: str = _ASSET_CODE,
    security_id: str = _SECURITY_ID,
) -> CapacityOrderUsage:
    """Build a single active or proposed order use in both supported measures."""

    return CapacityOrderUsage(
        order_id=order_id,
        account_id=account_id,
        asset_code=asset_code,
        security_id=security_id,
        side=side,
        volume=volume or CapacityValue(Decimal("0"), "share"),
        amount=amount or CapacityValue(Decimal("0"), "CNY"),
    )


def _usage(
    *,
    used: CapacityValue | None = None,
    active_orders: tuple[CapacityOrderUsage, ...] = (),
    proposed_orders: tuple[CapacityOrderUsage, ...] = (),
    capacity_date: date = _EXECUTION_DATE,
    executed_usage_complete: bool = True,
    active_orders_complete: bool = True,
) -> CapacityUsageSnapshot:
    """Bind executed use and active/new orders to one account, security and window."""

    if used is None:
        executed_volume = CapacityValue(Decimal("0"), "share")
        executed_amount = CapacityValue(Decimal("0"), "CNY")
    elif used.value is None:
        executed_volume = CapacityValue(None, None)
        executed_amount = CapacityValue(None, None)
    elif used.unit == "share":
        executed_volume = used
        executed_amount = CapacityValue(Decimal("0"), "CNY")
    elif used.unit == "CNY":
        executed_volume = CapacityValue(Decimal("0"), "share")
        executed_amount = used
    else:
        executed_volume = used
        executed_amount = CapacityValue(None, None)

    return CapacityUsageSnapshot(
        account_id=_ACCOUNT_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        capacity_date=capacity_date,
        snapshot_read_at=_AS_OF,
        volume=executed_volume,
        amount=executed_amount,
        executed_usage_complete=executed_usage_complete,
        active_orders_complete=active_orders_complete,
        active_orders=active_orders,
        proposed_orders=proposed_orders,
    )


def _evaluate(
    *,
    observation: CapacityWindowObservation | None = None,
    policy: CapacityParticipationPolicy | None = None,
    usage: CapacityUsageSnapshot | None = None,
    unconfigured: bool = False,
) -> PortfolioCapacityDecision:
    """Call the domain evaluator using the same exact cutoff and requested purpose."""

    return evaluate_portfolio_capacity(
        observation=observation or _observation(),
        policy=None if unconfigured else (policy or _policy()),
        usage=usage or _usage(),
        requested_purpose=_PURPOSE,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def test_capacity_divides_rolling_window_by_sessions_and_counts_both_sides_gross() -> None:
    """Executed use, active BUY/SELL holds and proposals share one gross budget."""

    result = _evaluate(
        usage=_usage(
            used=CapacityValue(Decimal("50"), "share"),
            active_orders=(
                _order("buy-1", side="buy", volume=CapacityValue(Decimal("20"), "share")),
                _order("sell-1", side="sell", volume=CapacityValue(Decimal("30"), "share")),
            ),
            proposed_orders=(
                _order("new-1", side="buy", volume=CapacityValue(Decimal("100"), "share")),
            ),
        )
    )

    assert result.status == "allowed"
    assert result.window_capacity == Decimal("200")
    assert result.used_capacity == Decimal("50")
    assert result.reserved_buy_capacity == Decimal("20")
    assert result.reserved_sell_capacity == Decimal("30")
    assert result.proposed_capacity == Decimal("100")
    assert result.allowed_new_capacity == Decimal("100")
    assert result.reason_codes == ()
    assert result.capacity_basis == "average_per_session"
    assert result.usage_scope == "account_security_session"
    assert result.usage_date_basis == "execution_session"
    assert result.business_date == _BUSINESS_DATE
    assert result.policy_date_precision_purposes == ()
    assert result.policy_allowed_source_restrictions == ()
    assert result.source_observed_at == _AS_OF - timedelta(minutes=2)
    assert result.source_available_at == _AS_OF - timedelta(minutes=1)
    assert result.executed_usage_complete is True
    assert result.active_orders_complete is True


def test_capacity_returns_a_partial_limit_without_netting_buy_and_sell_holds() -> None:
    """Opposite-side holds consume gross capacity and do not cancel each other."""

    result = _evaluate(
        usage=_usage(
            active_orders=(
                _order("buy-1", side="buy", volume=CapacityValue(Decimal("80"), "share")),
                _order("sell-1", side="sell", volume=CapacityValue(Decimal("80"), "share")),
            ),
            proposed_orders=(
                _order("new-1", side="buy", volume=CapacityValue(Decimal("50"), "share")),
            ),
        )
    )

    assert result.status == "partial"
    assert result.reserved_buy_capacity == Decimal("80")
    assert result.reserved_sell_capacity == Decimal("80")
    assert result.remaining_capacity == Decimal("40")
    assert result.allowed_new_capacity == Decimal("40")
    assert "CAPACITY_PROPOSAL_EXCEEDS_REMAINDER" in result.reason_codes


def test_amount_policy_uses_gross_order_notional_and_requires_exact_currency_unit() -> None:
    """SELL and BUY notional use the policy's amount unit without unit guessing."""

    result = _evaluate(
        policy=_policy(measure="amount", unit="CNY", participation=Decimal("0.10")),
        usage=_usage(
            used=CapacityValue(Decimal("1000"), "CNY"),
            active_orders=(
                _order("buy-1", side="buy", amount=CapacityValue(Decimal("500"), "CNY")),
                _order("sell-1", side="sell", amount=CapacityValue(Decimal("500"), "CNY")),
            ),
            proposed_orders=(
                _order("new-1", side="sell", amount=CapacityValue(Decimal("700"), "CNY")),
            ),
        ),
    )

    assert result.window_capacity == Decimal("2000")
    assert result.reserved_buy_capacity == Decimal("500")
    assert result.reserved_sell_capacity == Decimal("500")
    assert result.allowed_new_capacity == Decimal("0")
    assert result.status == "blocked"

    wrong_unit = _evaluate(
        policy=_policy(measure="amount", unit="CNY"),
        usage=_usage(
            used=CapacityValue(Decimal("0"), "CNY"),
            proposed_orders=(
                _order("new-2", side="buy", amount=CapacityValue(Decimal("1"), "share")),
            ),
        ),
    )
    assert wrong_unit.status == "unknown"
    assert "CAPACITY_ORDER_UNIT_MISMATCH" in wrong_unit.reason_codes


def test_unknown_used_capacity_or_active_order_measure_is_never_treated_as_zero() -> None:
    """Missing ledger usage or active order basis makes the capacity decision unknown."""

    missing_used = _evaluate(usage=_usage(used=CapacityValue(None, None)))
    assert missing_used.status == "unknown"
    assert "CAPACITY_USED_UNKNOWN" in missing_used.reason_codes

    missing_active = _evaluate(
        usage=_usage(
            active_orders=(_order("buy-unknown", side="buy", volume=CapacityValue(None, None)),)
        )
    )
    assert missing_active.status == "unknown"
    assert "CAPACITY_ACTIVE_ORDER_USE_UNKNOWN" in missing_active.reason_codes


def test_cross_account_or_security_order_use_is_rejected_without_filtering_it_away() -> None:
    """A caller cannot silently omit an order outside the requested projection scope."""

    result = _evaluate(
        usage=_usage(
            active_orders=(
                _order(
                    "foreign-security",
                    side="buy",
                    volume=CapacityValue(Decimal("1"), "share"),
                    security_id="another-security",
                ),
            )
        )
    )

    assert result.status == "unknown"
    assert "CAPACITY_ORDER_SCOPE_MISMATCH" in result.reason_codes


def test_incomplete_executed_usage_or_active_order_snapshot_cannot_be_assumed_zero() -> None:
    """Both actual fills and active order lists must attest complete read scope."""

    missing_fills = _evaluate(usage=_usage(executed_usage_complete=False))
    assert missing_fills.status == "unknown"
    assert "CAPACITY_EXECUTED_USAGE_INCOMPLETE" in missing_fills.reason_codes
    assert missing_fills.allowed_new_capacity is None

    missing_orders = _evaluate(usage=_usage(active_orders_complete=False))
    assert missing_orders.status == "unknown"
    assert "CAPACITY_ACTIVE_ORDER_SNAPSHOT_INCOMPLETE" in missing_orders.reason_codes
    assert missing_orders.allowed_new_capacity is None


@pytest.mark.parametrize(
    ("volume", "reason"),
    [
        (CapacityValue(Decimal("0"), "share"), "CAPACITY_ZERO_VOLUME"),
        (CapacityValue(None, None), "CAPACITY_VOLUME_UNKNOWN"),
    ],
)
def test_zero_and_unknown_window_capacity_have_distinct_outcomes(
    volume: CapacityValue,
    reason: str,
) -> None:
    """Zero liquidity blocks; absent liquidity remains unknown instead of zero."""

    result = _evaluate(observation=_observation(volume=volume))

    assert reason in result.reason_codes
    assert result.status == ("blocked" if volume.value == Decimal("0") else "unknown")
    assert result.allowed_new_capacity == (Decimal("0") if volume.value == Decimal("0") else None)


def test_amount_capacity_uses_amount_unit_and_blocks_zero_turnover() -> None:
    """An amount policy cannot borrow the volume field or turn zero turnover into capacity."""

    result = _evaluate(
        observation=_observation(amount=CapacityValue(Decimal("0"), "CNY")),
        policy=_policy(measure="amount", unit="CNY"),
        usage=_usage(used=CapacityValue(Decimal("0"), "CNY")),
    )

    assert result.status == "blocked"
    assert "CAPACITY_ZERO_AMOUNT" in result.reason_codes
    assert result.window_capacity == Decimal("0")
    assert result.allowed_new_capacity == Decimal("0")


def test_suspension_blocks_and_unknown_trading_status_remains_unknown() -> None:
    """A halt is a deterministic blocker; missing status is not an assumed open market."""

    suspended = _evaluate(observation=_observation(suspended=True))
    assert suspended.status == "blocked"
    assert "CAPACITY_TRADING_SUSPENDED" in suspended.reason_codes

    unknown = _evaluate(observation=_observation(suspended=None))
    assert unknown.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_UNKNOWN" in unknown.reason_codes


def test_rolling_window_and_execution_session_status_use_separate_source_clocks() -> None:
    """A prior DATE volume window cannot prove that today's session is open."""

    prior_window = _source_evidence(
        precision=SourceObservationPrecision.DATE,
        observed_on=_WINDOW_END,
        decision_date_cutoff=_BUSINESS_DATE,
    )
    policy = _policy(
        allowed_precisions=(
            SourceObservationPrecision.DATE,
            SourceObservationPrecision.TIMESTAMP,
        ),
        date_precision_purposes=(_PURPOSE,),
    )
    separate_current_status = _evaluate(
        observation=_observation(evidence=prior_window),
        policy=policy,
    )
    assert separate_current_status.status == "allowed"
    assert separate_current_status.source_observed_on == _WINDOW_END
    assert separate_current_status.execution_session_state_date == _EXECUTION_DATE
    assert separate_current_status.execution_session_state_evidence is not prior_window

    borrowed_window_status = _evaluate(
        observation=replace(
            _observation(evidence=prior_window),
            execution_session_state_evidence=prior_window,
        ),
        policy=policy,
    )
    assert borrowed_window_status.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_EFFECTIVE_DATE_MISMATCH" in (
        borrowed_window_status.reason_codes
    )


def test_missing_future_or_expired_execution_status_is_unknown_but_prohibition_blocks() -> None:
    """Unknown status stays unknown while explicit source prohibition blocks use."""

    missing = _evaluate(
        observation=_observation(
            include_state_evidence=False,
            state_date=None,
        ),
    )
    assert missing.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_EVIDENCE_MISSING" in missing.reason_codes
    assert missing.window_capacity is None
    assert missing.allowed_new_capacity is None

    future_date = date(2026, 11, 2)
    future = _evaluate(
        observation=_observation(
            state_date=future_date,
            state_evidence=_state_evidence(effective_on=future_date),
        ),
    )
    assert future.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_FUTURE_SESSION" in future.reason_codes
    assert future.allowed_new_capacity is None

    expired = _evaluate(
        observation=_observation(
            state_evidence=_state_evidence(valid_until=_AS_OF),
        ),
    )
    assert expired.status == "unknown"
    assert "RISK_SOURCE_EXPIRED_AT_CUTOFF" in expired.reason_codes

    prohibited = _evaluate(
        observation=_observation(
            state_evidence=_state_evidence(must_not_use_for_decision=True),
        ),
    )
    assert prohibited.status == "blocked"
    assert "RISK_SOURCE_PROHIBITED_FOR_DECISION" in prohibited.reason_codes


def test_date_precision_execution_status_needs_its_own_cutoff_permission() -> None:
    """A DATE status record is accepted only for its exact session and permitted purpose."""

    date_status = _state_evidence(
        precision=SourceObservationPrecision.DATE,
        observed_on=_EXECUTION_DATE,
    )
    date_policy = _policy(
        allowed_precisions=(SourceObservationPrecision.TIMESTAMP, SourceObservationPrecision.DATE),
        date_precision_purposes=(_PURPOSE,),
    )
    accepted = _evaluate(
        observation=_observation(state_evidence=date_status),
        policy=date_policy,
    )
    assert accepted.status == "allowed"
    assert accepted.execution_session_state_evidence is date_status

    not_permitted = _evaluate(
        observation=_observation(state_evidence=date_status),
        policy=_policy(
            allowed_precisions=(
                SourceObservationPrecision.TIMESTAMP,
                SourceObservationPrecision.DATE,
            ),
        ),
    )
    assert not_permitted.status == "unknown"
    assert "CAPACITY_TRADING_STATUS_DATE_PRECISION_NOT_ALLOWED" in (not_permitted.reason_codes)


def test_session_cumulative_is_not_misrepresented_as_a_rolling_multi_session_window() -> None:
    """A one-session source is accepted only with its explicit matching policy kind."""

    day_window = _observation(
        window_kind="session_cumulative",
        window_sessions=1,
        volume=CapacityValue(Decimal("1000"), "share"),
        amount=CapacityValue(Decimal("10000"), "CNY"),
        evidence=_source_evidence(
            precision=SourceObservationPrecision.DATE,
            observed_on=_WINDOW_END,
        ),
        state_date=_WINDOW_END,
        state_evidence=_state_evidence(
            precision=SourceObservationPrecision.DATE,
            effective_on=_WINDOW_END,
            observed_on=_WINDOW_END,
        ),
    )
    policy = _policy(
        window_kind="session_cumulative",
        window_sessions=1,
        allowed_precisions=(SourceObservationPrecision.DATE,),
        date_precision_purposes=(_PURPOSE,),
    )

    result = _evaluate(
        observation=day_window,
        policy=policy,
        usage=_usage(capacity_date=_WINDOW_END),
    )
    assert result.status == "allowed"
    assert result.window_capacity == Decimal("100")
    assert result.policy_date_precision_purposes == (_PURPOSE,)

    mismatched = _evaluate(
        observation=day_window,
        policy=_policy(),
        usage=_usage(capacity_date=_WINDOW_END),
    )
    assert mismatched.status == "unknown"
    assert "CAPACITY_WINDOW_POLICY_MISMATCH" in mismatched.reason_codes


def test_date_precision_source_needs_purpose_permission_and_exact_business_date_cutoff() -> None:
    """DATE evidence is allowed only by explicit purpose and matching business-date cutoff."""

    rolling_date_observation = _observation(
        evidence=_source_evidence(
            precision=SourceObservationPrecision.DATE,
            observed_on=_WINDOW_END,
            decision_date_cutoff=_BUSINESS_DATE,
        ),
    )
    rolling_date_policy = _policy(
        allowed_precisions=(
            SourceObservationPrecision.TIMESTAMP,
            SourceObservationPrecision.DATE,
        ),
        date_precision_purposes=(_PURPOSE,),
    )
    future_execution = _evaluate(
        observation=rolling_date_observation,
        policy=rolling_date_policy,
        usage=_usage(capacity_date=_EXECUTION_DATE),
    )
    assert future_execution.status == "allowed"
    assert future_execution.business_date == _BUSINESS_DATE
    assert future_execution.capacity_date == _EXECUTION_DATE

    date_observation = _observation(
        window_kind="session_cumulative",
        window_sessions=1,
        evidence=_source_evidence(
            precision=SourceObservationPrecision.DATE,
            observed_on=_WINDOW_END,
        ),
        state_date=_WINDOW_END,
        state_evidence=_state_evidence(
            precision=SourceObservationPrecision.DATE,
            effective_on=_WINDOW_END,
            observed_on=_WINDOW_END,
        ),
    )
    date_policy = _policy(
        window_kind="session_cumulative",
        window_sessions=1,
        allowed_precisions=(SourceObservationPrecision.DATE,),
    )
    not_permitted = _evaluate(
        observation=date_observation,
        policy=date_policy,
        usage=_usage(capacity_date=_WINDOW_END),
    )
    assert not_permitted.status == "unknown"
    assert "CAPACITY_DATE_PRECISION_PURPOSE_NOT_ALLOWED" in not_permitted.reason_codes
    assert not_permitted.window_capacity is None

    wrong_date_evidence = _source_evidence(
        precision=SourceObservationPrecision.DATE,
        observed_on=_WINDOW_END,
        decision_date_cutoff=date(2026, 10, 29),
    )
    wrong_date = _evaluate(
        observation=_observation(
            window_kind="session_cumulative",
            window_sessions=1,
            evidence=wrong_date_evidence,
            state_date=_WINDOW_END,
            state_evidence=_state_evidence(
                precision=SourceObservationPrecision.DATE,
                effective_on=_WINDOW_END,
                observed_on=_WINDOW_END,
            ),
        ),
        policy=_policy(
            window_kind="session_cumulative",
            window_sessions=1,
            allowed_precisions=(SourceObservationPrecision.DATE,),
            date_precision_purposes=(_PURPOSE,),
        ),
        usage=_usage(capacity_date=_WINDOW_END),
    )
    assert wrong_date.status == "unknown"
    assert "CAPACITY_DATE_CUTOFF_MISMATCH" in wrong_date.reason_codes
    assert wrong_date.allowed_new_capacity is None


def test_unqualified_stale_or_forbidden_source_never_produces_actionable_capacity() -> None:
    """The shared source qualifier supplies stable clock, purpose and restriction blockers."""

    stale = _evaluate(
        observation=_observation(
            evidence=_source_evidence(valid_until=_AS_OF),
        )
    )
    assert stale.status == "unknown"
    assert "RISK_SOURCE_EXPIRED_AT_CUTOFF" in stale.reason_codes
    assert stale.window_capacity is None
    assert stale.allowed_new_capacity is None

    forbidden_evidence = replace(
        _source_evidence(restrictions=("session_only",)),
        must_not_use_for_decision=True,
    )
    forbidden = _evaluate(
        observation=_observation(evidence=forbidden_evidence),
        policy=_policy(allowed_source_restrictions=("session_only",)),
    )
    assert forbidden.status == "blocked"
    assert "RISK_SOURCE_PROHIBITED_FOR_DECISION" in forbidden.reason_codes
    assert forbidden.window_capacity is None
    assert forbidden.allowed_new_capacity is None


def test_missing_or_future_source_availability_clock_never_produces_actionable_capacity() -> None:
    """A source observation cannot authorize use until its availability is known by cutoff."""

    missing_clock = _evaluate(
        observation=_observation(evidence=_source_evidence(available_at=None))
    )
    assert missing_clock.status == "unknown"
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" in missing_clock.reason_codes
    assert missing_clock.window_capacity is None
    assert missing_clock.allowed_new_capacity is None

    future_clock = _evaluate(
        observation=_observation(evidence=_source_evidence(known_at=_AS_OF + timedelta(seconds=1)))
    )
    assert future_clock.status == "unknown"
    assert "RISK_SOURCE_KNOWN_AT_AFTER_CUTOFF" in future_clock.reason_codes
    assert future_clock.allowed_new_capacity is None


def test_source_restrictions_require_explicit_versioned_policy_allowance() -> None:
    """Source restriction tokens stay fail-closed until policy explicitly authorizes each."""

    restricted = _observation(evidence=_source_evidence(restrictions=("closing_price_only",)))
    unapproved = _evaluate(observation=restricted)
    assert unapproved.status == "unknown"
    assert "RISK_SOURCE_RESTRICTION_NOT_ALLOWED" in unapproved.reason_codes
    assert unapproved.allowed_new_capacity is None

    allowed = _evaluate(
        observation=restricted,
        policy=_policy(allowed_source_restrictions=("closing_price_only",)),
    )
    assert allowed.status == "allowed"
    assert allowed.policy_allowed_source_restrictions == ("closing_price_only",)


@pytest.mark.parametrize(
    ("restriction", "source_purpose"),
    [
        ("must_not_use_for_decision", _PURPOSE),
        ("research_only", _PURPOSE),
        ("observation_only", _PURPOSE),
        ("eligible", "research_only"),
    ],
)
def test_unconditional_source_prohibitions_cannot_be_overridden_by_capacity_policy(
    restriction: str,
    source_purpose: str,
) -> None:
    """Source prohibitions remain blocked even if a policy attempts to authorize the token."""

    policy_allows_restriction = restriction == "eligible"
    if not policy_allows_restriction:
        with pytest.raises(ValueError):
            _policy(allowed_source_restrictions=(restriction,))

    evidence = replace(
        _source_evidence(restrictions=(restriction,)),
        source_purpose=source_purpose,
        must_not_use_for_decision=restriction == "must_not_use_for_decision",
    )
    result = _evaluate(
        observation=_observation(evidence=evidence),
        policy=_policy(
            allowed_source_restrictions=(restriction,) if policy_allows_restriction else ()
        ),
    )

    assert result.status == "blocked"
    assert any(reason.startswith("RISK_SOURCE_PROHIBITED_") for reason in result.reason_codes)
    assert result.window_capacity is None
    assert result.allowed_new_capacity is None


def test_partial_or_unknown_window_coverage_cannot_shrink_the_market_denominator() -> None:
    """An incomplete history never lowers the liquidity denominator and looks safe."""

    partial_evidence = replace(
        _source_evidence(),
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.PARTIAL,
            precision_basis="window_gap",
            expected_item_count=5,
            observed_item_count=4,
        ),
    )
    partial = _evaluate(observation=_observation(evidence=partial_evidence))
    assert partial.status == "unknown"
    assert "CAPACITY_WINDOW_COVERAGE_INCOMPLETE" in partial.reason_codes
    assert partial.window_capacity is None
    assert partial.allowed_new_capacity is None


def test_capacity_policy_must_be_present_versioned_current_and_complete() -> None:
    """There is no implicit participation default and an expired revision blocks."""

    missing = _evaluate(unconfigured=True)
    assert missing.status == "unknown"
    assert "CAPACITY_POLICY_UNCONFIGURED" in missing.reason_codes

    expired = _evaluate(policy=_policy(effective_until=_AS_OF))
    assert expired.status == "blocked"
    assert "CAPACITY_POLICY_EXPIRED" in expired.reason_codes
    assert expired.window_capacity is None
    assert expired.allowed_new_capacity is None


def test_rolling_source_lookback_is_separate_from_execution_session_usage_scope() -> None:
    """A completed historical lookback can size one later session without summing history."""

    result = _evaluate(
        observation=_observation(),
        usage=_usage(
            capacity_date=_EXECUTION_DATE,
            used=CapacityValue(Decimal("10"), "share"),
            proposed_orders=(
                _order("new-session", side="buy", volume=CapacityValue(Decimal("20"), "share")),
            ),
        ),
    )

    assert result.status == "allowed"
    assert result.source_window_start == _WINDOW_START
    assert result.source_window_end == _WINDOW_END
    assert result.capacity_date == _EXECUTION_DATE
    assert result.used_capacity == Decimal("10")
    assert result.window_capacity == Decimal("200")


def test_partial_buy_fill_and_remaining_hold_are_counted_once_in_current_session() -> None:
    """Today's booked fills and the order's unfilled remainder make the original total once."""

    result = _evaluate(
        usage=_usage(
            used=CapacityValue(Decimal("30"), "share"),
            active_orders=(
                _order(
                    "partially-filled-buy",
                    side="buy",
                    volume=CapacityValue(Decimal("70"), "share"),
                ),
            ),
            proposed_orders=(
                _order("second-order", side="buy", volume=CapacityValue(Decimal("100"), "share")),
            ),
        )
    )

    assert result.status == "allowed"
    assert result.used_capacity == Decimal("30")
    assert result.reserved_buy_capacity == Decimal("70")
    assert result.proposed_capacity == Decimal("100")


def test_unfilled_sell_remains_gross_usage_until_active_snapshot_drops_it() -> None:
    """A SELL reservation counts until cancellation/fill changes the locked active snapshot."""

    active_sell = _evaluate(
        usage=_usage(
            used=CapacityValue(Decimal("25"), "share"),
            active_orders=(
                _order("open-sell", side="sell", volume=CapacityValue(Decimal("125"), "share")),
            ),
            proposed_orders=(
                _order("new-buy", side="buy", volume=CapacityValue(Decimal("100"), "share")),
            ),
        )
    )
    assert active_sell.status == "partial"
    assert active_sell.used_capacity == Decimal("25")
    assert active_sell.reserved_sell_capacity == Decimal("125")
    assert active_sell.allowed_new_capacity == Decimal("50")

    after_cancel_snapshot = _evaluate(
        usage=_usage(
            used=CapacityValue(Decimal("25"), "share"),
            active_orders=(),
            proposed_orders=(
                _order("new-buy", side="buy", volume=CapacityValue(Decimal("100"), "share")),
            ),
        )
    )
    assert after_cancel_snapshot.status == "allowed"
    assert after_cancel_snapshot.used_capacity == Decimal("25")
    assert after_cancel_snapshot.reserved_sell_capacity == Decimal("0")
    assert after_cancel_snapshot.allowed_new_capacity == Decimal("100")
