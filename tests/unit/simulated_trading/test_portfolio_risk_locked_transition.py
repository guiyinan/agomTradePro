"""Serial locked-risk transition contracts for order validation and verification."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.application.portfolio_risk_locked_transition import (
    revalidate_locked_portfolio_fill,
    revalidate_locked_portfolio_order,
)
from apps.simulated_trading.application.portfolio_risk_qualification import (
    PortfolioRiskExecutionQualification,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_SECOND_CLOCK = _AS_OF + timedelta(seconds=2)
_SESSION = date(2026, 11, 3)


def _intent() -> SimulatedTradeIntent:
    """Build one exact simulated intent without touching any repository."""

    return SimulatedTradeIntent(
        account_id=12,
        user_id=4,
        idempotency_key="risk-locked-transition-test",
        side=SimulatedTradeSide.BUY,
        security_id="SSE:600036",
        asset_code="600036",
        asset_name="招商银行",
        asset_type="equity",
        market="SSE",
        board="MAIN",
        quantity=Decimal("100"),
        price=Decimal("10.2300"),
        reason="risk gate contract fixture",
        signal_id=None,
    )


def _qualification() -> PortfolioRiskExecutionQualification:
    """Build a valid short-lived proof for the fake risk guard."""

    return PortfolioRiskExecutionQualification(
        account_id=12,
        owner_user_id=4,
        execution_session=_SESSION,
        checked_at=_AS_OF,
        valid_until=_AS_OF + timedelta(minutes=10),
        policy_version="12",
        policy_content_sha256="a" * 64,
        runtime_config_sha256="b" * 64,
        baseline_source_sha256="c" * 64,
        native_limits_sha256="d" * 64,
        resource_snapshot_hash="e" * 64,
    )


class _RecordingRiskGuard:
    """Record the exact typed arguments and preserve ordered risk failures."""

    def __init__(
        self,
        *,
        qualification: PortfolioRiskExecutionQualification,
        events: list[str],
        validation_error: SimulatedTradeExecutionBlocked | None = None,
        verification_error: SimulatedTradeExecutionBlocked | None = None,
    ) -> None:
        self.qualification = qualification
        self.events = events
        self.validation_error = validation_error
        self.verification_error = verification_error
        self.market_purposes: list[str | None] = []
        self.validation_calls: list[tuple[SimulatedTradeIntent, Decimal, date, datetime]] = []
        self.verification_calls: list[tuple[PortfolioRiskExecutionQualification, datetime]] = []

    def validate_locked_order(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_cap: Decimal,
        market_purpose: str | None,
        as_of: datetime,
        execution_session: date,
    ) -> PortfolioRiskExecutionQualification:
        """Record the locked request, then return or reject its risk proof."""

        self.events.append("validate")
        self.market_purposes.append(market_purpose)
        self.validation_calls.append((intent, fee_cap, execution_session, as_of))
        if self.validation_error is not None:
            raise self.validation_error
        return self.qualification

    def verify_locked_qualification(
        self,
        *,
        qualification: PortfolioRiskExecutionQualification,
        as_of: datetime,
    ) -> None:
        """Record the second-clock check and preserve any expiry/policy failure."""

        self.events.append("verify")
        self.verification_calls.append((qualification, as_of))
        if self.verification_error is not None:
            raise self.verification_error


class _RecordingFillGuard:
    """Capture one actual fill event without translating it into a new order."""

    def __init__(
        self,
        *,
        qualification: PortfolioRiskExecutionQualification,
        events: list[str],
    ) -> None:
        self.qualification = qualification
        self.events = events
        self.market_purposes: list[str | None] = []
        self.validation_calls: list[
            tuple[SimulatedTradeIntent, LocalSimulatedFillEventV1, date, datetime]
        ] = []
        self.verification_calls: list[tuple[PortfolioRiskExecutionQualification, datetime]] = []

    def validate_locked_fill(
        self,
        *,
        intent: SimulatedTradeIntent,
        event: LocalSimulatedFillEventV1,
        market_purpose: str | None,
        execution_session: date,
        as_of: datetime,
    ) -> PortfolioRiskExecutionQualification:
        """Record the exact fill event and return the associated qualification."""

        self.events.append("validate_fill")
        self.market_purposes.append(market_purpose)
        self.validation_calls.append((intent, event, execution_session, as_of))
        return self.qualification

    def verify_locked_qualification(
        self,
        *,
        qualification: PortfolioRiskExecutionQualification,
        as_of: datetime,
    ) -> None:
        """Record the second-clock proof check for this fill transition."""

        self.events.append("verify")
        self.verification_calls.append((qualification, as_of))


def _fill_event() -> LocalSimulatedFillEventV1:
    """Build one exact local fill event for locked-helper contract tests."""

    return LocalSimulatedFillEventV1(
        source_namespace="test-matcher",
        source_version="v1",
        source_event_id="matcher-event-0001",
        event_payload_hash="1" * 64,
        source_snapshot_id="matcher-snapshot-01",
        source_snapshot_hash="2" * 64,
        reservation_id=73,
        account_id=12,
        user_id=4,
        order_idempotency_key="risk-locked-transition-test",
        intent_payload_hash="3" * 64,
        reservation_request_hash="4" * 64,
        plan_snapshot_hash="5" * 64,
        security_id="SSE:600036",
        asset_code="600036",
        side=SimulatedTradeSide.BUY,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("25.000000"),
        price=Decimal("10.2300"),
        occurred_at=_AS_OF - timedelta(seconds=5),
        source_observed_at=_AS_OF - timedelta(seconds=5),
        source_available_at=_AS_OF - timedelta(seconds=4),
        recorded_at=_AS_OF - timedelta(seconds=3),
    )


def test_locked_transition_passes_exact_fee_session_and_cutoffs_in_sequence() -> None:
    """Risk validates first, then a fresh server clock is checked before returning."""

    intent = _intent()
    fee_cap = Decimal("1.2300")
    qualification = _qualification()
    events: list[str] = []
    guard = _RecordingRiskGuard(qualification=qualification, events=events)

    def read_clock() -> datetime:
        """Return the real second test clock after the risk call."""

        events.append("read_clock")
        return _SECOND_CLOCK

    def read_execution_session(checked_at: datetime) -> date:
        """Return the exact active session for the second clock."""

        events.append("read_execution_session")
        assert checked_at is _SECOND_CLOCK
        return _SESSION

    result = revalidate_locked_portfolio_order(
        guard=guard,
        intent=intent,
        fee_cap=fee_cap,
        market_purpose="close_snapshot_simulation",
        execution_session=_SESSION,
        as_of=_AS_OF,
        read_clock=read_clock,
        read_execution_session=read_execution_session,
    )

    assert result is _SECOND_CLOCK
    assert events == ["validate", "read_clock", "read_execution_session", "verify"]
    assert guard.validation_calls == [(intent, fee_cap, _SESSION, _AS_OF)]
    assert guard.validation_calls[0][0] is intent
    assert guard.validation_calls[0][1] is fee_cap
    assert guard.validation_calls[0][2] is _SESSION
    assert guard.validation_calls[0][3] is _AS_OF
    assert guard.market_purposes == ["close_snapshot_simulation"]
    assert guard.verification_calls == [(qualification, _SECOND_CLOCK)]
    assert guard.verification_calls[0][0] is qualification


def test_missing_guard_returns_original_clock_without_any_read_or_guard_side_effect() -> None:
    """An unconfigured optional guard preserves legacy behavior without extra reads."""

    events: list[str] = []

    def read_clock() -> datetime:
        """Record any accidental second clock read."""

        events.append("read_clock")
        return _SECOND_CLOCK

    def read_execution_session(checked_at: datetime) -> date:
        """Record any accidental calendar read when no guard is configured."""

        events.append("read_execution_session")
        return checked_at.date()

    result = revalidate_locked_portfolio_order(
        guard=None,
        intent=_intent(),
        fee_cap=Decimal("1.23"),
        execution_session=_SESSION,
        as_of=_AS_OF,
        read_clock=read_clock,
        read_execution_session=read_execution_session,
    )

    assert result is _AS_OF
    assert events == []


def test_risk_validation_failure_prevents_second_clock_and_verification() -> None:
    """A failed current risk check stops before any post-check clock or verify step."""

    events: list[str] = []
    guard = _RecordingRiskGuard(
        qualification=_qualification(),
        events=events,
        validation_error=SimulatedTradeExecutionBlocked(
            "risk denied",
            code="PORTFOLIO_RISK_NOT_QUALIFIED",
        ),
    )

    def read_clock() -> datetime:
        """Record any clock read after a failed risk decision."""

        events.append("read_clock")
        return _SECOND_CLOCK

    def read_execution_session(checked_at: datetime) -> date:
        """Record an unexpected calendar lookup after failed risk validation."""

        events.append("read_execution_session")
        return _SESSION

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        revalidate_locked_portfolio_order(
            guard=guard,
            intent=_intent(),
            fee_cap=Decimal("1.23"),
            execution_session=_SESSION,
            as_of=_AS_OF,
            read_clock=read_clock,
            read_execution_session=read_execution_session,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert events == ["validate"]
    assert guard.verification_calls == []


def test_second_clock_verification_failure_stops_the_locked_transition() -> None:
    """An expired or replaced policy cannot return an execution clock to the caller."""

    events: list[str] = []
    guard = _RecordingRiskGuard(
        qualification=_qualification(),
        events=events,
        verification_error=SimulatedTradeExecutionBlocked(
            "risk proof expired",
            code="PORTFOLIO_RISK_EXECUTION_PROOF_EXPIRED",
        ),
    )

    def read_clock() -> datetime:
        """Return a fresh aware clock after the risk service check."""

        events.append("read_clock")
        return _SECOND_CLOCK

    def read_execution_session(checked_at: datetime) -> date:
        """Return the same session before the proof itself is rechecked."""

        events.append("read_execution_session")
        return _SESSION

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        revalidate_locked_portfolio_order(
            guard=guard,
            intent=_intent(),
            fee_cap=Decimal("1.23"),
            execution_session=_SESSION,
            as_of=_AS_OF,
            read_clock=read_clock,
            read_execution_session=read_execution_session,
        )

    assert error.value.code == "PORTFOLIO_RISK_EXECUTION_PROOF_EXPIRED"
    assert events == ["validate", "read_clock", "read_execution_session", "verify"]
    assert guard.verification_calls == [(_qualification(), _SECOND_CLOCK)]


def test_execution_session_change_after_second_clock_blocks_before_verification() -> None:
    """A session rollover between validation and transition prevents execution."""

    events: list[str] = []
    guard = _RecordingRiskGuard(qualification=_qualification(), events=events)

    def read_clock() -> datetime:
        """Read a fresh clock whose calendar session differs from the request."""

        events.append("read_clock")
        return _SECOND_CLOCK

    def read_execution_session(checked_at: datetime) -> date:
        """Report the next session after the original request session."""

        events.append("read_execution_session")
        assert checked_at is _SECOND_CLOCK
        return date(2026, 11, 4)

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        revalidate_locked_portfolio_order(
            guard=guard,
            intent=_intent(),
            fee_cap=Decimal("1.23"),
            execution_session=_SESSION,
            as_of=_AS_OF,
            read_clock=read_clock,
            read_execution_session=read_execution_session,
        )

    assert error.value.code == "PORTFOLIO_RISK_EXECUTION_SESSION_CHANGED"
    assert events == ["validate", "read_clock", "read_execution_session"]
    assert guard.verification_calls == []


def test_expired_execution_calendar_blocks_before_verification() -> None:
    """An expired calendar cannot qualify the second-clock execution session."""

    events: list[str] = []
    guard = _RecordingRiskGuard(qualification=_qualification(), events=events)

    def read_clock() -> datetime:
        """Read the real second clock before resolving the calendar again."""

        events.append("read_clock")
        return _SECOND_CLOCK

    def read_execution_session(checked_at: datetime) -> date:
        """Propagate the calendar evidence rejection without verifying risk."""

        events.append("read_execution_session")
        assert checked_at is _SECOND_CLOCK
        raise CalendarEvidenceValidationError("published execution calendar expired")

    with pytest.raises(CalendarEvidenceValidationError, match="expired"):
        revalidate_locked_portfolio_order(
            guard=guard,
            intent=_intent(),
            fee_cap=Decimal("1.23"),
            execution_session=_SESSION,
            as_of=_AS_OF,
            read_clock=read_clock,
            read_execution_session=read_execution_session,
        )

    assert events == ["validate", "read_clock", "read_execution_session"]
    assert guard.verification_calls == []


def test_locked_fill_rechecks_the_exact_accepted_event() -> None:
    """The helper forwards the accepted event itself rather than a new proposal."""

    intent = _intent()
    event = _fill_event()
    qualification = _qualification()
    events: list[str] = []
    guard = _RecordingFillGuard(qualification=qualification, events=events)

    def read_clock() -> datetime:
        """Return the second server clock after checking the reserved fill."""

        events.append("read_clock")
        return _SECOND_CLOCK

    result = revalidate_locked_portfolio_fill(
        guard=guard,
        intent=intent,
        event=event,
        market_purpose="local_simulation_only",
        execution_session=_SESSION,
        as_of=_AS_OF,
        read_clock=read_clock,
    )

    assert result is _SECOND_CLOCK
    assert events == ["validate_fill", "read_clock", "verify"]
    assert guard.validation_calls == [(intent, event, _SESSION, _AS_OF)]
    assert guard.validation_calls[0][0] is intent
    assert guard.validation_calls[0][1] is event
    assert guard.market_purposes == ["local_simulation_only"]
    assert guard.verification_calls == [(qualification, _SECOND_CLOCK)]


def test_missing_fill_guard_returns_original_clock_without_reading_clock() -> None:
    """An absent fill guard preserves the source event transition without reads."""

    events: list[str] = []

    def read_clock() -> datetime:
        """Record an accidental second clock read."""

        events.append("read_clock")
        return _SECOND_CLOCK

    result = revalidate_locked_portfolio_fill(
        guard=None,
        intent=_intent(),
        event=_fill_event(),
        execution_session=_SESSION,
        as_of=_AS_OF,
        read_clock=read_clock,
    )

    assert result is _AS_OF
    assert events == []
