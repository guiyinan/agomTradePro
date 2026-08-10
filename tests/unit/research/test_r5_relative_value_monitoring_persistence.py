"""Focused Phase B contracts for R5 monitoring persistence."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta

import pytest

from apps.research.application.r5_relative_value_monitoring import (
    R5MonitoringEvaluationEvidence,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    AuditR5MonitoringAssessmentsCommand,
    R5MonitoringAssessmentRef,
    R5MonitoringPersistedAssessment,
    R5MonitoringPersistenceUnavailable,
    RegisterR5MonitoringAssessment,
)
from apps.research.infrastructure.r5_relative_value_monitoring_codec import (
    R5MonitoringCodecError,
    decode_r5_monitoring_active_lifecycle,
    decode_r5_monitoring_assessment,
    decode_r5_monitoring_fact,
    decode_r5_monitoring_fixed_income,
    decode_r5_monitoring_period_calendar,
    decode_r5_monitoring_policy,
    encode_r5_monitoring_active_lifecycle,
    encode_r5_monitoring_assessment,
    encode_r5_monitoring_fact,
    encode_r5_monitoring_fixed_income,
    encode_r5_monitoring_period_calendar,
    encode_r5_monitoring_policy,
)
from tests.unit.research.test_r5_relative_value_monitoring_application import (
    _application,
)


class _Evaluator:
    def __init__(self, evidence: R5MonitoringEvaluationEvidence, key: object) -> None:
        self.evidence = evidence
        self.key = key
        self.calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self.key

    def execute_evidence(self, command: object) -> R5MonitoringEvaluationEvidence:
        del command
        self.calls += 1
        return self.evidence


class _Writer:
    def __init__(self, evidence: R5MonitoringEvaluationEvidence, key: object) -> None:
        self.evidence = evidence
        self.key = key
        self.atomic_calls = 0
        self.append_calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self.key

    def atomic(self):  # type: ignore[no-untyped-def]
        self.atomic_calls += 1
        return nullcontext()

    def append_evidence(self, *, command: object, evidence: object) -> object:
        del command
        assert evidence == self.evidence
        self.append_calls += 1
        assessment = self.evidence.assessment
        assert self.evidence.active_lifecycle is not None
        assert self.evidence.fixed_income is not None
        assert self.evidence.policy is not None
        assert self.evidence.calendar is not None
        return R5MonitoringPersistedAssessment(
            assessment_ref=R5MonitoringAssessmentRef(
                assessment.assessment_id,
                assessment.content_hash,
            ),
            active_lifecycle=self.evidence.active_lifecycle,
            fixed_income=self.evidence.fixed_income,
            policy=self.evidence.policy,
            calendar=self.evidence.calendar,
            portfolio_facts=self.evidence.portfolio_facts,
            assessment=assessment,
            ledger_recorded_at=assessment.evaluated_at + timedelta(seconds=1),
        )


def test_phase_a_exposes_complete_replayable_evidence() -> None:
    use_case, command, _, _ = _application()

    evidence = use_case.execute_evidence(command)

    assert type(evidence) is R5MonitoringEvaluationEvidence
    assert evidence.policy is not None
    assert evidence.active_lifecycle is not None
    assert evidence.fixed_income is not None
    assert evidence.calendar is not None
    assert evidence.portfolio_facts
    assert (
        evidence.assessment.validated_copy(
            policy=evidence.policy,
            calendar=evidence.calendar,
            facts=evidence.portfolio_facts,
        )
        == evidence.assessment
    )


def test_strict_codec_roundtrips_full_owner_graph_and_rejects_extra_key() -> None:
    use_case, command, _, _ = _application()
    evidence = use_case.execute_evidence(command)
    assert evidence.active_lifecycle is not None
    assert evidence.fixed_income is not None
    assert evidence.policy is not None
    assert evidence.calendar is not None

    assert (
        decode_r5_monitoring_active_lifecycle(
            encode_r5_monitoring_active_lifecycle(evidence.active_lifecycle)
        )
        == evidence.active_lifecycle
    )
    assert (
        decode_r5_monitoring_fixed_income(encode_r5_monitoring_fixed_income(evidence.fixed_income))
        == evidence.fixed_income
    )
    assert (
        decode_r5_monitoring_policy(encode_r5_monitoring_policy(evidence.policy)) == evidence.policy
    )
    assert (
        decode_r5_monitoring_period_calendar(
            encode_r5_monitoring_period_calendar(evidence.calendar)
        )
        == evidence.calendar
    )
    assert (
        tuple(
            decode_r5_monitoring_fact(encode_r5_monitoring_fact(item))
            for item in evidence.portfolio_facts
        )
        == evidence.portfolio_facts
    )
    assert (
        decode_r5_monitoring_assessment(encode_r5_monitoring_assessment(evidence.assessment))
        == evidence.assessment
    )

    payload = deepcopy(encode_r5_monitoring_fact(evidence.portfolio_facts[0]))
    payload["extra"] = "not-canonical"
    with pytest.raises(R5MonitoringCodecError):
        decode_r5_monitoring_fact(payload)


def test_register_keeps_exact_shared_uow_and_appends_complete_graph() -> None:
    use_case, command, _, _ = _application()
    evidence = use_case.execute_evidence(command)
    evaluator = _Evaluator(evidence, "django:r5-monitoring")
    writer = _Writer(evidence, "django:r5-monitoring")
    register = RegisterR5MonitoringAssessment(evaluator=evaluator, writer=writer)

    persisted = register.execute(command)

    assert persisted.assessment == evidence.assessment
    assert evaluator.calls == 1
    assert writer.atomic_calls == 1
    assert writer.append_calls == 1


@pytest.mark.parametrize("key", ["", object()])
def test_register_rejects_missing_or_non_string_uow_key(key: object) -> None:
    use_case, command, _, _ = _application()
    evidence = use_case.execute_evidence(command)

    with pytest.raises(R5MonitoringPersistenceUnavailable):
        RegisterR5MonitoringAssessment(
            evaluator=_Evaluator(evidence, key),
            writer=_Writer(evidence, key),
        )


def test_audit_limit_rejects_bool_and_int_subclass() -> None:
    class WideInt(int):
        pass

    use_case, command, _, _ = _application()
    use_case.execute_evidence(command)
    with pytest.raises(ValueError):
        AuditR5MonitoringAssessmentsCommand(as_of=command.as_of, limit=True)
    with pytest.raises(ValueError):
        AuditR5MonitoringAssessmentsCommand(as_of=command.as_of, limit=WideInt(2))
