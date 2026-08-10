"""Application contract tests for ID-only R4 monitoring registration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringPersistenceUnavailable,
    RegisterR4MonitoringAssessment,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import evaluate_r4_promotion_monitoring
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)


def _command_and_evidence() -> tuple[
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
]:
    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    command = EvaluateR4PromotionMonitoringCommand(
        active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=calendar.valid_from + timedelta(hours=2, minutes=30),
    )
    assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=command.active_decision,
        requested_policy_id=command.policy_id,
        requested_policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        evaluated_at=command.as_of,
    )
    return command, R4MonitoringEvaluationEvidence(
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        assessment=assessment,
    )


class Evaluator:
    def __init__(self, evidence: R4MonitoringEvaluationEvidence) -> None:
        self.evidence = evidence
        self.key = "django:r4-monitoring-test"
        self.calls = 0

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    def execute_evidence(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        self.calls += 1
        assert command.as_of == self.evidence.assessment.evaluated_at
        return self.evidence


class Store:
    def __init__(self) -> None:
        self.key = "django:r4-monitoring-test"
        self.active = False
        self.appended: list[R4MonitoringEvaluationEvidence] = []

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def append_evidence(
        self,
        *,
        command: EvaluateR4PromotionMonitoringCommand,
        evidence: R4MonitoringEvaluationEvidence,
    ) -> R4MonitoringEvaluationEvidence:
        assert self.active
        assert command.as_of == evidence.assessment.evaluated_at
        self.appended.append(evidence)
        return evidence


class WideUnitOfWorkKey(str):
    """String subclass that must not cross the exact owner boundary."""


def test_register_rereads_and_appends_only_inside_the_same_uow() -> None:
    command, evidence = _command_and_evidence()
    evaluator = Evaluator(evidence)
    store = Store()

    result = RegisterR4MonitoringAssessment(evaluator=evaluator, writer=store).execute(command)

    assert result == evidence
    assert evaluator.calls == 1
    assert store.appended == [evidence]
    assert store.active is False


def test_register_rejects_missing_owner_graph_and_runtime_uow_drift() -> None:
    command, evidence = _command_and_evidence()
    evaluator = Evaluator(evidence)
    evaluator.evidence = R4MonitoringEvaluationEvidence(
        active_decision=None,
        portfolio_result=None,
        current_r3_attestation=None,
        policy=None,
        period_calendar=None,
        observations=(),
        assessment=evidence.assessment,
    )
    store = Store()
    register = RegisterR4MonitoringAssessment(evaluator=evaluator, writer=store)
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="owner graph"):
        register.execute(command)
    assert store.appended == []

    evaluator.evidence = evidence
    evaluator.key = "drifted"
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="unit of work"):
        register.execute(command)
    assert store.appended == []


@pytest.mark.parametrize(
    "invalid_key",
    (WideUnitOfWorkKey("django:r4-monitoring-test"), 7),
)
def test_register_rejects_non_exact_uow_keys_even_when_both_owners_agree(
    invalid_key: object,
) -> None:
    _, evidence = _command_and_evidence()
    evaluator = Evaluator(evidence)
    store = Store()
    object.__setattr__(evaluator, "key", invalid_key)
    object.__setattr__(store, "key", invalid_key)

    with pytest.raises(R4MonitoringPersistenceUnavailable, match="unit of work"):
        RegisterR4MonitoringAssessment(evaluator=evaluator, writer=store)
