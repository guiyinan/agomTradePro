"""Application contracts for persisted R8 optimization monitoring."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from inspect import signature
from typing import NoReturn

import pytest
from django.test import override_settings

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
)
from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringAssessmentRef,
    GovernedOptimizationMonitoringAuditEntry,
    GovernedOptimizationMonitoringPersistenceUnavailable,
    RegisterGovernedOptimizationMonitoringAssessment,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    MonitoringAssessmentStatus,
)
from apps.portfolio.governed_optimization_monitoring_composition import (
    build_django_governed_optimization_monitoring_runtime,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_audit_codec import (
    create_monitoring_audit_snapshot,
    decode_monitoring_audit_cursor,
    encode_monitoring_audit_cursor,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_codec import (
    GovernedOptimizationMonitoringCodecError,
    decode_monitoring_assessment,
    encode_monitoring_assessment,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import _evaluate


class _NeverEvaluator:
    unit_of_work_key = "monitoring-uow"

    def execute_evidence(self, command: object) -> NoReturn:
        raise AssertionError("malformed registration must not evaluate owners")


class _NeverWriter:
    unit_of_work_key = "monitoring-uow"

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def append_evidence(self, **kwargs: object) -> NoReturn:
        raise AssertionError("malformed registration must not append")


def test_registration_rejects_mutated_id_only_command_before_uow_or_write() -> None:
    command = EvaluateGovernedOptimizationMonitoringCommand(
        policy_id="policy",
        policy_version="governed-optimization-monitoring-policy.v1",
        expected_policy_hash="a" * 64,
        as_of=datetime(2026, 8, 10, tzinfo=UTC),
    )
    object.__setattr__(command, "expected_policy_hash", "not-a-hash")

    use_case = RegisterGovernedOptimizationMonitoringAssessment(
        evaluator=_NeverEvaluator(),
        writer=_NeverWriter(),
    )

    with pytest.raises(
        GovernedOptimizationMonitoringPersistenceUnavailable,
        match="command is malformed",
    ):
        use_case.execute(command)


def test_registration_rejects_different_owner_and_writer_uow() -> None:
    writer = _NeverWriter()
    writer.unit_of_work_key = "other-uow"

    with pytest.raises(
        GovernedOptimizationMonitoringPersistenceUnavailable,
        match="different units of work",
    ):
        RegisterGovernedOptimizationMonitoringAssessment(
            evaluator=_NeverEvaluator(),
            writer=writer,
        )


def test_uow_keys_require_exact_non_whitespace_builtin_strings() -> None:
    evaluator = _NeverEvaluator()
    writer = _NeverWriter()
    evaluator.unit_of_work_key = "   "
    writer.unit_of_work_key = "   "

    with pytest.raises(
        GovernedOptimizationMonitoringPersistenceUnavailable,
        match="unit of work is unavailable",
    ):
        RegisterGovernedOptimizationMonitoringAssessment(
            evaluator=evaluator,
            writer=writer,
        )


def test_strict_assessment_codec_rejects_nested_content_tamper() -> None:
    assessment = _evaluate()
    payload = deepcopy(encode_monitoring_assessment(assessment))
    value = payload["value"]
    assert isinstance(value, dict)
    fields = value["$fields"]
    assert isinstance(fields, dict)
    fields["content_hash"] = "0" * 64

    with pytest.raises(GovernedOptimizationMonitoringCodecError):
        decode_monitoring_assessment(payload)


def test_audit_cursor_binds_cutoff_and_django_secret_key() -> None:
    assessment = _evaluate()
    as_of = assessment.evaluated_at

    def entry(suffix: str) -> GovernedOptimizationMonitoringAuditEntry:
        return GovernedOptimizationMonitoringAuditEntry(
            assessment_ref=GovernedOptimizationMonitoringAssessmentRef(
                f"assessment:{suffix}",
                suffix * 64,
            ),
            result_id=assessment.result_id,
            result_hash=assessment.result_hash,
            policy_id=assessment.policy_id,
            policy_version="governed-optimization-monitoring-policy.v1",
            evaluated_at=as_of,
            ledger_recorded_at=as_of,
            status=MonitoringAssessmentStatus.HEALTHY,
            observation_count=len(assessment.observation_hashes),
            blocker_codes=(),
            retirement_review_required=False,
        )

    snapshot = create_monitoring_audit_snapshot(
        as_of=as_of,
        created_at=as_of,
        entries=(entry("a"), entry("b")),
    )
    cursor = encode_monitoring_audit_cursor(snapshot=snapshot, next_offset=1)
    decoded = decode_monitoring_audit_cursor(cursor)
    assert decoded is not None
    assert decoded.snapshot_as_of == as_of

    with override_settings(SECRET_KEY="different-monitoring-test-key"):
        with pytest.raises(
            GovernedOptimizationMonitoringPersistenceUnavailable,
            match="signature",
        ):
            decode_monitoring_audit_cursor(cursor)


def test_public_runtime_builder_has_no_caller_clock_parameter() -> None:
    assert (
        "clock" not in signature(build_django_governed_optimization_monitoring_runtime).parameters
    )
