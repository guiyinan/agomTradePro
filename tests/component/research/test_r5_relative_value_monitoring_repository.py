"""Component coverage for the R5 monitoring append-only persistence graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import Collector
from django.test import override_settings

from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoringCommand,
    R5MonitoringEvaluationEvidence,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    R5MonitoringAssessmentRef,
    R5MonitoringPersistenceConflict,
    R5MonitoringPersistenceCorruption,
    R5MonitoringPersistenceUnavailable,
    RegisterR5MonitoringAssessment,
)
from apps.research.domain.r5_relative_value_monitoring import (
    evaluate_r5_post_promotion_monitoring,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringMetricKey,
    R5MonitoringPeriodEntry,
    R5MonitoringPolicy,
    R5MonitoringTarget,
    R5MonitoringThreshold,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5MonitoringPortfolioSourceProjection,
    R5PostPromotionMonitoringFact,
)
from apps.research.domain.r5_relative_value_monitoring_owners import (
    R5MonitoringOwnerRef,
    R5MonitoringOwnerRole,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAssessmentLedgerModel,
    R5MonitoringAuditSnapshotModel,
    R5MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r5_relative_value_monitoring_repository import (
    DjangoR5MonitoringRepository,
    _build_r5_monitoring_writer,
)
from apps.research.r5_relative_value_monitoring_composition import (
    build_django_r5_monitoring_runtime,
)
from tests.component.research.test_r5_relative_value_promotion_repository import (
    _graph,
    _lifecycle_command,
    _register_graph,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _hash(label: str) -> str:
    return sha256(label.encode()).hexdigest()


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class _FailingClock:
    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@dataclass
class _Evaluator:
    evidence: R5MonitoringEvaluationEvidence
    unit_of_work_key: str = "django:default"

    def execute_evidence(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5MonitoringEvaluationEvidence:
        assert command.as_of == self.evidence.assessment.evaluated_at
        return self.evidence


def _owner_ref(
    role: R5MonitoringOwnerRole,
    owner: str,
    identity: str,
    digest: str,
    *,
    known_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> R5MonitoringOwnerRef:
    return R5MonitoringOwnerRef(
        role=role,
        owner=owner,
        owner_id=identity,
        owner_version="v1",
        content_hash=digest,
        known_at=known_at,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    R5MonitoringEvaluationEvidence,
    EvaluateR5PostPromotionMonitoringCommand,
]:
    graph = _graph(monkeypatch)
    _register_graph(graph)
    lifecycle_command = _lifecycle_command(graph)
    decision = graph.runtime.evaluate.execute(graph.decision_command)
    event = graph.runtime.apply_lifecycle.execute(lifecycle_command)
    owner_seals = tuple(
        sorted({item.fixed_income_record.content_hash for item in decision.trial.observations})
    )
    active = R5MonitoringActiveLifecycle.create(
        scope_id=decision.scope.scope_id,
        scope_hash=decision.scope.content_hash,
        decision_id=decision.decision_id,
        decision_version=decision.decision_version,
        decision_hash=decision.content_hash,
        trial_id=decision.trial.trial_id,
        trial_hash=decision.trial.content_hash,
        fixed_income_owner_seal_hashes=owner_seals,
        stream_id=event.stream_id,
        latest_event_id=event.event_id,
        latest_event_hash=event.content_hash,
        promoted_at=event.occurred_at,
        recorded_at=event.recorded_at,
        valid_until=decision.valid_until,
    )
    owner_record = decision.trial.observations[-1].fixed_income_record
    fixed_income = R5MonitoringFixedIncomeEvidence.create(
        result_id=owner_record.result_id,
        result_version=owner_record.result_version,
        result_hash=owner_record.result_record_hash,
        owner_seal_id=owner_record.owner_record_key,
        owner_seal_version="v1",
        owner_seal_hash=owner_record.content_hash,
        recorded_at=owner_record.recorded_at,
    )
    first_start = event.recorded_at + timedelta(minutes=20)
    calendar_recorded_at = event.recorded_at + timedelta(minutes=1)
    valid_until = decision.valid_until
    calendar_owner = _owner_ref(
        R5MonitoringOwnerRole.CALENDAR,
        "research",
        "r5-monitoring-calendar",
        _hash("calendar-owner"),
        known_at=event.recorded_at,
        recorded_at=calendar_recorded_at,
        valid_until=valid_until,
    )
    periods = tuple(
        R5MonitoringPeriodEntry.create(
            calendar_id=calendar_owner.owner_id,
            calendar_version=calendar_owner.owner_version,
            period_start=first_start + timedelta(minutes=10 * index),
            period_end=first_start + timedelta(minutes=10 * (index + 1)),
        )
        for index in range(3)
    )
    calendar = R5MonitoringCalendar.create(
        owner=calendar_owner,
        entries=periods,
        recorded_at=calendar_recorded_at,
        valid_until=valid_until,
    )
    policy_recorded_at = event.recorded_at + timedelta(minutes=5)
    target = R5MonitoringTarget.create(
        active_lifecycle=active,
        fixed_income=fixed_income,
        benchmark=_owner_ref(
            R5MonitoringOwnerRole.BENCHMARK,
            "research",
            "r5-monitoring-benchmark",
            _hash("benchmark"),
            known_at=event.occurred_at - timedelta(minutes=2),
            recorded_at=event.occurred_at - timedelta(minutes=1),
            valid_until=valid_until,
        ),
        cost_policy=_owner_ref(
            R5MonitoringOwnerRole.COST_POLICY,
            "portfolio",
            "r5-monitoring-cost",
            _hash("cost"),
            known_at=event.occurred_at - timedelta(minutes=2),
            recorded_at=event.occurred_at - timedelta(minutes=1),
            valid_until=valid_until,
        ),
        liquidity_policy=_owner_ref(
            R5MonitoringOwnerRole.LIQUIDITY_POLICY,
            "portfolio",
            "r5-monitoring-liquidity",
            _hash("liquidity"),
            known_at=event.occurred_at - timedelta(minutes=2),
            recorded_at=event.occurred_at - timedelta(minutes=1),
            valid_until=valid_until,
        ),
        label_baseline=_owner_ref(
            R5MonitoringOwnerRole.LABEL_BASELINE,
            "research",
            "r5-monitoring-label",
            _hash("label"),
            known_at=event.occurred_at - timedelta(minutes=2),
            recorded_at=event.occurred_at - timedelta(minutes=1),
            valid_until=valid_until,
        ),
        data_schema=_owner_ref(
            R5MonitoringOwnerRole.DATA_SCHEMA,
            "fixed_income",
            "r5-monitoring-schema",
            _hash("schema"),
            known_at=event.occurred_at - timedelta(minutes=2),
            recorded_at=event.occurred_at - timedelta(minutes=1),
            valid_until=valid_until,
        ),
    )
    threshold_values = {
        R5MonitoringMetricKey.COVERAGE_RATIO: Decimal("1"),
        R5MonitoringMetricKey.EXCESS_NET_RETURN: Decimal("0"),
        R5MonitoringMetricKey.DRAWDOWN_INCREASE: Decimal("0.03"),
        R5MonitoringMetricKey.TOTAL_TARGET_COST: Decimal("0.02"),
        R5MonitoringMetricKey.LIQUIDITY_BREACH: Decimal("0"),
        R5MonitoringMetricKey.PEAK_CAPACITY_UTILIZATION: Decimal("0.9"),
        R5MonitoringMetricKey.REALIZED_CREDIT_LOSS: Decimal("0.01"),
    }
    policy = R5MonitoringPolicy.create(
        policy_scope_id="r5-post-promotion-monitoring",
        target=target,
        calendar=calendar,
        thresholds=tuple(
            R5MonitoringThreshold.canonical(
                metric_key=key,
                breach_threshold=threshold_values[key],
                retirement_review_consecutive_breaches=2,
            )
            for key in R5MonitoringMetricKey
        ),
        minimum_complete_periods=3,
        maximum_period_age_seconds=3600,
        maximum_source_delay_seconds=3600,
        recorded_at=policy_recorded_at,
        valid_until=valid_until,
    )
    facts: list[R5PostPromotionMonitoringFact] = []
    for index, period in enumerate(periods):
        source_owner = _owner_ref(
            R5MonitoringOwnerRole.PORTFOLIO_MONITORING_SOURCE,
            "portfolio",
            f"r5-monitoring-source-{index}",
            _hash(f"source-{index}"),
            known_at=period.period_end,
            recorded_at=period.period_end + timedelta(minutes=2),
            valid_until=valid_until,
        )
        projection = R5MonitoringPortfolioSourceProjection.create(
            owner_record=source_owner,
            source_observed_at=period.period_end - timedelta(minutes=1),
            coverage_observed_count=10,
            coverage_expected_count=10,
            target_gross_return=Decimal("0.025"),
            benchmark_gross_return=Decimal("0.01"),
            target_execution_cost=Decimal("0.01"),
            target_financing_cost=Decimal("0"),
            target_liquidity_cost=Decimal("0"),
            benchmark_execution_cost=Decimal("0.005"),
            benchmark_financing_cost=Decimal("0"),
            benchmark_liquidity_cost=Decimal("0"),
            target_drawdown=Decimal("0.03"),
            benchmark_drawdown=Decimal("0.02"),
            liquidity_breach_count=0,
            liquidity_eligible_count=10,
            capacity_used=Decimal("7"),
            capacity_limit=Decimal("10"),
            realized_credit_loss=Decimal("0.001"),
            credit_exposure=Decimal("1"),
        )
        observed_at = period.period_end + timedelta(minutes=5)
        facts.append(
            R5PostPromotionMonitoringFact.create(
                fact_id=f"r5-monitoring-fact-{index}",
                fact_version="v1",
                period=period,
                calendar=calendar,
                target=target,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_hash=policy.content_hash,
                source_projection=projection,
                observed_at=observed_at,
                available_at=observed_at + timedelta(minutes=1),
                recorded_at=observed_at + timedelta(minutes=2),
                valid_until=valid_until,
                observed_label_hash=target.label_baseline.content_hash,
                observed_data_schema_hash=target.data_schema.content_hash,
            )
        )
    evaluated_at = periods[-1].period_end + timedelta(minutes=15)
    assessment = evaluate_r5_post_promotion_monitoring(
        requested_policy_id=policy.policy_id,
        requested_policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        active_lifecycle=active,
        fixed_income=fixed_income,
        policy=policy,
        calendar=calendar,
        portfolio_facts=tuple(facts),
        evaluated_at=evaluated_at,
    )
    evidence = R5MonitoringEvaluationEvidence(
        policy=policy,
        active_lifecycle=active,
        calendar=calendar,
        fixed_income=fixed_income,
        portfolio_facts=tuple(facts),
        assessment=assessment,
    )
    command = EvaluateR5PostPromotionMonitoringCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=evaluated_at,
    )
    return evidence, command


def _reevaluated_evidence(
    evidence: R5MonitoringEvaluationEvidence,
    command: EvaluateR5PostPromotionMonitoringCommand,
    *,
    evaluated_at: datetime,
) -> tuple[R5MonitoringEvaluationEvidence, EvaluateR5PostPromotionMonitoringCommand]:
    assert evidence.active_lifecycle is not None
    assert evidence.fixed_income is not None
    assert evidence.policy is not None
    assert evidence.calendar is not None
    assessment = evaluate_r5_post_promotion_monitoring(
        requested_policy_id=command.policy_id,
        requested_policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        active_lifecycle=evidence.active_lifecycle,
        fixed_income=evidence.fixed_income,
        policy=evidence.policy,
        calendar=evidence.calendar,
        portfolio_facts=evidence.portfolio_facts,
        evaluated_at=evaluated_at,
    )
    return (
        replace(evidence, assessment=assessment),
        replace(command, as_of=evaluated_at),
    )


def _forked_evidence(
    evidence: R5MonitoringEvaluationEvidence,
    command: EvaluateR5PostPromotionMonitoringCommand,
) -> R5MonitoringEvaluationEvidence:
    assert evidence.active_lifecycle is not None
    assert evidence.fixed_income is not None
    assert evidence.policy is not None
    assert evidence.calendar is not None
    original = evidence.portfolio_facts[0]
    period = next(
        item for item in evidence.calendar.entries if item.period_id == original.period_id
    )
    projection = replace(
        original.source_projection,
        target_gross_return=Decimal("-0.50"),
    )
    forked_fact = R5PostPromotionMonitoringFact.create(
        fact_id=original.fact_id,
        fact_version=original.fact_version,
        period=period,
        calendar=evidence.calendar,
        target=evidence.policy.target,
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        policy_hash=original.policy_hash,
        source_projection=projection,
        observed_at=original.observed_at,
        available_at=original.available_at,
        recorded_at=original.recorded_at,
        valid_until=original.valid_until,
        observed_label_hash=original.observed_label_hash,
        observed_data_schema_hash=original.observed_data_schema_hash,
    )
    facts = (forked_fact, *evidence.portfolio_facts[1:])
    assessment = evaluate_r5_post_promotion_monitoring(
        requested_policy_id=command.policy_id,
        requested_policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        active_lifecycle=evidence.active_lifecycle,
        fixed_income=evidence.fixed_income,
        policy=evidence.policy,
        calendar=evidence.calendar,
        portfolio_facts=facts,
        evaluated_at=command.as_of,
    )
    return replace(evidence, portfolio_facts=facts, assessment=assessment)


def test_register_exact_pit_and_clock_forward_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, command = _evidence(monkeypatch)
    clock = _Clock(command.as_of + timedelta(minutes=1))
    store = _build_r5_monitoring_writer(clock=clock)
    register = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=store,
    )

    first = register.execute(command)
    first_clock = first.ledger_recorded_at
    clock.current += timedelta(minutes=5)
    second = register.execute(command)

    assert second == first
    assert second.ledger_recorded_at == first_clock
    assert R5MonitoringAssessmentLedgerModel._default_manager.count() == 1
    assert R5MonitoringObservationLedgerModel._default_manager.count() == 3
    assert (
        store.get_exact(
            assessment_ref=first.assessment_ref,
            as_of=first_clock - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        store.get_exact(
            assessment_ref=first.assessment_ref,
            as_of=first_clock,
        )
        == first
    )


def test_existing_exact_winner_replays_without_a_new_server_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, command = _evidence(monkeypatch)
    clock = _Clock(command.as_of + timedelta(minutes=1))
    first = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=_build_r5_monitoring_writer(clock=clock),
    ).execute(command)

    clock.current = command.as_of - timedelta(hours=1)
    regressed = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=_build_r5_monitoring_writer(clock=clock),
    ).execute(command)
    unavailable = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=_build_r5_monitoring_writer(clock=_FailingClock()),
    ).execute(command)

    assert regressed == first
    assert unavailable == first
    assert R5MonitoringAssessmentLedgerModel._default_manager.count() == 1
    assert R5MonitoringObservationLedgerModel._default_manager.count() == 3


def test_signed_audit_snapshot_is_stable_across_pages_and_secret_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_evidence, first_command = _evidence(monkeypatch)
    second_evidence, second_command = _reevaluated_evidence(
        first_evidence,
        first_command,
        evaluated_at=first_command.as_of + timedelta(minutes=1),
    )
    clock = _Clock(second_command.as_of + timedelta(minutes=1))
    store = _build_r5_monitoring_writer(clock=clock)
    RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(first_evidence),
        writer=store,
    ).execute(first_command)
    RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(second_evidence),
        writer=store,
    ).execute(second_command)

    with patch("django.core.signing.time.time", return_value=1_000.0):
        first_page = store.list_audit(as_of=clock.current, cursor=None, limit=1)
    assert len(first_page.entries) == 1
    assert first_page.next_cursor is not None
    assert R5MonitoringAuditSnapshotModel._default_manager.count() == 1

    with patch("django.core.signing.time.time", return_value=1_005.0):
        second_page = store.list_audit(
            as_of=clock.current,
            cursor=first_page.next_cursor,
            limit=1,
        )
    assert len(second_page.entries) == 1
    assert second_page.next_cursor is None

    suffix = "x" if not first_page.next_cursor.endswith("x") else "y"
    tampered = f"{first_page.next_cursor[:-1]}{suffix}"
    with pytest.raises(R5MonitoringPersistenceUnavailable, match="signature|noncanonical"):
        store.list_audit(as_of=clock.current, cursor=tampered, limit=1)
    with pytest.raises(R5MonitoringPersistenceUnavailable, match="another cutoff"):
        store.list_audit(
            as_of=clock.current - timedelta(microseconds=1),
            cursor=first_page.next_cursor,
            limit=1,
        )
    with override_settings(SECRET_KEY="another-r5-monitoring-test-secret"):
        with pytest.raises(R5MonitoringPersistenceUnavailable, match="signature"):
            store.list_audit(
                as_of=clock.current,
                cursor=first_page.next_cursor,
                limit=1,
            )


def test_actual_integrity_race_replays_exact_winner_and_rejects_fork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, command = _evidence(monkeypatch)
    clock = _Clock(command.as_of + timedelta(minutes=1))
    first = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=_build_r5_monitoring_writer(clock=clock),
    ).execute(command)
    store = _build_r5_monitoring_writer(clock=clock)
    store_type = type(store)
    original_collisions = store_type._assessment_collisions  # noqa: SLF001

    collision_reads = 0

    def hide_winner_twice(self: object, assessment: object) -> object:
        nonlocal collision_reads
        collision_reads += 1
        if collision_reads <= 2:
            return ()
        return original_collisions(self, assessment)

    with patch.object(store_type, "_assessment_collisions", hide_winner_twice):
        replayed = RegisterR5MonitoringAssessment(
            evaluator=_Evaluator(evidence),
            writer=store,
        ).execute(command)
    assert replayed == first
    assert collision_reads >= 3

    forked_evidence = _forked_evidence(evidence, command)
    collision_reads = 0
    with patch.object(store_type, "_assessment_collisions", hide_winner_twice):
        with pytest.raises(R5MonitoringPersistenceConflict, match="race"):
            RegisterR5MonitoringAssessment(
                evaluator=_Evaluator(forked_evidence),
                writer=store,
            ).execute(command)
    assert collision_reads >= 3
    assert R5MonitoringAssessmentLedgerModel._default_manager.count() == 1
    assert R5MonitoringObservationLedgerModel._default_manager.count() == 3


def test_normal_django_mutation_and_collector_paths_are_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, command = _evidence(monkeypatch)
    store = _build_r5_monitoring_writer(clock=_Clock(command.as_of + timedelta(minutes=1)))
    RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=store,
    ).execute(command)
    assessment = R5MonitoringAssessmentLedgerModel._default_manager.get()
    observation = R5MonitoringObservationLedgerModel._default_manager.order_by("pk").first()
    assert observation is not None
    decision = observation.active_decision
    unsaved_snapshot = R5MonitoringAuditSnapshotModel()

    forbidden = (
        lambda: R5MonitoringObservationLedgerModel._default_manager.create(),
        lambda: R5MonitoringObservationLedgerModel._base_manager.create(),
        lambda: decision.r5_monitoring_observations.create(),
        lambda: observation.save(),
        lambda: observation.save_base(),
        lambda: observation.delete(),
        lambda: R5MonitoringObservationLedgerModel._default_manager.all().update(
            source_owner="caller"
        ),
        lambda: R5MonitoringObservationLedgerModel._default_manager.all().delete(),
        lambda: R5MonitoringObservationLedgerModel._default_manager.bulk_create([]),
        lambda: R5MonitoringObservationLedgerModel._default_manager.bulk_update(
            [observation], ["source_owner"]
        ),
        lambda: R5MonitoringObservationLedgerModel._default_manager.get_or_create(fact_id="caller"),
        lambda: R5MonitoringObservationLedgerModel._default_manager.update_or_create(
            fact_id="caller"
        ),
        lambda: R5MonitoringObservationLedgerModel._default_manager.all()._update([]),
        lambda: R5MonitoringObservationLedgerModel._default_manager.all()._raw_delete("default"),
        lambda: R5MonitoringObservationLedgerModel._default_manager.all()._insert(
            [observation], []
        ),
        lambda: R5MonitoringObservationLedgerModel._default_manager.all()._batched_insert(
            [observation], [], None
        ),
        lambda: assessment.save(),
        lambda: assessment.save_base(),
        lambda: assessment.delete(),
        lambda: R5MonitoringAssessmentLedgerModel._base_manager.create(),
        lambda: R5MonitoringAssessmentLedgerModel._default_manager.bulk_create([]),
        lambda: R5MonitoringAuditSnapshotModel._default_manager.create(),
        lambda: R5MonitoringAuditSnapshotModel._base_manager.create(),
        lambda: unsaved_snapshot.save(),
        lambda: unsaved_snapshot.save_base(),
        lambda: unsaved_snapshot.delete(),
    )
    for operation in forbidden:
        with pytest.raises(ValidationError):
            operation()

    collector = Collector(using="default")
    collector.collect([observation])
    with transaction.atomic(), pytest.raises(ValidationError):
        collector.delete()


def test_outer_rollback_and_runtime_remain_zero_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, command = _evidence(monkeypatch)
    clock = _Clock(command.as_of + timedelta(minutes=1))
    store = _build_r5_monitoring_writer(clock=clock)
    register = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=store,
    )

    with pytest.raises(RuntimeError, match="rollback"):
        with transaction.atomic():
            register.execute(command)
            raise RuntimeError("rollback")

    assert R5MonitoringAssessmentLedgerModel._default_manager.count() == 0
    assert R5MonitoringObservationLedgerModel._default_manager.count() == 0
    runtime = build_django_r5_monitoring_runtime()
    with pytest.raises(R5MonitoringPersistenceUnavailable):
        runtime.register.execute(command)
    assert R5MonitoringAssessmentLedgerModel._default_manager.count() == 0
    assert not hasattr(runtime.register, "__dict__")
    assert not hasattr(runtime.register, "_writer")


def test_row_tamper_and_normal_orm_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, command = _evidence(monkeypatch)
    clock = _Clock(command.as_of + timedelta(minutes=1))
    store = _build_r5_monitoring_writer(clock=clock)
    persisted = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(evidence),
        writer=store,
    ).execute(command)
    row = R5MonitoringAssessmentLedgerModel._default_manager.get()

    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R5MonitoringAssessmentLedgerModel._default_manager.update(status="healthy")
    with pytest.raises(ValidationError):
        R5MonitoringAssessmentLedgerModel._default_manager.all().delete()
    with pytest.raises(ValidationError):
        R5MonitoringAuditSnapshotModel._default_manager.create()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_monitoring_assessment "
            "SET ledger_header_hash = %s WHERE assessment_id = %s",
            ["0" * 64, row.assessment_id],
        )
    with pytest.raises(R5MonitoringPersistenceCorruption):
        DjangoR5MonitoringRepository(clock=clock).get_exact(
            assessment_ref=R5MonitoringAssessmentRef(
                persisted.assessment.assessment_id,
                persisted.assessment.content_hash,
            ),
            as_of=clock.current,
        )
