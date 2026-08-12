"""Canonical metric vocabulary and value domains for R8 monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from ._optimization_canonical import decimal_text, require_finite, require_token


class MonitoringMetricKey(StrEnum):
    """Canonical metric set required for every complete monitoring period."""

    NET_REALIZED_RETURN = "net_realized_return"
    MAX_DRAWDOWN = "max_drawdown"
    TURNOVER_RATE = "turnover_rate"
    TOTAL_COST_RATE = "total_cost_rate"
    ADVERSE_SLIPPAGE_RATE = "adverse_slippage_rate"
    LIQUIDITY_UTILIZATION = "liquidity_utilization"
    CAPACITY_UTILIZATION = "capacity_utilization"
    CONSTRAINT_BREACH_RATE = "constraint_breach_rate"
    RECONCILIATION_BREAK_RATE = "reconciliation_break_rate"
    LABEL_DRIFT_RATE = "label_drift_rate"
    DATA_DRIFT_SCORE = "data_drift_score"


class MonitoringMetricUnit(StrEnum):
    """Exact unit vocabulary for R8 monitoring values."""

    DECIMAL_RETURN = "decimal_return"
    FRACTION = "fraction"
    TURNOVER_RATIO = "turnover_ratio"
    NOTIONAL_RATE = "notional_rate"
    UTILIZATION_RATIO = "utilization_ratio"
    NORMALIZED_SCORE = "normalized_score"


class MonitoringThresholdDirection(StrEnum):
    """Threshold comparison direction."""

    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class MonitoringSourceOwner(StrEnum):
    """Canonical owners allowed to publish raw R8 monitoring evidence."""

    PORTFOLIO = "portfolio"
    BROKER_EXECUTION = "broker_execution"


class MonitoringAssessmentStatus(StrEnum):
    """Outcome of one post-promotion monitoring evaluation."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"
    BLOCKED = "blocked"


class MonitoringBlockerCode(StrEnum):
    """Stable fail-closed reasons for unavailable or inconsistent evidence."""

    ACTIVE_RESULT_UNAVAILABLE = "active_result_unavailable"
    ACTIVE_RESULT_SUBSTITUTED = "active_result_substituted"
    ACTIVE_RESULT_INACTIVE = "active_result_inactive"
    ACTIVE_RESULT_FUTURE_OR_EXPIRED = "active_result_future_or_expired"
    RECEIPT_UNAVAILABLE = "receipt_unavailable"
    RECEIPT_SUBSTITUTED = "receipt_substituted"
    UPSTREAM_PROMOTION_UNAVAILABLE = "upstream_promotion_unavailable"
    UPSTREAM_PROMOTION_SUBSTITUTED = "upstream_promotion_substituted"
    UPSTREAM_PROMOTION_INACTIVE = "upstream_promotion_inactive"
    POLICY_UNAVAILABLE = "policy_unavailable"
    POLICY_SUBSTITUTED = "policy_substituted"
    POLICY_INACTIVE = "policy_inactive"
    CALENDAR_UNAVAILABLE = "calendar_unavailable"
    CALENDAR_SUBSTITUTED = "calendar_substituted"
    CALENDAR_INCOMPLETE = "calendar_incomplete"
    CALENDAR_STALE = "calendar_stale"
    SOURCE_EVIDENCE_INCOMPLETE = "source_evidence_incomplete"
    SOURCE_EVIDENCE_SUBSTITUTED = "source_evidence_substituted"
    SOURCE_EVIDENCE_FUTURE_OR_STALE = "source_evidence_future_or_stale"
    OBSERVATION_INCOMPLETE = "observation_incomplete"
    OBSERVATION_SUBSTITUTED = "observation_substituted"


_MetricSemantics = tuple[
    MonitoringMetricUnit,
    MonitoringThresholdDirection,
    MonitoringSourceOwner,
    Decimal,
    Decimal | None,
]

_METRIC_SEMANTICS: dict[MonitoringMetricKey, _MetricSemantics] = {
    MonitoringMetricKey.NET_REALIZED_RETURN: (
        MonitoringMetricUnit.DECIMAL_RETURN,
        MonitoringThresholdDirection.MINIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("-1"),
        None,
    ),
    MonitoringMetricKey.MAX_DRAWDOWN: (
        MonitoringMetricUnit.FRACTION,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        Decimal("1"),
    ),
    MonitoringMetricKey.TURNOVER_RATE: (
        MonitoringMetricUnit.TURNOVER_RATIO,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        None,
    ),
    MonitoringMetricKey.TOTAL_COST_RATE: (
        MonitoringMetricUnit.NOTIONAL_RATE,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.BROKER_EXECUTION,
        Decimal("0"),
        Decimal("1"),
    ),
    MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE: (
        MonitoringMetricUnit.NOTIONAL_RATE,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.BROKER_EXECUTION,
        Decimal("0"),
        Decimal("1"),
    ),
    MonitoringMetricKey.LIQUIDITY_UTILIZATION: (
        MonitoringMetricUnit.UTILIZATION_RATIO,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        None,
    ),
    MonitoringMetricKey.CAPACITY_UTILIZATION: (
        MonitoringMetricUnit.UTILIZATION_RATIO,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        None,
    ),
    MonitoringMetricKey.CONSTRAINT_BREACH_RATE: (
        MonitoringMetricUnit.FRACTION,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        Decimal("1"),
    ),
    MonitoringMetricKey.RECONCILIATION_BREAK_RATE: (
        MonitoringMetricUnit.FRACTION,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.BROKER_EXECUTION,
        Decimal("0"),
        Decimal("1"),
    ),
    MonitoringMetricKey.LABEL_DRIFT_RATE: (
        MonitoringMetricUnit.FRACTION,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        Decimal("1"),
    ),
    MonitoringMetricKey.DATA_DRIFT_SCORE: (
        MonitoringMetricUnit.NORMALIZED_SCORE,
        MonitoringThresholdDirection.MAXIMUM,
        MonitoringSourceOwner.PORTFOLIO,
        Decimal("0"),
        Decimal("1"),
    ),
}


def _require_exact_int(value: object, field_name: str, *, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be an exact int within [{minimum}, {maximum}]")


def _require_metric_value(metric_key: MonitoringMetricKey, value: Decimal) -> None:
    require_finite(value, f"{metric_key.value} value")
    _, _, _, minimum, maximum = _METRIC_SEMANTICS[metric_key]
    if value < minimum or (maximum is not None and value > maximum):
        upper = "unbounded" if maximum is None else decimal_text(maximum)
        raise ValueError(
            f"{metric_key.value} value must be within [{decimal_text(minimum)}, {upper}]"
        )


def _enum_index(metric_key: MonitoringMetricKey) -> int:
    return tuple(MonitoringMetricKey).index(metric_key)


@dataclass(frozen=True)
class OptimizationMonitoringOwnerMetricPayload:
    """One canonical owner-published metric value sealed by source evidence."""

    metric_key: MonitoringMetricKey
    unit: MonitoringMetricUnit
    value: Decimal
    evidence_namespace: str

    @classmethod
    def create(
        cls,
        *,
        metric_key: MonitoringMetricKey,
        value: Decimal,
        evidence_namespace: str,
    ) -> OptimizationMonitoringOwnerMetricPayload:
        """Create one payload member from the canonical metric catalog."""

        return cls(
            metric_key=metric_key,
            unit=_METRIC_SEMANTICS[metric_key][0],
            value=value,
            evidence_namespace=evidence_namespace,
        )

    def __post_init__(self) -> None:
        if type(self.metric_key) is not MonitoringMetricKey:
            raise TypeError("monitoring owner payload metric key is invalid")
        if self.unit is not _METRIC_SEMANTICS[self.metric_key][0]:
            raise ValueError("monitoring owner payload unit mismatch")
        _require_metric_value(self.metric_key, self.value)
        require_token(self.evidence_namespace, "monitoring owner payload namespace")


@dataclass(frozen=True)
class MonitoringMetricResult:
    """Derived threshold result across the exact calendar horizon."""

    metric_key: MonitoringMetricKey
    latest_value: Decimal
    threshold: Decimal
    breached_period_ids: tuple[str, ...]
    trailing_consecutive_breaches: int

    def __post_init__(self) -> None:
        if type(self.metric_key) is not MonitoringMetricKey:
            raise TypeError("monitoring metric result key is invalid")
        _require_metric_value(self.metric_key, self.latest_value)
        _require_metric_value(self.metric_key, self.threshold)
        if type(self.breached_period_ids) is not tuple:
            raise TypeError("monitoring breached period ids must be a tuple")
        for period_id in self.breached_period_ids:
            require_token(period_id, "monitoring breached period_id")
        if len(set(self.breached_period_ids)) != len(self.breached_period_ids):
            raise ValueError("monitoring breached period ids must be unique")
        _require_exact_int(
            self.trailing_consecutive_breaches,
            "monitoring trailing_consecutive_breaches",
            minimum=0,
            maximum=len(self.breached_period_ids),
        )


__all__ = [
    "MonitoringAssessmentStatus",
    "MonitoringBlockerCode",
    "MonitoringMetricKey",
    "MonitoringMetricResult",
    "MonitoringMetricUnit",
    "MonitoringSourceOwner",
    "MonitoringThresholdDirection",
    "OptimizationMonitoringOwnerMetricPayload",
]
