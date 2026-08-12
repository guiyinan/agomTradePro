"""Pure contracts for the read-only R4 research-control preflight."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime, timedelta
from decimal import Decimal
from inspect import signature

import pytest

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_research_control_preflight import (
    EvaluateR4ResearchControlPreflight,
    EvaluateR4ResearchControlPreflightCommand,
    R4ResearchControlBlockerCode,
    R4ResearchControlMonitoringEvidence,
    R4ResearchControlPreflightStatus,
    R4ResearchControlUnavailable,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessmentStatus,
    R4MonitoringMetricKey,
    evaluate_r4_promotion_monitoring,
)
from apps.research.r4_research_control_composition import (
    build_django_r4_research_control_runtime,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)


def _monitoring(
    *,
    status: R4MonitoringAssessmentStatus = R4MonitoringAssessmentStatus.HEALTHY,
) -> R4ResearchControlMonitoringEvidence:
    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    overrides: tuple[dict[R4MonitoringMetricKey, Decimal], ...]
    if status is R4MonitoringAssessmentStatus.HEALTHY:
        overrides = ({}, {})
    elif status is R4MonitoringAssessmentStatus.BREACHED:
        overrides = ({}, {R4MonitoringMetricKey.RELATIVE_NET_RETURN: Decimal("-0.01")})
    else:
        overrides = (
            {R4MonitoringMetricKey.RELATIVE_NET_RETURN: Decimal("-0.01")},
            {R4MonitoringMetricKey.RELATIVE_NET_RETURN: Decimal("-0.01")},
        )
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
            value_overrides=overrides[index],
        )
        for index in range(2)
    )
    evaluated_at = calendar.valid_from + timedelta(hours=2, minutes=30)
    assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        requested_policy_id=policy.policy_id,
        requested_policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        evaluated_at=evaluated_at,
    )
    assert assessment.status is status
    return R4ResearchControlMonitoringEvidence.create(
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        assessment=assessment,
        ledger_recorded_at=evaluated_at,
    )


def _owner_graph(
    monitoring: R4ResearchControlMonitoringEvidence,
) -> R4MonitoringEvaluationEvidence:
    return R4MonitoringEvaluationEvidence(
        active_decision=monitoring.active_decision,
        portfolio_result=monitoring.portfolio_result,
        current_r3_attestation=monitoring.current_r3_attestation,
        policy=monitoring.policy,
        period_calendar=monitoring.period_calendar,
        observations=monitoring.observations,
        assessment=monitoring.assessment,
    )


class _UnitOfWork:
    unit_of_work_key = "django:r4-control-test"

    def __init__(self, server_time: datetime) -> None:
        self.server_time = server_time
        self.entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.entries += 1
        yield

    def server_now(self) -> datetime:
        return self.server_time


class _ActiveProvider:
    unit_of_work_key = "django:r4-control-test"

    def __init__(self, values: tuple[R4PromotionDecisionIdentity | None, ...]) -> None:
        self.values = values
        self.calls = 0

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R4PromotionDecisionIdentity | None:
        assert scope_id == monitoring_decision().scope.scope_id
        assert as_of == _monitoring().assessment.evaluated_at
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class _MonitoringProvider:
    unit_of_work_key = "django:r4-control-test"

    def __init__(
        self,
        values: tuple[R4ResearchControlMonitoringEvidence | None, ...],
    ) -> None:
        self.values = values
        self.calls = 0

    def get_latest_complete(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4ResearchControlMonitoringEvidence | None:
        assert active_decision.scope.scope_id == monitoring_decision().scope.scope_id
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class _OwnerGraphProvider:
    unit_of_work_key = "django:r4-control-test"

    def __init__(self, values: tuple[R4MonitoringEvaluationEvidence, ...]) -> None:
        self.values = values
        self.calls = 0

    def execute_evidence(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        assert command.as_of == _monitoring().assessment.evaluated_at
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def _service(
    *,
    monitoring_values: tuple[R4ResearchControlMonitoringEvidence | None, ...] | None = None,
    active_values: tuple[R4PromotionDecisionIdentity | None, ...] | None = None,
    owner_values: tuple[R4MonitoringEvaluationEvidence, ...] | None = None,
) -> tuple[
    EvaluateR4ResearchControlPreflight,
    _ActiveProvider,
    _MonitoringProvider,
    _OwnerGraphProvider,
    _UnitOfWork,
]:
    monitoring = _monitoring()
    identity = R4PromotionDecisionIdentity.from_decision(monitoring.active_decision)
    active = _ActiveProvider(active_values or (identity, identity))
    monitoring_provider = _MonitoringProvider(monitoring_values or (monitoring, monitoring))
    graph = _owner_graph(monitoring)
    owner = _OwnerGraphProvider(owner_values or (graph, graph))
    uow = _UnitOfWork(monitoring.assessment.evaluated_at + timedelta(minutes=5))
    return (
        EvaluateR4ResearchControlPreflight(
            active_promotion_provider=active,
            monitoring_provider=monitoring_provider,
            owner_graph_provider=owner,
            unit_of_work=uow,
        ),
        active,
        monitoring_provider,
        owner,
        uow,
    )


def _command() -> EvaluateR4ResearchControlPreflightCommand:
    monitoring = _monitoring()
    return EvaluateR4ResearchControlPreflightCommand(
        scope_id=monitoring.active_decision.scope.scope_id,
        as_of=monitoring.assessment.evaluated_at,
    )


def test_preflight_double_reads_full_owner_graph_and_only_allows_manual_review() -> None:
    service, active, monitoring, owner, uow = _service()

    result = service.execute(_command())

    expected = _monitoring()
    assert result.status is R4ResearchControlPreflightStatus.ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW
    assert result.blocker_codes == ()
    assert result.active_decision_hash == expected.active_decision.content_hash
    assert result.monitoring_assessment_hash == expected.assessment.content_hash
    assert result.portfolio_record_hash == expected.portfolio_result.content_hash
    assert result.r3_attestation_hash == expected.current_r3_attestation.content_hash
    assert result.monitoring_policy_hash == expected.policy.content_hash
    assert result.period_calendar_hash == expected.period_calendar.content_hash
    assert result.observation_hashes == tuple(item.content_hash for item in expected.observations)
    assert result.research_only is True
    assert result.must_not_publish_current is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True
    assert (active.calls, monitoring.calls, owner.calls, uow.entries) == (2, 2, 2, 1)


@pytest.mark.parametrize(
    ("status", "blocker"),
    (
        (
            R4MonitoringAssessmentStatus.BREACHED,
            R4ResearchControlBlockerCode.LATEST_MONITORING_BREACHED,
        ),
        (
            R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
            R4ResearchControlBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW,
        ),
    ),
)
def test_latest_nonhealthy_assessment_cannot_be_cherry_picked(
    status: R4MonitoringAssessmentStatus,
    blocker: R4ResearchControlBlockerCode,
) -> None:
    latest = _monitoring(status=status)
    graph = _owner_graph(latest)
    service, _, _, _, _ = _service(
        monitoring_values=(latest, latest),
        owner_values=(graph, graph),
    )

    result = service.execute(_command())

    assert result.status is R4ResearchControlPreflightStatus.BLOCKED
    assert result.blocker_codes == (blocker,)


def test_missing_changed_or_tampered_owner_graph_is_stably_blocked() -> None:
    service, _, monitoring_provider, owner, _ = _service(active_values=(None, None))
    missing = service.execute(_command())
    assert missing.blocker_codes == (R4ResearchControlBlockerCode.ACTIVE_PROMOTION_UNAVAILABLE,)
    assert monitoring_provider.calls == 0
    assert owner.calls == 0

    monitoring = _monitoring()
    changed = R4PromotionDecisionIdentity.from_decision(monitoring.active_decision)
    object.__setattr__(changed, "decision_version", "v2")
    service, _, _, _, _ = _service(
        active_values=(
            R4PromotionDecisionIdentity.from_decision(monitoring.active_decision),
            changed,
        )
    )
    drift = service.execute(_command())
    assert drift.blocker_codes == (
        R4ResearchControlBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
    )

    tampered = _monitoring()
    object.__setattr__(tampered.assessment, "content_hash", "f" * 64)
    object.__setattr__(tampered.assessment, "__post_init__", lambda: None)
    service, _, _, _, _ = _service(monitoring_values=(tampered, tampered))
    invalid = service.execute(_command())
    assert invalid.blocker_codes == (R4ResearchControlBlockerCode.OWNER_PROVIDER_UNAVAILABLE,)


def test_command_clock_and_uow_are_live_validated() -> None:
    service, active, monitoring, owner, uow = _service()
    malformed = object.__new__(EvaluateR4ResearchControlPreflightCommand)
    object.__setattr__(malformed, "scope_id", "")
    object.__setattr__(malformed, "as_of", _command().as_of)
    with pytest.raises(R4ResearchControlUnavailable, match="command"):
        service.execute(malformed)
    assert (active.calls, monitoring.calls, owner.calls) == (0, 0, 0)

    with pytest.raises(R4ResearchControlUnavailable, match="future"):
        service.execute(
            EvaluateR4ResearchControlPreflightCommand(
                scope_id=monitoring_decision().scope.scope_id,
                as_of=uow.server_time + timedelta(microseconds=1),
            )
        )

    owner.unit_of_work_key = "django:other"
    with pytest.raises(R4ResearchControlUnavailable, match="unit of work"):
        EvaluateR4ResearchControlPreflight(
            active_promotion_provider=active,
            monitoring_provider=monitoring,
            owner_graph_provider=owner,
            unit_of_work=uow,
        )


def test_runtime_uow_drift_throwing_clock_and_exact_provider_types_fail_closed() -> None:
    monitoring = _monitoring()
    identity = R4PromotionDecisionIdentity.from_decision(monitoring.active_decision)

    class _DriftingActive(_ActiveProvider):
        def get_active(self, **kwargs: object) -> R4PromotionDecisionIdentity | None:
            value = super().get_active(**kwargs)
            self.unit_of_work_key = "django:other"
            return value

    drifting_active = _DriftingActive((identity, identity))
    monitoring_provider = _MonitoringProvider((monitoring, monitoring))
    graph = _owner_graph(monitoring)
    owner = _OwnerGraphProvider((graph, graph))
    uow = _UnitOfWork(monitoring.assessment.evaluated_at + timedelta(minutes=1))
    service = EvaluateR4ResearchControlPreflight(
        active_promotion_provider=drifting_active,
        monitoring_provider=monitoring_provider,
        owner_graph_provider=owner,
        unit_of_work=uow,
    )
    drifted = service.execute(_command())
    assert drifted.blocker_codes == (R4ResearchControlBlockerCode.UNIT_OF_WORK_CHANGED,)
    assert monitoring_provider.calls == 0

    service, _, _, _, uow = _service()

    def _throwing_clock() -> datetime:
        raise RuntimeError("clock unavailable")

    uow.server_now = _throwing_clock
    clock_blocked = service.execute(_command())
    assert clock_blocked.blocker_codes == (R4ResearchControlBlockerCode.OWNER_PROVIDER_UNAVAILABLE,)

    class _IdentitySubclass(R4PromotionDecisionIdentity):
        pass

    subclass = _IdentitySubclass(
        **{item.name: getattr(identity, item.name) for item in fields(identity)}
    )
    service, _, _, _, _ = _service(active_values=(subclass, subclass))
    wrong_type = service.execute(_command())
    assert wrong_type.blocker_codes == (R4ResearchControlBlockerCode.OWNER_PROVIDER_UNAVAILABLE,)


def test_command_and_public_runtime_expose_no_authority_or_owner_injection() -> None:
    assert tuple(EvaluateR4ResearchControlPreflightCommand.__dataclass_fields__) == (
        "scope_id",
        "as_of",
    )
    assert tuple(signature(build_django_r4_research_control_runtime).parameters) == ("using",)
    runtime = build_django_r4_research_control_runtime()
    assert tuple(runtime.__dataclass_fields__) == ("preflight",)
    assert not hasattr(runtime, "register")
    assert not hasattr(runtime, "publish_current")
    assert not hasattr(runtime, "decide")
    assert not hasattr(runtime, "execute")
