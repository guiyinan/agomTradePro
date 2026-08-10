"""Component contracts for R2 trial and monitoring append-only persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from apps.research.application.r2_market_structure_trial_monitoring import (
    EvaluateR2MarketStructureTrialCommand,
    R2ExplanatoryTrialEvaluationEvidence,
    R2MonitoringEvaluationEvidence,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    R2MonitoringAssessmentRef,
    R2TrialAssessmentRef,
    R2TrialMonitoringPersistenceUnavailable,
    RegisterR2ExplanatoryTrialAssessment,
    RegisterR2MonitoringAssessment,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_models import (
    R2ExplanatoryTrialAssessmentLedgerModel,
    R2MonitoringAssessmentLedgerModel,
    R2MonitoringAuditSnapshotModel,
    R2MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_repository import (
    DjangoR2TrialMonitoringRepository,
    _build_r2_trial_monitoring_writer,
)
from apps.research.r2_market_structure_trial_monitoring_composition import (
    build_django_r2_trial_monitoring_runtime,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import NOW
from tests.unit.research.test_r2_market_structure_trial_monitoring_persistence import (
    _command,
    _monitoring_evidence,
    _trial_evidence,
)

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass
class _Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class _Evaluator:
    evidence: R2ExplanatoryTrialEvaluationEvidence | R2MonitoringEvaluationEvidence
    unit_of_work_key: str = "django:default"

    def execute_evidence(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialEvaluationEvidence | R2MonitoringEvaluationEvidence:
        assert command.as_of == self.evidence.assessment.assessed_at
        return self.evidence


def test_trial_and_monitoring_graphs_round_trip_with_idempotent_writes() -> None:
    clock = _Clock(NOW + timedelta(minutes=1))
    store = _build_r2_trial_monitoring_writer(clock=clock)
    trial = _trial_evidence()
    monitoring = _monitoring_evidence()
    command = _command()

    trial_use_case = RegisterR2ExplanatoryTrialAssessment(
        evaluator=_Evaluator(trial),
        writer=store,
    )
    monitoring_use_case = RegisterR2MonitoringAssessment(
        evaluator=_Evaluator(monitoring),
        writer=store,
    )
    assert trial_use_case.execute(command) == trial
    assert trial_use_case.execute(command) == trial
    assert monitoring_use_case.execute(command) == monitoring
    assert monitoring_use_case.execute(command) == monitoring

    assert R2ExplanatoryTrialAssessmentLedgerModel._default_manager.count() == 1
    assert R2MonitoringAssessmentLedgerModel._default_manager.count() == 1
    assert R2MonitoringObservationLedgerModel._default_manager.count() == len(monitoring.facts)
    trial_row = R2ExplanatoryTrialAssessmentLedgerModel._default_manager.get()
    monitoring_row = R2MonitoringAssessmentLedgerModel._default_manager.get()
    repository = DjangoR2TrialMonitoringRepository(clock=clock)
    restored_trial = repository.get_trial_exact(
        reference=R2TrialAssessmentRef(
            trial_row.assessment_id,
            trial_row.assessment_version,
            trial_row.content_hash,
        ),
        as_of=clock.value,
    )
    restored_monitoring = repository.get_monitoring_exact(
        reference=R2MonitoringAssessmentRef(
            monitoring_row.assessment_id,
            monitoring_row.assessment_version,
            monitoring_row.content_hash,
        ),
        as_of=clock.value,
    )
    assert restored_trial is not None and restored_trial.evidence == trial
    assert restored_monitoring is not None and restored_monitoring.evidence == monitoring


def test_audit_snapshot_is_immutable_and_public_production_mutation_is_inert() -> None:
    clock = _Clock(NOW + timedelta(minutes=1))
    store = _build_r2_trial_monitoring_writer(clock=clock)
    RegisterR2MonitoringAssessment(
        evaluator=_Evaluator(_monitoring_evidence()),
        writer=store,
    ).execute(_command())

    with store.atomic():
        page = store.list_audit(as_of=clock.value, cursor=None, limit=1)
    assert len(page.entries) == 1
    assert page.next_cursor is None
    assert R2MonitoringAuditSnapshotModel._default_manager.count() == 1

    runtime = build_django_r2_trial_monitoring_runtime()
    assert not hasattr(runtime.register_trial, "__dict__")
    assert not hasattr(runtime.register_monitoring, "__dict__")
    assert not hasattr(runtime.audit, "__dict__")
    with pytest.raises(R2TrialMonitoringPersistenceUnavailable, match="owner providers"):
        runtime.register_trial.execute(_command())
    with pytest.raises(R2TrialMonitoringPersistenceUnavailable, match="owner providers"):
        runtime.register_monitoring.execute(_command())
    assert R2ExplanatoryTrialAssessmentLedgerModel._default_manager.count() == 1
    assert R2MonitoringAssessmentLedgerModel._default_manager.count() == 1


def test_models_reject_unclaimed_mutation() -> None:
    with pytest.raises(ValidationError, match="exact insert claim"):
        R2ExplanatoryTrialAssessmentLedgerModel._default_manager.create()
