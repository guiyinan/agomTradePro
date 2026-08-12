"""Narrow Portfolio raw receipt projections for R8 Phase A monitoring ports."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.domain._optimization_canonical import (
    require_aware,
    require_sha256,
    require_token,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    OptimizationMonitoringMetricObservation,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
)
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringSourceOwner,
    OptimizationMonitoringOwnerMetricPayload,
)
from apps.portfolio.domain.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedback,
)
from apps.portfolio.infrastructure.r8_broker_monitoring_feedback_adapter import (
    DjangoR8BrokerMonitoringFeedbackAdapter,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_repository import (
    DjangoPortfolioR8MonitoringFeedbackRepository,
)


class DjangoPortfolioR8MonitoringFeedbackAdapter:
    """Read seven-member Portfolio receipts and derive eight sealed ratios live."""

    __slots__ = ("_repository", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._repository = DjangoPortfolioR8MonitoringFeedbackRepository(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return f"django:{self._using}"

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        receipt_id: str,
        receipt_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[OptimizationMonitoringSourceEvidence, ...]:
        """Return exact complete Portfolio evidence or preserve absence as empty."""

        values = self._repository.list_exact(
            result_id=result_id,
            result_hash=result_hash,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            calendar_id=calendar_id,
            calendar_hash=calendar_hash,
            period_ids=period_ids,
            as_of=as_of,
        )
        if values is None:
            return ()
        if type(values) is not tuple or any(
            type(item) is not PortfolioR8MonitoringFeedback for item in values
        ):
            raise ValueError("Portfolio R8 feedback repository returned another type")
        return tuple(_to_monitoring_source_evidence(item) for item in values)


class DjangoR8MonitoringRawFactAdapter:
    """Rebuild complete eleven-metric observations from Portfolio and Broker receipts."""

    __slots__ = ("_broker", "_portfolio", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._portfolio = DjangoPortfolioR8MonitoringFeedbackAdapter(using=using)
        self._broker = DjangoR8BrokerMonitoringFeedbackAdapter(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return f"django:{self._using}"

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        receipt_id: str,
        receipt_hash: str,
        policy_id: str,
        policy_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[OptimizationMonitoringPeriodObservation, ...]:
        """Return complete raw observations; any missing owner remains blocked."""

        _validate_raw_query(policy_id, policy_hash, period_ids, as_of)
        portfolio = self._portfolio.list_exact(
            result_id=result_id,
            result_hash=result_hash,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            calendar_id=calendar_id,
            calendar_hash=calendar_hash,
            period_ids=period_ids,
            as_of=as_of,
        )
        broker = self._broker.list_exact(
            result_id=result_id,
            result_hash=result_hash,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            calendar_id=calendar_id,
            calendar_hash=calendar_hash,
            period_ids=period_ids,
            as_of=as_of,
        )
        return _build_period_observations(
            portfolio=portfolio,
            broker=broker,
            period_ids=period_ids,
        )


def _to_monitoring_source_evidence(
    value: PortfolioR8MonitoringFeedback,
) -> OptimizationMonitoringSourceEvidence:
    if type(value) is not PortfolioR8MonitoringFeedback:
        raise TypeError("Portfolio R8 feedback must use the exact Domain type")
    feedback = PortfolioR8MonitoringFeedback.validated_copy(value)
    payload = tuple(
        OptimizationMonitoringOwnerMetricPayload.create(
            metric_key=item.metric_key,
            value=item.value,
            evidence_namespace=f"r8.monitoring.{item.metric_key.value}.v1",
        )
        for item in feedback.metric_facts
    )
    evidence = OptimizationMonitoringSourceEvidence.create(
        owner=MonitoringSourceOwner.PORTFOLIO,
        evidence_id=feedback.feedback_id,
        evidence_version=feedback.feedback_version,
        result_id=feedback.result_id,
        result_hash=feedback.result_hash,
        receipt_id=feedback.receipt_id,
        receipt_hash=feedback.receipt_hash,
        period_id=feedback.period_id,
        metric_payload=payload,
        observed_at=feedback.observed_at,
        available_at=feedback.available_at,
    )
    OptimizationMonitoringSourceEvidence.__post_init__(evidence)
    return evidence


def _build_period_observations(
    *,
    portfolio: tuple[OptimizationMonitoringSourceEvidence, ...],
    broker: tuple[OptimizationMonitoringSourceEvidence, ...],
    period_ids: tuple[str, ...],
) -> tuple[OptimizationMonitoringPeriodObservation, ...]:
    if type(portfolio) is not tuple or type(broker) is not tuple:
        raise TypeError("R8 monitoring evidence collections must be exact tuples")
    for evidence in (*portfolio, *broker):
        if type(evidence) is not OptimizationMonitoringSourceEvidence:
            raise TypeError("R8 monitoring evidence type differs")
        OptimizationMonitoringSourceEvidence.__post_init__(evidence)
    portfolio_by_period = {item.period_id: item for item in portfolio}
    broker_by_period = {item.period_id: item for item in broker}
    expected = set(period_ids)
    if (
        len(portfolio_by_period) != len(portfolio)
        or len(broker_by_period) != len(broker)
        or set(portfolio_by_period) != expected
        or set(broker_by_period) != expected
    ):
        return ()
    observations: list[OptimizationMonitoringPeriodObservation] = []
    for period_id in period_ids:
        evidence_set = (portfolio_by_period[period_id], broker_by_period[period_id])
        metrics = tuple(
            OptimizationMonitoringMetricObservation.create(
                metric_key=payload.metric_key,
                value=payload.value,
                source_evidence=evidence,
                evidence_namespace=payload.evidence_namespace,
            )
            for evidence in evidence_set
            for payload in evidence.metric_payload
        )
        observation = OptimizationMonitoringPeriodObservation.create(
            period_id=period_id,
            metrics=metrics,
        )
        OptimizationMonitoringPeriodObservation.__post_init__(observation)
        observations.append(observation)
    return tuple(observations)


def _validate_raw_query(
    policy_id: str,
    policy_hash: str,
    period_ids: tuple[str, ...],
    as_of: datetime,
) -> None:
    require_token(policy_id, "R8 monitoring raw policy_id")
    require_sha256(policy_hash, "R8 monitoring raw policy_hash")
    if type(period_ids) is not tuple or not period_ids or len(set(period_ids)) != len(period_ids):
        raise ValueError("R8 monitoring raw period ids must be a non-empty unique tuple")
    for period_id in period_ids:
        require_token(period_id, "R8 monitoring raw period_id")
    require_aware(as_of, "R8 monitoring raw as_of")


__all__ = [
    "DjangoPortfolioR8MonitoringFeedbackAdapter",
    "DjangoR8MonitoringRawFactAdapter",
]
