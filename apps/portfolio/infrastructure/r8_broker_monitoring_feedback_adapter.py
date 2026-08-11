"""Narrow Broker receipt projection for the Portfolio R8 monitoring port."""

from __future__ import annotations

from datetime import datetime

from apps.broker_execution.domain.r8_monitoring_reconciliation import (
    R8BrokerMonitoringMetricKey,
    R8BrokerMonitoringPeriodReceipt,
)
from apps.broker_execution.r8_monitoring_reconciliation_composition import (
    build_django_r8_broker_monitoring_receipt_provider,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    OptimizationMonitoringSourceEvidence,
)
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
    MonitoringSourceOwner,
    OptimizationMonitoringOwnerMetricPayload,
)

_METRIC_KEY_MAP = {
    R8BrokerMonitoringMetricKey.TOTAL_COST_RATE: MonitoringMetricKey.TOTAL_COST_RATE,
    R8BrokerMonitoringMetricKey.ADVERSE_SLIPPAGE_RATE: (MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE),
    R8BrokerMonitoringMetricKey.RECONCILIATION_BREAK_RATE: (
        MonitoringMetricKey.RECONCILIATION_BREAK_RATE
    ),
}


class DjangoR8BrokerMonitoringFeedbackAdapter:
    """Read exact Broker owner receipts and project only the three sealed ratios."""

    __slots__ = ("_provider", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._provider = build_django_r8_broker_monitoring_receipt_provider(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

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
        """Return complete exact Broker evidence or preserve absence as empty."""

        receipts = self._provider.list_exact(
            result_id=result_id,
            result_hash=result_hash,
            portfolio_receipt_id=receipt_id,
            portfolio_receipt_hash=receipt_hash,
            calendar_id=calendar_id,
            calendar_hash=calendar_hash,
            period_ids=period_ids,
            as_of=as_of,
        )
        if receipts is None:
            return ()
        if type(receipts) is not tuple or any(
            type(item) is not R8BrokerMonitoringPeriodReceipt for item in receipts
        ):
            raise ValueError("Broker monitoring receipt provider returned an invalid type")
        return tuple(_to_portfolio_evidence(item) for item in receipts)


def _to_portfolio_evidence(
    value: R8BrokerMonitoringPeriodReceipt,
) -> OptimizationMonitoringSourceEvidence:
    receipt = value.validated_copy()
    definition = receipt.definition
    payload = tuple(
        OptimizationMonitoringOwnerMetricPayload.create(
            metric_key=_METRIC_KEY_MAP[item.metric_key],
            value=item.value,
            evidence_namespace=f"r8.monitoring.{item.metric_key.value}.v1",
        )
        for item in definition.metric_facts
    )
    evidence = OptimizationMonitoringSourceEvidence.create(
        owner=MonitoringSourceOwner.BROKER_EXECUTION,
        evidence_id=receipt.receipt_id,
        evidence_version=receipt.receipt_version,
        result_id=definition.result_id,
        result_hash=definition.result_hash,
        receipt_id=definition.portfolio_receipt_id,
        receipt_hash=definition.portfolio_receipt_hash,
        period_id=definition.period_id,
        metric_payload=payload,
        observed_at=definition.observed_at,
        available_at=receipt.recorded_at,
    )
    OptimizationMonitoringSourceEvidence.__post_init__(evidence)
    return evidence


__all__ = ["DjangoR8BrokerMonitoringFeedbackAdapter"]
