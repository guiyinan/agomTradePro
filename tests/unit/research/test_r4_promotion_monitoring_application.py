"""Application-boundary tests for ID-only R4 monitoring."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoring,
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringUnavailable,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_evidence import R4PromotionR3AttestationEvidence
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessmentStatus,
    R4MonitoringBlockerCode,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
)
from apps.research.domain.r4_promotion_record_seal import R4PromotionPortfolioRecordSeal
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)


class AtomicState:
    """Synthetic shared transaction and call trace."""

    def __init__(self) -> None:
        self.key = "research-r4-monitoring-uow"
        self.active = False
        self.calls: list[str] = []


class UnitOfWork:
    """Minimal shared UoW used only by synthetic tests."""

    def __init__(self, state: AtomicState) -> None:
        self.state = state

    @property
    def unit_of_work_key(self) -> str:
        return self.state.key

    @contextmanager
    def atomic(self) -> Iterator[None]:
        assert self.state.active is False
        self.state.active = True
        try:
            yield
        finally:
            self.state.active = False


class BoundProvider:
    """Base synthetic provider with an explicit UoW identity."""

    def __init__(self, state: AtomicState) -> None:
        self.state = state
        self.key_override: str | None = None

    @property
    def unit_of_work_key(self) -> str:
        return self.key_override or self.state.key

    def record(self, label: str) -> None:
        assert self.state.active is True
        self.state.calls.append(label)


class ActiveDecisionProvider(BoundProvider):
    def __init__(self, state: AtomicState, value: R4PromotionDecision | None) -> None:
        super().__init__(state)
        self.value = value
        self.error: Exception | None = None
        self.drift_key_on_read: str | None = None

    def get_exact_active(self, **_: object) -> R4PromotionDecision | None:
        self.record("active")
        if self.error is not None:
            raise self.error
        if self.drift_key_on_read is not None:
            self.state.key = self.drift_key_on_read
        return self.value


class PolicyProvider(BoundProvider):
    def __init__(self, state: AtomicState, value: R4MonitoringPolicy | None) -> None:
        super().__init__(state)
        self.value = value

    def get_exact(self, **_: object) -> R4MonitoringPolicy | None:
        self.record("policy")
        return self.value


class PortfolioProvider(BoundProvider):
    def __init__(self, state: AtomicState, value: R4PromotionPortfolioRecordSeal | None) -> None:
        super().__init__(state)
        self.value = value

    def get_exact(self, **_: object) -> R4PromotionPortfolioRecordSeal | None:
        self.record("portfolio")
        return self.value


class R3Provider(BoundProvider):
    def __init__(self, state: AtomicState, value: R4PromotionR3AttestationEvidence | None) -> None:
        super().__init__(state)
        self.value = value

    def get_exact(self, **_: object) -> R4PromotionR3AttestationEvidence | None:
        self.record("r3")
        return self.value


class CalendarProvider(BoundProvider):
    def __init__(self, state: AtomicState, value: R4MonitoringPeriodCalendar | None) -> None:
        super().__init__(state)
        self.value = value

    def get_exact(self, **_: object) -> R4MonitoringPeriodCalendar | None:
        self.record("calendar")
        return self.value


class RawFactProvider(BoundProvider):
    def __init__(
        self,
        state: AtomicState,
        value: tuple[R4MonitoringObservation, ...],
    ) -> None:
        super().__init__(state)
        self.value = value

    def list_exact(self, **_: object) -> tuple[R4MonitoringObservation, ...]:
        self.record("facts")
        return self.value


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class Ports:
    """Mutable synthetic owner graph for boundary variations."""

    def __init__(self) -> None:
        self.state = AtomicState()
        self.decision = monitoring_decision()
        self.calendar = monitoring_calendar(self.decision)
        self.policy = monitoring_policy(self.decision, self.calendar)
        self.observations = tuple(
            monitoring_observation(
                period_index=index,
                decision=self.decision,
                calendar=self.calendar,
                policy=self.policy,
            )
            for index in range(2)
        )
        self.active = ActiveDecisionProvider(self.state, self.decision)
        self.policy_provider = PolicyProvider(self.state, self.policy)
        self.portfolio = PortfolioProvider(
            self.state,
            self.decision.trial.portfolio_record,
        )
        self.r3 = R3Provider(
            self.state,
            self.decision.trial.current_r3_attestation,
        )
        self.calendar_provider = CalendarProvider(self.state, self.calendar)
        self.facts = RawFactProvider(self.state, self.observations)
        self.uow = UnitOfWork(self.state)
        self.clock = Clock(self.calendar.valid_from + timedelta(hours=3))

    def use_case(self) -> EvaluateR4PromotionMonitoring:
        return EvaluateR4PromotionMonitoring(
            active_decision_provider=self.active,
            policy_provider=self.policy_provider,
            portfolio_result_provider=self.portfolio,
            r3_attestation_provider=self.r3,
            period_calendar_provider=self.calendar_provider,
            raw_fact_provider=self.facts,
            unit_of_work=self.uow,
            clock=self.clock,
        )

    def command(self) -> EvaluateR4PromotionMonitoringCommand:
        return EvaluateR4PromotionMonitoringCommand(
            active_decision=R4PromotionDecisionIdentity.from_decision(self.decision),
            policy_id=self.policy.policy_id,
            policy_version=self.policy.policy_version,
            expected_policy_hash=self.policy.content_hash,
            as_of=self.calendar.valid_from + timedelta(hours=2, minutes=30),
        )


def test_command_is_identity_only_and_every_owner_is_reread_in_one_uow() -> None:
    """No caller metric or threshold can enter the orchestration boundary."""

    ports = Ports()

    evidence = ports.use_case().execute_evidence(ports.command())

    assert {item.name for item in fields(EvaluateR4PromotionMonitoringCommand)} == {
        "active_decision",
        "policy_id",
        "policy_version",
        "expected_policy_hash",
        "as_of",
    }
    assert ports.state.calls == ["active", "portfolio", "r3", "policy", "calendar", "facts"]
    assert ports.state.active is False
    assert evidence.assessment.status is R4MonitoringAssessmentStatus.HEALTHY
    assert evidence.assessment.automatic_retirement is False


@pytest.mark.parametrize(
    ("missing", "expected"),
    (
        ("active", R4MonitoringBlockerCode.ACTIVE_DECISION_MISSING),
        ("portfolio", R4MonitoringBlockerCode.PORTFOLIO_RESULT_MISSING),
        ("r3", R4MonitoringBlockerCode.R3_ATTESTATION_MISSING),
        ("policy", R4MonitoringBlockerCode.POLICY_MISSING),
        ("calendar", R4MonitoringBlockerCode.PERIOD_CALENDAR_MISSING),
        ("facts", R4MonitoringBlockerCode.OBSERVATIONS_MISSING),
    ),
)
def test_missing_owner_evidence_returns_a_blocked_assessment(
    missing: str,
    expected: R4MonitoringBlockerCode,
) -> None:
    """Canonical absence is explicit and never becomes a healthy default."""

    ports = Ports()
    if missing == "active":
        ports.active.value = None
    elif missing == "portfolio":
        ports.portfolio.value = None
    elif missing == "r3":
        ports.r3.value = None
    elif missing == "policy":
        ports.policy_provider.value = None
    elif missing == "calendar":
        ports.calendar_provider.value = None
    else:
        ports.facts.value = ()

    result = ports.use_case().execute(ports.command())

    assert result.status is R4MonitoringAssessmentStatus.BLOCKED
    assert expected in result.blockers


def test_future_cutoff_and_provider_failure_are_normalized_unavailable() -> None:
    """Clock and owner failures cannot leak partial or caller-selected state."""

    ports = Ports()
    future = ports.command()
    ports.clock.value = future.as_of - timedelta(seconds=1)
    with pytest.raises(R4MonitoringUnavailable, match="future"):
        ports.use_case().execute(future)
    assert ports.state.calls == []

    ports = Ports()
    ports.active.error = LookupError("owner offline")
    with pytest.raises(R4MonitoringUnavailable, match="owner graph"):
        ports.use_case().execute(ports.command())


def test_uow_mismatch_and_runtime_key_drift_fail_closed() -> None:
    """All exact reads must retain the construction-time shared UoW identity."""

    ports = Ports()
    ports.facts.key_override = "other-uow"
    with pytest.raises(R4MonitoringUnavailable, match="units of work"):
        ports.use_case()

    ports = Ports()
    use_case = ports.use_case()
    ports.state.key = "drifted-uow"
    with pytest.raises(R4MonitoringUnavailable, match="changed"):
        use_case.execute(ports.command())
    assert ports.state.calls == []


def test_command_is_revalidated_and_early_missing_return_rechecks_uow() -> None:
    """Frozen-object tamper and a drifting early-return provider are normalized."""

    ports = Ports()
    command = ports.command()
    object.__setattr__(command, "as_of", object())
    with pytest.raises(R4MonitoringUnavailable, match="command"):
        ports.use_case().execute(command)
    assert ports.state.calls == []

    ports = Ports()
    ports.active.value = None
    ports.active.drift_key_on_read = "drifted-on-missing"
    with pytest.raises(R4MonitoringUnavailable, match="changed"):
        ports.use_case().execute(ports.command())


def test_malformed_owner_hash_is_normalized_before_domain_recomputation() -> None:
    """A malformed frozen owner object cannot escape as an incidental exception."""

    ports = Ports()
    command = ports.command()
    object.__setattr__(ports.policy, "content_hash", object())

    with pytest.raises(R4MonitoringUnavailable, match="owner graph"):
        ports.use_case().execute(command)
