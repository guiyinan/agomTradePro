"""Narrow Broker receipt projection for the Portfolio R8 monitoring port."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from apps.portfolio.domain.governed_optimization_monitoring import (
    OptimizationMonitoringSourceEvidence,
)
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
    MonitoringSourceOwner,
    OptimizationMonitoringOwnerMetricPayload,
)
from core.integration.r8_broker_monitoring import (
    build_r8_broker_monitoring_provider,
)

_METRIC_KEY_MAP: dict[str, MonitoringMetricKey] = {
    "total_cost_rate": MonitoringMetricKey.TOTAL_COST_RATE,
    "adverse_slippage_rate": MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE,
    "reconciliation_break_rate": MonitoringMetricKey.RECONCILIATION_BREAK_RATE,
}


class _BrokerReceiptProvider(Protocol):
    def list_exact(self, **kwargs: object) -> object: ...


class DjangoR8BrokerMonitoringFeedbackAdapter:
    """Read exact Broker owner receipts and project only the three sealed ratios."""

    __slots__ = ("_provider", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._provider = cast(
            _BrokerReceiptProvider,
            build_r8_broker_monitoring_provider(using=using),
        )

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
        if type(receipts) is not tuple:
            raise ValueError("Broker monitoring receipt provider returned an invalid type")
        return tuple(_to_portfolio_evidence(item) for item in receipts)


def _to_portfolio_evidence(value: object) -> OptimizationMonitoringSourceEvidence:
    validator = getattr(value, "validated_copy", None)
    if not callable(validator):
        raise ValueError("Broker monitoring receipt is not recursively validated")
    receipt = cast(Any, validator())
    if receipt != value:
        raise ValueError("Broker monitoring receipt is noncanonical")
    definition = receipt.definition
    payload_items: list[OptimizationMonitoringOwnerMetricPayload] = []
    for item in definition.metric_facts:
        raw_key = getattr(getattr(item, "metric_key", None), "value", None)
        if type(raw_key) is not str or raw_key not in _METRIC_KEY_MAP:
            raise ValueError("Broker monitoring receipt has an unsupported metric")
        payload_items.append(
            OptimizationMonitoringOwnerMetricPayload.create(
                metric_key=_METRIC_KEY_MAP[raw_key],
                value=item.value,
                evidence_namespace=f"r8.monitoring.{raw_key}.v1",
            )
        )
    payload = tuple(payload_items)
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
