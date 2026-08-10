"""Synthetic Phase-A coverage for governed R8 post-promotion monitoring."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoring,
    EvaluateGovernedOptimizationMonitoringCommand,
    GovernedOptimizationMonitoringUnavailable,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    ActiveGovernedOptimizationResultEvidence,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringPolicy,
    GovernedOptimizationMonitoringTarget,
    GovernedOptimizationMonitoringThreshold,
    MonitoringAssessmentStatus,
    MonitoringMetricKey,
    MonitoringSourceOwner,
    OptimizationMonitoringMetricObservation,
    OptimizationMonitoringOwnerMetricPayload,
    OptimizationMonitoringPeriod,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
    evaluate_governed_optimization_monitoring,
    metric_observation_hash,
    monitoring_assessment_hash,
    period_observation_hash,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    create_optimization_lifecycle_event,
    create_optimization_lifecycle_root,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
)
from tests.unit.portfolio.test_governed_optimization_inputs import _input_set
from tests.unit.portfolio.test_optimization_research_evidence import _all_evaluations

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)
AS_OF = NOW + timedelta(days=4, hours=2)
H = "a" * 64


def _receipt_and_result(*, receipt_recorded_at: datetime | None = None) -> tuple[
    GovernedOptimizationInputReceipt,
    GovernedOptimizationResearchResult,
]:
    input_set = _input_set()
    receipt = GovernedOptimizationInputReceipt.record(
        input_set=input_set,
        server_recorded_at=receipt_recorded_at or input_set.created_at,
    )
    result = GovernedOptimizationResearchResult.create(
        run_key="r8-monitoring-run",
        run_version="run.v1",
        assembly_hash="1" * 64,
        problem_id="problem:r8:monitoring:v1",
        problem_hash="2" * 64,
        input_set_id=input_set.input_set_id,
        input_set_hash=input_set.content_hash,
        input_receipt_id=receipt.receipt_id,
        input_receipt_hash=receipt.content_hash,
        input_receipt_schema_version=receipt.receipt_version,
        candidate_evaluations=_all_evaluations(),
        problem_blockers=(),
        evaluated_at=NOW,
        valid_until=NOW + timedelta(days=30),
    )
    return receipt, result


def _active_result(
    result: GovernedOptimizationResearchResult,
) -> ActiveGovernedOptimizationResultEvidence:
    root = create_optimization_lifecycle_root(result)
    promotion = ExactPromotionAttestation.create(
        capability_key="r8",
        artifact_id=result.result_id,
        artifact_version=result.result_version,
        artifact_content_hash=result.content_hash,
        decision_id="promotion:r8:monitoring:v1",
        decision_content_hash="3" * 64,
        owner="research",
        approved_at=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(days=30),
    )
    promoted = create_optimization_lifecycle_event(
        result=result,
        previous_events=(root,),
        event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
        occurred_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1),
        reason_codes=("research_promotion_approved",),
        promotion_attestation=promotion,
    )
    return ActiveGovernedOptimizationResultEvidence.create(
        result=result,
        lifecycle_events=(root, promoted),
    )


def _calendar() -> GovernedOptimizationMonitoringCalendar:
    calendar_id = "r8-monitoring-calendar:daily:v1"
    calendar_version = "r8-monitoring-calendar.v1"
    periods = tuple(
        OptimizationMonitoringPeriod.create(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            index=index,
            start_at=NOW + timedelta(days=index),
            end_at=NOW + timedelta(days=index + 1),
        )
        for index in range(1, 4)
    )
    return GovernedOptimizationMonitoringCalendar.create(
        calendar_id=calendar_id,
        calendar_version=calendar_version,
        owner="portfolio",
        periods=periods,
        recorded_at=NOW + timedelta(hours=2),
        valid_until=NOW + timedelta(days=30),
    )


def _threshold_values() -> dict[MonitoringMetricKey, Decimal]:
    return {
        MonitoringMetricKey.NET_REALIZED_RETURN: Decimal("-0.02"),
        MonitoringMetricKey.MAX_DRAWDOWN: Decimal("0.10"),
        MonitoringMetricKey.TURNOVER_RATE: Decimal("0.50"),
        MonitoringMetricKey.TOTAL_COST_RATE: Decimal("0.01"),
        MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE: Decimal("0.005"),
        MonitoringMetricKey.LIQUIDITY_UTILIZATION: Decimal("0.80"),
        MonitoringMetricKey.CAPACITY_UTILIZATION: Decimal("0.80"),
        MonitoringMetricKey.CONSTRAINT_BREACH_RATE: Decimal("0"),
        MonitoringMetricKey.RECONCILIATION_BREAK_RATE: Decimal("0"),
        MonitoringMetricKey.LABEL_DRIFT_RATE: Decimal("0.10"),
        MonitoringMetricKey.DATA_DRIFT_SCORE: Decimal("0.10"),
    }


def _policy(
    calendar: GovernedOptimizationMonitoringCalendar,
    active: ActiveGovernedOptimizationResultEvidence,
    receipt: GovernedOptimizationInputReceipt,
) -> GovernedOptimizationMonitoringPolicy:
    thresholds = tuple(
        GovernedOptimizationMonitoringThreshold.create(
            metric_key=metric_key,
            threshold=value,
            evidence_namespace=f"r8.monitoring.{metric_key.value}.v1",
        )
        for metric_key, value in _threshold_values().items()
    )
    return GovernedOptimizationMonitoringPolicy.create(
        policy_id="r8-monitoring-policy:post-promotion:v1",
        owner="research",
        target=GovernedOptimizationMonitoringTarget.create(
            active_result=active,
            receipt=receipt,
            upstream_promotions=receipt.input_set.promotions,
        ),
        thresholds=thresholds,
        required_consecutive_breaches=2,
        minimum_complete_periods=3,
        max_period_lag_seconds=172800,
        max_evidence_delay_seconds=21600,
        calendar=calendar,
        recorded_at=NOW + timedelta(hours=3),
        valid_until=NOW + timedelta(days=20),
    )


def _healthy_values() -> dict[MonitoringMetricKey, Decimal]:
    return {
        MonitoringMetricKey.NET_REALIZED_RETURN: Decimal("0.01"),
        MonitoringMetricKey.MAX_DRAWDOWN: Decimal("0.05"),
        MonitoringMetricKey.TURNOVER_RATE: Decimal("0.20"),
        MonitoringMetricKey.TOTAL_COST_RATE: Decimal("0.005"),
        MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE: Decimal("0.001"),
        MonitoringMetricKey.LIQUIDITY_UTILIZATION: Decimal("0.40"),
        MonitoringMetricKey.CAPACITY_UTILIZATION: Decimal("0.50"),
        MonitoringMetricKey.CONSTRAINT_BREACH_RATE: Decimal("0"),
        MonitoringMetricKey.RECONCILIATION_BREAK_RATE: Decimal("0"),
        MonitoringMetricKey.LABEL_DRIFT_RATE: Decimal("0.02"),
        MonitoringMetricKey.DATA_DRIFT_SCORE: Decimal("0.03"),
    }


def _facts(
    *,
    calendar: GovernedOptimizationMonitoringCalendar,
    receipt: GovernedOptimizationInputReceipt,
    result: GovernedOptimizationResearchResult,
    breached_period_indexes: tuple[int, ...] = (),
    label_drift_period_indexes: tuple[int, ...] = (),
) -> tuple[
    tuple[OptimizationMonitoringSourceEvidence, ...],
    tuple[OptimizationMonitoringSourceEvidence, ...],
    tuple[OptimizationMonitoringPeriodObservation, ...],
]:
    portfolio_evidence: list[OptimizationMonitoringSourceEvidence] = []
    broker_evidence: list[OptimizationMonitoringSourceEvidence] = []
    observations: list[OptimizationMonitoringPeriodObservation] = []
    broker_keys = {
        MonitoringMetricKey.TOTAL_COST_RATE,
        MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE,
        MonitoringMetricKey.RECONCILIATION_BREAK_RATE,
    }
    for period in calendar.periods:
        values = _healthy_values()
        if period.index in breached_period_indexes:
            values[MonitoringMetricKey.MAX_DRAWDOWN] = Decimal("0.20")
            values[MonitoringMetricKey.TOTAL_COST_RATE] = Decimal("0.02")
        if period.index in label_drift_period_indexes:
            values[MonitoringMetricKey.LABEL_DRIFT_RATE] = Decimal("0.20")
        payloads = {
            owner: tuple(
                OptimizationMonitoringOwnerMetricPayload.create(
                    metric_key=metric_key,
                    value=value,
                    evidence_namespace=f"r8.monitoring.{metric_key.value}.v1",
                )
                for metric_key, value in values.items()
                if (metric_key in broker_keys) is (owner is MonitoringSourceOwner.BROKER_EXECUTION)
            )
            for owner in MonitoringSourceOwner
        }
        portfolio = OptimizationMonitoringSourceEvidence.create(
            owner=MonitoringSourceOwner.PORTFOLIO,
            evidence_id=f"portfolio-feedback:{period.period_id}",
            evidence_version="portfolio-feedback.v1",
            result_id=result.result_id,
            result_hash=result.content_hash,
            receipt_id=receipt.receipt_id,
            receipt_hash=receipt.content_hash,
            period_id=period.period_id,
            metric_payload=payloads[MonitoringSourceOwner.PORTFOLIO],
            observed_at=period.end_at - timedelta(hours=1),
            available_at=period.end_at + timedelta(hours=1),
        )
        broker = OptimizationMonitoringSourceEvidence.create(
            owner=MonitoringSourceOwner.BROKER_EXECUTION,
            evidence_id=f"broker-feedback:{period.period_id}",
            evidence_version="broker-feedback.v1",
            result_id=result.result_id,
            result_hash=result.content_hash,
            receipt_id=receipt.receipt_id,
            receipt_hash=receipt.content_hash,
            period_id=period.period_id,
            metric_payload=payloads[MonitoringSourceOwner.BROKER_EXECUTION],
            observed_at=period.end_at - timedelta(hours=1),
            available_at=period.end_at + timedelta(hours=1),
        )
        portfolio_evidence.append(portfolio)
        broker_evidence.append(broker)
        metrics = tuple(
            OptimizationMonitoringMetricObservation.create(
                metric_key=metric_key,
                value=value,
                source_evidence=(broker if metric_key in broker_keys else portfolio),
                evidence_namespace=f"r8.monitoring.{metric_key.value}.v1",
            )
            for metric_key, value in values.items()
        )
        observations.append(
            OptimizationMonitoringPeriodObservation.create(
                period_id=period.period_id,
                metrics=metrics,
            )
        )
    return tuple(portfolio_evidence), tuple(broker_evidence), tuple(observations)


def _evaluate(
    *,
    breached_period_indexes: tuple[int, ...] = (),
    label_drift_period_indexes: tuple[int, ...] = (),
    receipt_recorded_at: datetime | None = None,
):  # type: ignore[no-untyped-def]
    receipt, result = _receipt_and_result(receipt_recorded_at=receipt_recorded_at)
    active = _active_result(result)
    calendar = _calendar()
    policy = _policy(calendar, active, receipt)
    portfolio, broker, observations = _facts(
        calendar=calendar,
        receipt=receipt,
        result=result,
        breached_period_indexes=breached_period_indexes,
        label_drift_period_indexes=label_drift_period_indexes,
    )
    return evaluate_governed_optimization_monitoring(
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


def test_active_result_deterioration_requires_manual_retirement_review() -> None:
    assessment = _evaluate(breached_period_indexes=(2, 3))

    assert assessment.status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.manual_retirement_review_required is True
    assert assessment.automatic_retirement is False
    assert assessment.research_only is True
    assert assessment.must_not_execute is True
    assert assessment.must_not_use_for_decision is True


def test_monitoring_requires_consecutive_breach_but_drift_reviews_immediately() -> None:
    breached = _evaluate(breached_period_indexes=(3,))
    assert breached.status is MonitoringAssessmentStatus.BREACHED
    assert breached.manual_retirement_review_required is False

    drift = _evaluate(label_drift_period_indexes=(3,))
    assert drift.status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert drift.manual_retirement_review_required is True


def test_historical_non_drift_breach_recovers_but_historical_drift_stays_review() -> None:
    recovered = _evaluate(breached_period_indexes=(1,))
    assert recovered.status is MonitoringAssessmentStatus.HEALTHY

    drift = _evaluate(label_drift_period_indexes=(1,))
    assert drift.status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED


def test_assessment_recomputes_status_and_forbids_current_publication() -> None:
    assessment = _evaluate()
    assert assessment.must_not_publish_current is True

    tampered = deepcopy(assessment)
    object.__setattr__(tampered, "status", MonitoringAssessmentStatus.BREACHED)
    digest = monitoring_assessment_hash(tampered)
    object.__setattr__(tampered, "content_hash", digest)
    object.__setattr__(
        tampered,
        "assessment_id",
        f"r8_monitoring_assessment:{digest[:24]}",
    )
    with pytest.raises(ValueError, match="status"):
        type(tampered).__post_init__(tampered)


def test_receipt_recorded_after_evaluation_is_blocked() -> None:
    assessment = _evaluate(receipt_recorded_at=AS_OF + timedelta(seconds=1))
    assert assessment.status is MonitoringAssessmentStatus.BLOCKED


def test_missing_period_and_source_substitution_are_blocked() -> None:
    receipt, result = _receipt_and_result()
    active = _active_result(result)
    calendar = _calendar()
    policy = _policy(calendar, active, receipt)
    portfolio, broker, observations = _facts(
        calendar=calendar,
        receipt=receipt,
        result=result,
    )
    common = {
        "requested_policy_id": policy.policy_id,
        "requested_policy_version": policy.policy_version,
        "expected_policy_hash": policy.content_hash,
        "active_result": active,
        "receipt": receipt,
        "current_upstream_promotions": receipt.input_set.promotions,
        "policy": policy,
        "calendar": calendar,
        "portfolio_evidence": portfolio,
        "broker_evidence": broker,
        "evaluated_at": AS_OF,
    }
    missing = evaluate_governed_optimization_monitoring(
        **common,
        observations=(observations[0], observations[2]),
    )
    assert missing.status is MonitoringAssessmentStatus.BLOCKED

    substituted = deepcopy(observations[-1])
    cost_metric = next(
        metric
        for metric in substituted.metrics
        if metric.metric_key is MonitoringMetricKey.TOTAL_COST_RATE
    )
    object.__setattr__(cost_metric, "source_evidence_hash", "0" * 64)
    replaced_source = evaluate_governed_optimization_monitoring(
        **common,
        observations=(*observations[:-1], substituted),
    )
    assert replaced_source.status is MonitoringAssessmentStatus.BLOCKED

    same_owner_seal = deepcopy(observations[-1])
    cost_metric = next(
        metric
        for metric in same_owner_seal.metrics
        if metric.metric_key is MonitoringMetricKey.TOTAL_COST_RATE
    )
    object.__setattr__(cost_metric, "value", Decimal("0.02"))
    object.__setattr__(cost_metric, "content_hash", metric_observation_hash(cost_metric))
    object.__setattr__(
        same_owner_seal,
        "content_hash",
        period_observation_hash(same_owner_seal),
    )
    changed_value = evaluate_governed_optimization_monitoring(
        **common,
        observations=(*observations[:-1], same_owner_seal),
    )
    assert changed_value.status is MonitoringAssessmentStatus.BLOCKED


class _Provider:
    def __init__(self, value: object, key: str = "r8-monitoring:uow") -> None:
        self.value = value
        self.key = key
        self.calls = 0

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    def get_exact(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return self.value

    def list_exact(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return self.value


class _UnitOfWork:
    unit_of_work_key = "r8-monitoring:uow"

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()


class _Clock:
    def __init__(self, value: datetime = AS_OF) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _application() -> tuple[
    EvaluateGovernedOptimizationMonitoring,
    EvaluateGovernedOptimizationMonitoringCommand,
    _Provider,
]:
    receipt, result = _receipt_and_result()
    active = _active_result(result)
    calendar = _calendar()
    policy = _policy(calendar, active, receipt)
    portfolio, broker, observations = _facts(
        calendar=calendar,
        receipt=receipt,
        result=result,
        breached_period_indexes=(2, 3),
    )
    promotion_providers = {
        item.capability_key: _Provider(item) for item in receipt.input_set.promotions
    }
    raw_provider = _Provider(observations)
    use_case = EvaluateGovernedOptimizationMonitoring(
        active_result_provider=_Provider(active),
        receipt_provider=_Provider(receipt),
        r3_promotion_provider=promotion_providers["r3"],
        r4_promotion_provider=promotion_providers["r4"],
        r5_promotion_provider=promotion_providers["r5"],
        policy_provider=_Provider(policy),
        calendar_provider=_Provider(calendar),
        portfolio_feedback_provider=_Provider(portfolio),
        broker_feedback_provider=_Provider(broker),
        raw_fact_provider=raw_provider,
        unit_of_work=_UnitOfWork(),
        clock=_Clock(),
    )
    command = EvaluateGovernedOptimizationMonitoringCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=AS_OF,
    )
    return use_case, command, raw_provider


def test_application_rereads_only_identities_and_has_no_lifecycle_side_effect() -> None:
    use_case, command, raw_provider = _application()

    assessment = use_case.execute(command)

    assert assessment.status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.automatic_retirement is False
    assert raw_provider.calls == 2
    assert not hasattr(use_case, "lifecycle")
    assert not hasattr(use_case, "transition")
    assert not hasattr(use_case, "execution")


def test_application_command_uses_only_the_policy_sealed_owner_graph() -> None:
    use_case, old_command, _ = _application()
    command = EvaluateGovernedOptimizationMonitoringCommand(
        policy_id=old_command.policy_id,
        policy_version=old_command.policy_version,
        expected_policy_hash=old_command.expected_policy_hash,
        as_of=old_command.as_of,
    )

    assessment = use_case.execute(command)

    assert assessment.status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED


def test_application_blocks_owner_drift_and_normalizes_clock_failure() -> None:
    use_case, command, raw_provider = _application()

    class _DriftingRawProvider(_Provider):
        def list_exact(self, **kwargs: object) -> object:
            result = super().list_exact(**kwargs)
            if self.calls == 1:
                self.key = "r8-monitoring:other-uow"
            return result

    use_case._raw_fact_provider = _DriftingRawProvider(raw_provider.value)  # type: ignore[attr-defined]
    with pytest.raises(GovernedOptimizationMonitoringUnavailable, match="UoW identity changed"):
        use_case.execute(command)

    clock_use_case, clock_command, _ = _application()
    clock_use_case._clock = _Clock(AS_OF - timedelta(seconds=1))  # type: ignore[attr-defined]
    with pytest.raises(GovernedOptimizationMonitoringUnavailable, match="future.*as_of"):
        clock_use_case.execute(clock_command)
