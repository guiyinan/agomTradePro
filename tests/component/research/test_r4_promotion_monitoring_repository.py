"""Component coverage for R4 monitoring append-only persistence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import Collector
from django.test import override_settings

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringPersistenceConflict,
    R4MonitoringPersistenceCorruption,
    R4MonitoringPersistenceUnavailable,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import evaluate_r4_promotion_monitoring
from apps.research.infrastructure.r4_promotion_model_values import (
    _decision_bundle_model_values,
    _decision_receipt_model_values,
    _policy_model_values,
)
from apps.research.infrastructure.r4_promotion_models import (
    R4PromotionDecisionBundleModel,
    R4PromotionDecisionReceiptModel,
    R4PromotionPolicyModel,
    _activate_r4_promotion_unit_of_work,
    _claim_r4_promotion_insert,
)
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAssessmentLedgerModel,
    R4MonitoringAuditSnapshotModel,
    R4MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    DjangoR4MonitoringRepository,
    _DjangoR4MonitoringStore,
)
from tests.unit.research.r4_promotion_factories import promotion_decision_bundle
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _persist_active_decision(decision: R4PromotionDecision) -> R4PromotionDecisionBundleModel:
    bundle = promotion_decision_bundle(decision)
    token = object()
    with transaction.atomic(), _activate_r4_promotion_unit_of_work(token):
        policy_values = _policy_model_values(decision.policy)
        with _claim_r4_promotion_insert(
            token=token,
            model_type=R4PromotionPolicyModel,
            expected_values=policy_values,
        ):
            policy_model = R4PromotionPolicyModel._default_manager.create(**policy_values)
        receipt_values = {
            **_decision_receipt_model_values(bundle.receipt),
            "policy_id": policy_model.pk,
        }
        with _claim_r4_promotion_insert(
            token=token,
            model_type=R4PromotionDecisionReceiptModel,
            expected_values=receipt_values,
        ):
            receipt_model = R4PromotionDecisionReceiptModel._default_manager.create(
                **receipt_values
            )
        bundle_values = {
            **_decision_bundle_model_values(bundle),
            "receipt_id": receipt_model.pk,
            "policy_id": policy_model.pk,
        }
        with _claim_r4_promotion_insert(
            token=token,
            model_type=R4PromotionDecisionBundleModel,
            expected_values=bundle_values,
        ):
            return R4PromotionDecisionBundleModel._default_manager.create(**bundle_values)


def _command_and_evidence(
    *,
    period_count: int = 2,
    decision: R4PromotionDecision | None = None,
) -> tuple[EvaluateR4PromotionMonitoringCommand, R4MonitoringEvaluationEvidence]:
    selected = decision or monitoring_decision()
    calendar = monitoring_calendar(selected)
    policy = monitoring_policy(selected, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=selected,
            calendar=calendar,
            policy=policy,
        )
        for index in range(period_count)
    )
    as_of = calendar.valid_from + timedelta(hours=period_count, minutes=30)
    command = EvaluateR4PromotionMonitoringCommand(
        active_decision=R4PromotionDecisionIdentity.from_decision(selected),
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=as_of,
    )
    assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=command.active_decision,
        requested_policy_id=command.policy_id,
        requested_policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        active_decision=selected,
        portfolio_result=selected.trial.portfolio_record,
        current_r3_attestation=selected.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        evaluated_at=command.as_of,
    )
    return command, R4MonitoringEvaluationEvidence(
        active_decision=selected,
        portfolio_result=selected.trial.portfolio_record,
        current_r3_attestation=selected.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        assessment=assessment,
    )


def _append(
    store: _DjangoR4MonitoringStore,
    command: EvaluateR4PromotionMonitoringCommand,
    evidence: R4MonitoringEvaluationEvidence,
):
    with store.atomic():
        return store.append_evidence(command=command, evidence=evidence)


def test_append_idempotency_exact_pit_and_server_ledger_clock() -> None:
    command, evidence = _command_and_evidence()
    _persist_active_decision(evidence.active_decision)
    clock = FixedClock(command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)

    first = _append(store, command, evidence)
    second = _append(store, command, evidence)

    assert second == first
    assert first.ledger_recorded_at == clock.value
    assert R4MonitoringObservationLedgerModel._default_manager.count() == 2
    assert R4MonitoringAssessmentLedgerModel._default_manager.count() == 1
    repository = DjangoR4MonitoringRepository(clock=clock)
    assert (
        repository.get_exact(
            assessment_ref=first.assessment_ref,
            as_of=clock.value - timedelta(microseconds=1),
        )
        is None
    )
    assert repository.get_exact(assessment_ref=first.assessment_ref, as_of=clock.value) == first
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="future"):
        repository.get_exact(
            assessment_ref=first.assessment_ref,
            as_of=clock.value + timedelta(microseconds=1),
        )


def test_raw_payload_header_fk_and_future_row_tamper_fail_closed() -> None:
    command, evidence = _command_and_evidence()
    _persist_active_decision(evidence.active_decision)
    clock = FixedClock(command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)
    persisted = _append(store, command, evidence)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_monitoring_assessment SET status = %s WHERE assessment_id = %s",
            ["breached", persisted.assessment_ref.assessment_id],
        )
    repository = DjangoR4MonitoringRepository(clock=clock)
    with pytest.raises(R4MonitoringPersistenceCorruption, match="header differs"):
        repository.get_exact(assessment_ref=persisted.assessment_ref, as_of=clock.value)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_monitoring_assessment SET ledger_recorded_at = %s "
            "WHERE assessment_id = %s",
            [clock.value + timedelta(hours=1), persisted.assessment_ref.assessment_id],
        )
    assert repository.get_exact(assessment_ref=persisted.assessment_ref, as_of=clock.value) is None


def test_period_fork_and_outer_transaction_rollback_leave_no_partial_rows() -> None:
    command, evidence = _command_and_evidence()
    _persist_active_decision(evidence.active_decision)
    clock = FixedClock(command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)
    with pytest.raises(RuntimeError, match="rollback"):
        with store.atomic():
            store.append_evidence(command=command, evidence=evidence)
            raise RuntimeError("rollback outer transaction")
    assert R4MonitoringObservationLedgerModel._default_manager.count() == 0
    assert R4MonitoringAssessmentLedgerModel._default_manager.count() == 0

    _append(store, command, evidence)
    first = evidence.observations[0]
    forked = replace(first, observation_id="r4-monitoring-period-fork")
    forked_observations = (forked, *evidence.observations[1:])
    forked_assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=command.active_decision,
        requested_policy_id=command.policy_id,
        requested_policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        active_decision=evidence.active_decision,
        portfolio_result=evidence.portfolio_result,
        current_r3_attestation=evidence.current_r3_attestation,
        policy=evidence.policy,
        period_calendar=evidence.period_calendar,
        observations=forked_observations,
        evaluated_at=command.as_of,
    )
    forked_evidence = replace(
        evidence,
        observations=forked_observations,
        assessment=forked_assessment,
    )
    with pytest.raises(R4MonitoringPersistenceConflict, match="period"):
        _append(store, command, forked_evidence)


def test_immutable_signed_audit_snapshot_binds_cutoff_and_secret() -> None:
    decision = monitoring_decision()
    _persist_active_decision(decision)
    first_command, first_evidence = _command_and_evidence(
        period_count=2,
        decision=decision,
    )
    second_command, second_evidence = _command_and_evidence(
        period_count=3,
        decision=decision,
    )
    clock = FixedClock(second_command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)
    _append(store, first_command, first_evidence)
    clock.value += timedelta(minutes=1)
    _append(store, second_command, second_evidence)
    audit_as_of = clock.value

    with patch("django.core.signing.time.time", return_value=1_000.0):
        first_page = store.list_audit(as_of=audit_as_of, cursor=None, limit=1)
    assert len(first_page.entries) == 1
    assert first_page.next_cursor is not None
    assert R4MonitoringAuditSnapshotModel._default_manager.count() == 1
    with patch("django.core.signing.time.time", return_value=1_005.0):
        second_page = store.list_audit(
            as_of=audit_as_of,
            cursor=first_page.next_cursor,
            limit=1,
        )
    assert len(second_page.entries) == 1
    assert second_page.next_cursor is None

    tampered = f"{first_page.next_cursor[:-1]}x"
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="signature|noncanonical"):
        store.list_audit(as_of=audit_as_of, cursor=tampered, limit=1)
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="another cutoff"):
        store.list_audit(
            as_of=audit_as_of - timedelta(microseconds=1),
            cursor=first_page.next_cursor,
            limit=1,
        )
    with override_settings(SECRET_KEY="another-r4-monitoring-test-secret"):
        with pytest.raises(R4MonitoringPersistenceUnavailable, match="signature"):
            store.list_audit(
                as_of=audit_as_of,
                cursor=first_page.next_cursor,
                limit=1,
            )


def test_normal_django_mutation_and_collector_paths_are_guarded() -> None:
    command, evidence = _command_and_evidence()
    decision_model = _persist_active_decision(evidence.active_decision)
    clock = FixedClock(command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)
    _append(store, command, evidence)
    observation = R4MonitoringObservationLedgerModel._default_manager.order_by("pk").first()
    assert observation is not None
    assessment = R4MonitoringAssessmentLedgerModel._default_manager.get()

    forbidden = (
        lambda: R4MonitoringObservationLedgerModel._default_manager.create(),
        lambda: R4MonitoringObservationLedgerModel._base_manager.create(),
        lambda: decision_model.monitoring_observation_ledgers.create(),
        lambda: observation.save(),
        lambda: observation.save_base(),
        lambda: observation.delete(),
        lambda: R4MonitoringObservationLedgerModel._default_manager.all().update(
            source_owner="caller"
        ),
        lambda: R4MonitoringObservationLedgerModel._default_manager.all().delete(),
        lambda: R4MonitoringObservationLedgerModel._default_manager.bulk_create([]),
        lambda: R4MonitoringObservationLedgerModel._default_manager.bulk_update(
            [observation], ["source_owner"]
        ),
        lambda: R4MonitoringObservationLedgerModel._default_manager.get_or_create(
            observation_id="caller"
        ),
        lambda: R4MonitoringObservationLedgerModel._default_manager.update_or_create(
            observation_id="caller"
        ),
        lambda: R4MonitoringObservationLedgerModel._default_manager.all()._update([]),
        lambda: R4MonitoringObservationLedgerModel._default_manager.all()._raw_delete("default"),
        lambda: R4MonitoringObservationLedgerModel._default_manager.all()._insert(
            [observation], []
        ),
        lambda: R4MonitoringObservationLedgerModel._default_manager.all()._batched_insert(
            [observation], [], None
        ),
        lambda: assessment.save(),
        lambda: assessment.delete(),
    )
    for operation in forbidden:
        with pytest.raises(ValidationError):
            operation()

    collector = Collector(using="default")
    collector.collect([assessment])
    with transaction.atomic(), pytest.raises(ValidationError):
        collector.delete()


def test_integrity_race_replays_only_an_exact_first_winner() -> None:
    command, evidence = _command_and_evidence()
    _persist_active_decision(evidence.active_decision)
    clock = FixedClock(command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)

    original_create = R4MonitoringAssessmentLedgerModel._default_manager.create
    inserted = False

    def race_create(**values: object):
        nonlocal inserted
        if not inserted:
            inserted = True
            original_create(**values)
            raise IntegrityError("simulated first-winner race")
        return original_create(**values)

    with patch.object(
        R4MonitoringAssessmentLedgerModel._default_manager,
        "create",
        side_effect=race_create,
    ):
        persisted = _append(store, command, evidence)
    assert persisted.assessment == evidence.assessment
    assert R4MonitoringAssessmentLedgerModel._default_manager.count() == 1
