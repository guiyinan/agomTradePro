"""R7 monitoring persistence re-evidences owners before every append."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest

from apps.research.application.r7_post_promotion_monitoring import (
    R7MonitoringEvaluationEvidence,
)
from apps.research.application.r7_post_promotion_monitoring_persistence import (
    R7MonitoringPersistenceUnavailable,
    RegisterR7MonitoringAssessment,
    derive_r7_monitoring_assessment_id,
)
from tests.unit.research.test_r7_post_promotion_monitoring_application import (
    _command,
    _graph,
    _use_case,
)


class _Evaluator:
    unit_of_work_key = "research:default"

    def __init__(self, evidence: R7MonitoringEvaluationEvidence) -> None:
        self.evidence = evidence
        self.calls = 0

    def execute_evidence(self, _: object) -> R7MonitoringEvaluationEvidence:
        self.calls += 1
        return self.evidence


class _Writer:
    unit_of_work_key = "research:default"

    def __init__(self) -> None:
        self.calls = 0
        self.evidence: R7MonitoringEvaluationEvidence | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def append_evidence(
        self,
        *,
        command: object,
        evidence: R7MonitoringEvaluationEvidence,
    ) -> R7MonitoringEvaluationEvidence:
        self.calls += 1
        self.evidence = evidence
        return evidence


def _evidence() -> tuple[object, R7MonitoringEvaluationEvidence]:
    policy, owner_graph, calendar, realization, as_of = _graph()
    use_case, _, _, _ = _use_case(
        policy=policy,
        owner_graph=owner_graph,
        calendar=calendar,
        realization=realization,
        now=as_of + timedelta(seconds=1),
    )
    command = _command(policy, as_of)
    return command, use_case.execute_evidence(command)


def test_registration_rereads_complete_evidence_before_append() -> None:
    command, evidence = _evidence()
    evaluator = _Evaluator(evidence)
    writer = _Writer()

    result = RegisterR7MonitoringAssessment(
        evaluator=evaluator,
        writer=writer,
    ).execute(command)

    assert result == evidence
    assert evaluator.calls == 2
    assert writer.calls == 1
    assert writer.evidence == evidence
    assert derive_r7_monitoring_assessment_id(command).startswith(
        "r7-monitoring-assessment-ledger:"
    )


def test_registration_blocks_owner_change_before_append() -> None:
    command, evidence = _evidence()

    class _ChangingEvaluator(_Evaluator):
        def execute_evidence(self, _: object) -> R7MonitoringEvaluationEvidence:
            self.calls += 1
            if self.calls == 1:
                return self.evidence
            object.__setattr__(self.evidence.assessment, "result_id", "substituted")
            return self.evidence

    evaluator = _ChangingEvaluator(evidence)
    writer = _Writer()

    with pytest.raises(R7MonitoringPersistenceUnavailable):
        RegisterR7MonitoringAssessment(evaluator=evaluator, writer=writer).execute(command)

    assert writer.calls == 0


def test_registration_blocks_uow_drift_before_append() -> None:
    command, evidence = _evidence()
    evaluator = _Evaluator(evidence)
    writer = _Writer()
    register = RegisterR7MonitoringAssessment(evaluator=evaluator, writer=writer)
    writer.unit_of_work_key = "research:other"

    with pytest.raises(R7MonitoringPersistenceUnavailable):
        register.execute(command)

    assert evaluator.calls == 0
    assert writer.calls == 0


def test_registration_normalizes_evaluator_failure_and_writes_nothing() -> None:
    command, evidence = _evidence()

    class _FailingEvaluator(_Evaluator):
        def execute_evidence(self, _: object) -> R7MonitoringEvaluationEvidence:
            raise RuntimeError("owner unavailable")

    writer = _Writer()
    with pytest.raises(R7MonitoringPersistenceUnavailable):
        RegisterR7MonitoringAssessment(
            evaluator=_FailingEvaluator(evidence),
            writer=writer,
        ).execute(command)

    assert writer.calls == 0
