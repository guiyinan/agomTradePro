"""Component coverage for R7 post-promotion monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import Collector

from apps.research.application.r7_post_promotion_monitoring import (
    EvaluateR7PostPromotionMonitoringCommand,
    R7MonitoringActiveOwnerGraph,
    R7PostPromotionMonitoringPolicy,
)
from apps.research.application.r7_post_promotion_monitoring_persistence import (
    GetExactR7MonitoringAssessmentCommand,
    R7MonitoringAssessmentRef,
    derive_r7_monitoring_assessment_id,
    r7_monitoring_evidence_hash,
)
from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationMember,
    R7ForecastRealizationOwnerRecord,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7LifecycleStreamOwnerEvidence,
    R7MonitoringPeriodCalendar,
    R7MonitoringPeriodEntry,
)
from apps.research.domain.r7_research_result_lifecycle import R7ResultLifecycleAction
from apps.research.infrastructure.r7_post_promotion_monitoring_models import (
    R7MonitoringAssessmentLedgerModel,
    R7MonitoringAuditSnapshotModel,
    R7MonitoringObservationLedgerModel,
)
from apps.research.r7_post_promotion_monitoring_composition import (
    _build_django_r7_monitoring_test_runtime,
)
from tests.component.research.test_r7_research_result_lifecycle_repository import (
    _apply_command,
    _authorization,
    _lifecycle_runtime,
    _result_ref,
)
from tests.component.research.test_r7_research_result_repository import _command as _result_command
from tests.component.research.test_r7_research_result_repository import (
    _runtime,
)


@dataclass
class _Clock:
    value: datetime
    unit_of_work_key: str = "django:default"

    def now(self) -> datetime:
        return self.value


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value

    def get_exact(self, **_: object) -> object:
        return self.value


def _monitoring_runtime() -> tuple[object, object, _Clock]:
    result_fixture = _runtime()
    result = result_fixture.runtime.register.execute(_result_command())
    result_fixture.clock.value += timedelta(hours=1)
    lifecycle = _lifecycle_runtime(result_fixture.clock)
    authorization = _authorization(
        result_ref=_result_ref(result),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=result_fixture.clock.value - timedelta(minutes=1),
    )
    lifecycle.provider.authorization = authorization
    event = lifecycle.runtime.apply.execute(_apply_command(authorization))
    stream = (event,)
    attestation = R7LifecycleStreamOwnerEvidence.create(
        attestation_id="r7-monitoring-lifecycle-attestation:component",
        attestation_version="r7-lifecycle-stream-owner-evidence.v1",
        owner="research",
        lifecycle_stream=stream,
        recorded_at=event.recorded_at + timedelta(seconds=1),
        valid_until=event.recorded_at + timedelta(days=30),
        evidence_ref="research://r7-monitoring/component-lifecycle",
    )
    owner_graph = R7MonitoringActiveOwnerGraph(
        result=result,
        lifecycle_stream=stream,
        lifecycle_owner_evidence=attestation,
    ).validated_copy()
    active = owner_graph.active_result()
    period = R7MonitoringPeriodEntry.create(
        calendar_id="r7-monitoring-calendar:component",
        calendar_version="v1",
        period_start=max(item.published_at for item in active.predictions) + timedelta(seconds=1),
        period_end=active.predictions[0].horizon_end,
    )
    calendar = R7MonitoringPeriodCalendar.create(
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        periods=(period,),
        recorded_at=period.period_start - timedelta(minutes=2),
        valid_from=period.period_start,
        valid_until=period.period_end,
    )
    latest_outcome = max(
        observation.outcome_recorded_at or observation.horizon_end
        for observation in result.evidence_graph.forecast_observations
    )
    members = tuple(
        R7ForecastRealizationMember.from_owner_observation(
            observation=observation,
            available_at=latest_outcome + timedelta(minutes=1),
            recorded_at=latest_outcome + timedelta(minutes=2),
            evidence_ref=f"signal://r7-monitoring/{observation.entry_id}",
        )
        for observation in result.evidence_graph.forecast_observations
    )
    realization = R7ForecastRealizationOwnerRecord.create(
        owner_record_id="r7-monitoring-realization:component",
        owner_record_version="signal-forecast-realization-owner.v1",
        period=period,
        pit_as_of=latest_outcome + timedelta(minutes=4),
        available_at=latest_outcome + timedelta(minutes=2),
        recorded_at=latest_outcome + timedelta(minutes=3),
        valid_until=attestation.valid_until,
        evidence_ref="signal://r7-monitoring/component-owner",
        members=members,
    )
    as_of = max(attestation.recorded_at, realization.pit_as_of) + timedelta(seconds=1)
    policy = R7PostPromotionMonitoringPolicy.create(
        policy_id="r7-monitoring-policy:component",
        result_id=active.result_id,
        result_version=active.result_version,
        result_hash=active.result_hash,
        lifecycle_attestation_id=active.lifecycle_attestation_id,
        lifecycle_attestation_version=active.lifecycle_attestation_version,
        lifecycle_attestation_hash=active.lifecycle_attestation_hash,
        calendar_id=calendar.calendar_id,
        calendar_version=calendar.calendar_version,
        calendar_hash=calendar.content_hash,
        period_id=period.period_id,
        period_version=period.period_version,
        period_hash=period.content_hash,
        maximum_subjective_brier_score=Decimal("0.20"),
        maximum_model_brier_score=Decimal("0.20"),
        minimum_forecast_outcome_coverage=Decimal("1"),
        recorded_at=period.period_start - timedelta(minutes=1),
        valid_until=attestation.valid_until,
    )
    command = EvaluateR7PostPromotionMonitoringCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=as_of,
    )
    clock = _Clock(as_of + timedelta(seconds=1))
    runtime = _build_django_r7_monitoring_test_runtime(
        policy_provider=_Provider(policy),
        active_owner_graph_provider=_Provider(owner_graph),
        calendar_provider=_Provider(calendar),
        realization_provider=_Provider(realization),
        clock=clock,
    )
    return runtime, command, clock


@pytest.mark.django_db
def test_append_exact_pit_winner_replay_and_outer_rollback() -> None:
    runtime, command, clock = _monitoring_runtime()

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            runtime.register.execute(command)
            raise RuntimeError("outer rollback")
    assert R7MonitoringAssessmentLedgerModel._default_manager.count() == 0
    assert R7MonitoringObservationLedgerModel._default_manager.count() == 0

    evidence = runtime.register.execute(command)
    reference = R7MonitoringAssessmentRef(
        assessment_id=derive_r7_monitoring_assessment_id(command),
        assessment_version=evidence.assessment.assessment_version,
        content_hash=r7_monitoring_evidence_hash(evidence),
    )
    stored = runtime.get_exact.execute(
        GetExactR7MonitoringAssessmentCommand(
            reference=reference,
            as_of=clock.value,
        )
    )
    assert stored is not None
    assert stored.evidence == evidence
    assert stored.ledger_recorded_at == clock.value
    assert R7MonitoringAssessmentLedgerModel._default_manager.count() == 1
    assert R7MonitoringObservationLedgerModel._default_manager.count() == len(
        evidence.realization_owner_record.members
    )

    clock.value += timedelta(minutes=1)
    assert runtime.register.execute(command) == evidence
    replay = runtime.get_exact.execute(
        GetExactR7MonitoringAssessmentCommand(reference=reference, as_of=clock.value)
    )
    assert replay is not None
    assert replay.ledger_recorded_at == stored.ledger_recorded_at
    assert R7MonitoringAssessmentLedgerModel._default_manager.count() == 1


@pytest.mark.django_db
def test_common_orm_and_collector_mutations_are_rejected() -> None:
    runtime, command, _ = _monitoring_runtime()
    runtime.register.execute(command)
    row = R7MonitoringAssessmentLedgerModel._default_manager.get()
    observation = R7MonitoringObservationLedgerModel._default_manager.first()
    assert observation is not None

    row.status = "healthy"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        R7MonitoringAssessmentLedgerModel._default_manager.update(status="healthy")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        R7MonitoringObservationLedgerModel._base_manager.filter(pk=observation.pk).delete()
    with pytest.raises(ValidationError, match="get_or_create"):
        R7MonitoringAuditSnapshotModel._default_manager.get_or_create(snapshot_id="forbidden")
    with pytest.raises(ValidationError, match="repository appends"):
        R7MonitoringObservationLedgerModel._default_manager.bulk_create([])
    with pytest.raises(ValidationError, match="exact insert claim"):
        row.observations.create(
            observation_index=999,
            observation_id="forbidden",
        )
    collector = Collector(using="default")
    collector.collect([observation])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        with transaction.atomic():
            collector.delete()
