"""Component coverage for append-only R8 monitoring persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import Collector

from apps.portfolio.application.governed_optimization import (
    GovernedOptimizationRunBundle,
)
from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
    GovernedOptimizationMonitoringEvaluationEvidence,
)
from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringAssessmentRef,
    GovernedOptimizationMonitoringPersistenceUnavailable,
    RegisterGovernedOptimizationMonitoringAssessment,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringPolicy,
    evaluate_governed_optimization_monitoring,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_models import (
    GovernedOptimizationMonitoringAssessmentModel,
    GovernedOptimizationMonitoringAuditSnapshotModel,
    GovernedOptimizationMonitoringObservationModel,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_repository import (
    DjangoGovernedOptimizationMonitoringRepository,
    _build_governed_optimization_monitoring_writer,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
    _DjangoGovernedOptimizationLifecycleStore,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import (
    AS_OF,
    _active_result,
    _calendar,
    _facts,
    _policy,
    _receipt_and_result,
)


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _EvidenceEvaluator:
    def __init__(
        self,
        *,
        unit_of_work_key: str,
        evidence: GovernedOptimizationMonitoringEvaluationEvidence,
    ) -> None:
        self.unit_of_work_key = unit_of_work_key
        self._evidence = evidence

    def execute_evidence(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> GovernedOptimizationMonitoringEvaluationEvidence:
        assert command.as_of == self._evidence.assessment.evaluated_at
        return self._evidence


def _assert_manager_mutations_are_blocked(manager: Any, row: Any) -> None:
    with pytest.raises(ValidationError):
        manager.bulk_create([])
    with pytest.raises(ValidationError):
        manager.bulk_update([row], ["status"])
    with pytest.raises(ValidationError):
        manager.get_or_create(assessment_id=row.assessment_id)
    with pytest.raises(ValidationError):
        manager.update_or_create(assessment_id=row.assessment_id)


@pytest.mark.django_db(transaction=True)
def test_monitoring_round_trip_is_exact_pit_and_append_only() -> None:
    receipt, result = _receipt_and_result()
    active = _active_result(result)
    calendar = _calendar()
    policy = _policy(calendar, active, receipt)
    portfolio, broker, observations = _facts(
        calendar=calendar,
        receipt=receipt,
        result=result,
    )
    assessment = evaluate_governed_optimization_monitoring(
        requested_policy_id=policy.policy_id,
        requested_policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        active_result=active,
        receipt=receipt,
        current_upstream_promotions=receipt.input_set.promotions,
        policy=policy,
        calendar=calendar,
        portfolio_evidence=portfolio,
        broker_evidence=broker,
        observations=observations,
        evaluated_at=AS_OF,
    )
    evidence = GovernedOptimizationMonitoringEvaluationEvidence(
        active_result=active,
        receipt=receipt,
        upstream_promotions=receipt.input_set.promotions,
        policy=policy,
        calendar=calendar,
        portfolio_evidence=portfolio,
        broker_evidence=broker,
        observations=observations,
        assessment=assessment,
    )
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    clock = _Clock(AS_OF + timedelta(hours=1))
    receipts = DjangoGovernedOptimizationInputReceiptRepository(
        unit_of_work=unit_of_work,
        clock=clock,
    )
    with unit_of_work.atomic():
        receipts._store_verified(receipt.input_set, receipt.recorded_at)
    result_repository = DjangoGovernedOptimizationResearchRepository(
        unit_of_work=unit_of_work,
        receipt_provider=receipts,
        clock=clock,
    )
    result_repository.append_bundle(
        GovernedOptimizationRunBundle(
            result=result,
            lifecycle_root=active.lifecycle_events[0],
        )
    )
    lifecycle_store = _DjangoGovernedOptimizationLifecycleStore(result_repository)
    with lifecycle_store.atomic():
        lifecycle_store.append_lifecycle_event(active.lifecycle_events[1])
    writer = _build_governed_optimization_monitoring_writer(
        unit_of_work=unit_of_work,
        clock=clock,
    )
    register = RegisterGovernedOptimizationMonitoringAssessment(
        evaluator=_EvidenceEvaluator(
            unit_of_work_key=unit_of_work.unit_of_work_key,
            evidence=evidence,
        ),
        writer=writer,
    )
    command = EvaluateGovernedOptimizationMonitoringCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=AS_OF,
    )

    persisted = register.execute(command)
    original_ledger_time = persisted.ledger_recorded_at
    clock.value += timedelta(hours=1)
    assert register.execute(command) == persisted
    assert persisted.ledger_recorded_at == original_ledger_time

    second_policy = GovernedOptimizationMonitoringPolicy.create(
        policy_id=policy.policy_scope_id,
        owner=policy.owner,
        target=policy.target,
        thresholds=policy.thresholds,
        required_consecutive_breaches=3,
        minimum_complete_periods=policy.minimum_complete_periods,
        max_period_lag_seconds=policy.max_period_lag_seconds,
        max_evidence_delay_seconds=policy.max_evidence_delay_seconds,
        calendar=calendar,
        recorded_at=policy.recorded_at + timedelta(minutes=1),
        valid_until=policy.valid_until,
    )
    second_assessment = evaluate_governed_optimization_monitoring(
        requested_policy_id=second_policy.policy_id,
        requested_policy_version=second_policy.policy_version,
        expected_policy_hash=second_policy.content_hash,
        active_result=active,
        receipt=receipt,
        current_upstream_promotions=receipt.input_set.promotions,
        policy=second_policy,
        calendar=calendar,
        portfolio_evidence=portfolio,
        broker_evidence=broker,
        observations=observations,
        evaluated_at=AS_OF,
    )
    second_evidence = GovernedOptimizationMonitoringEvaluationEvidence(
        active_result=active,
        receipt=receipt,
        upstream_promotions=receipt.input_set.promotions,
        policy=second_policy,
        calendar=calendar,
        portfolio_evidence=portfolio,
        broker_evidence=broker,
        observations=observations,
        assessment=second_assessment,
    )
    second_register = RegisterGovernedOptimizationMonitoringAssessment(
        evaluator=_EvidenceEvaluator(
            unit_of_work_key=unit_of_work.unit_of_work_key,
            evidence=second_evidence,
        ),
        writer=writer,
    )
    second_command = EvaluateGovernedOptimizationMonitoringCommand(
        policy_id=second_policy.policy_id,
        policy_version=second_policy.policy_version,
        expected_policy_hash=second_policy.content_hash,
        as_of=AS_OF,
    )

    forked_register = RegisterGovernedOptimizationMonitoringAssessment(
        evaluator=_EvidenceEvaluator(
            unit_of_work_key=unit_of_work.unit_of_work_key,
            evidence=GovernedOptimizationMonitoringEvaluationEvidence(
                active_result=active,
                receipt=receipt,
                upstream_promotions=receipt.input_set.promotions,
                policy=second_policy,
                calendar=calendar,
                portfolio_evidence=portfolio,
                broker_evidence=broker,
                observations=observations,
                assessment=assessment,
            ),
        ),
        writer=writer,
    )
    with pytest.raises(GovernedOptimizationMonitoringPersistenceUnavailable):
        forked_register.execute(command)
    assert GovernedOptimizationMonitoringAssessmentModel._default_manager.count() == 1

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            second_register.execute(second_command)
            assert GovernedOptimizationMonitoringAssessmentModel._default_manager.count() == 2
            assert GovernedOptimizationMonitoringObservationModel._default_manager.count() == 6
            raise RuntimeError("outer rollback")
    assert GovernedOptimizationMonitoringAssessmentModel._default_manager.count() == 1
    assert GovernedOptimizationMonitoringObservationModel._default_manager.count() == 3

    second_register.execute(second_command)

    assert GovernedOptimizationMonitoringAssessmentModel._default_manager.count() == 2
    assert GovernedOptimizationMonitoringObservationModel._default_manager.count() == 6
    assert (
        GovernedOptimizationMonitoringObservationModel._default_manager.values(
            "domain_observation_hash"
        )
        .distinct()
        .count()
        == 3
    )
    assert GovernedOptimizationMonitoringAuditSnapshotModel._default_manager.count() == 0

    public = DjangoGovernedOptimizationMonitoringRepository(clock=clock)
    assert (
        public.get_exact(
            assessment_ref=GovernedOptimizationMonitoringAssessmentRef(
                assessment.assessment_id,
                assessment.content_hash,
            ),
            as_of=clock.value,
        )
        == persisted
    )
    assert (
        public.get_exact(
            assessment_ref=persisted.assessment_ref,
            as_of=AS_OF,
        )
        is None
    )

    assessment_row = GovernedOptimizationMonitoringAssessmentModel._default_manager.get(
        assessment_id=persisted.assessment_ref.assessment_id
    )
    with pytest.raises(ValidationError):
        GovernedOptimizationMonitoringAssessmentModel._default_manager.update(status="blocked")
    with pytest.raises(ValidationError):
        GovernedOptimizationMonitoringAssessmentModel._base_manager.all().delete()
    with pytest.raises(ValidationError):
        assessment_row.delete()
    with pytest.raises(ValidationError):
        assessment_row.save()
    with pytest.raises(ValidationError):
        assessment_row.save_base(force_update=True)

    related_manager = assessment_row.result.monitoring_assessment_ledgers
    for manager in (
        GovernedOptimizationMonitoringAssessmentModel._default_manager,
        GovernedOptimizationMonitoringAssessmentModel._base_manager,
        related_manager,
    ):
        _assert_manager_mutations_are_blocked(manager, assessment_row)

    queryset = GovernedOptimizationMonitoringAssessmentModel._default_manager.all()
    with pytest.raises(ValidationError):
        queryset.update(status="blocked")
    with pytest.raises(ValidationError):
        queryset.delete()
    with pytest.raises(ValidationError):
        queryset._update([])
    with pytest.raises(ValidationError):
        queryset._raw_delete(using="default")
    with pytest.raises(ValidationError):
        queryset._insert([], [])
    with pytest.raises(ValidationError):
        queryset._batched_insert([], [], None)

    collector = Collector(using="default")
    collector.collect([assessment_row])
    with pytest.raises(ValidationError):
        collector.delete()
