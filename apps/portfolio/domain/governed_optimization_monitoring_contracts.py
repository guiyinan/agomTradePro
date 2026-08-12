"""Content-sealed post-promotion monitoring for governed R8 research results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ._optimization_canonical import (
    decimal_text,
    hash_components,
    require_aware,
    require_sha256,
    require_token,
    utc_text,
)
from .governed_input_set import ExactPromotionAttestation
from .governed_optimization_monitoring_metrics import (
    _METRIC_SEMANTICS,
    MonitoringMetricKey,
    MonitoringMetricUnit,
    MonitoringSourceOwner,
    MonitoringThresholdDirection,
    OptimizationMonitoringOwnerMetricPayload,
    _enum_index,
    _require_exact_int,
    _require_metric_value,
)
from .optimization_input_receipt import GovernedOptimizationInputReceipt
from .optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleState,
    OptimizationResearchLifecycleEvent,
    derive_optimization_lifecycle_state,
)
from .optimization_research_result import (
    GovernedOptimizationResearchResult,
    GovernedOptimizationResultStatus,
)

MONITORING_POLICY_VERSION = "governed-optimization-monitoring-policy.v1"
MONITORING_CALENDAR_VERSION = "r8-monitoring-calendar.v1"
MONITORING_OBSERVATION_VERSION = "governed-optimization-monitoring-observation.v1"
MONITORING_ASSESSMENT_VERSION = "governed-optimization-monitoring-assessment.v1"
ACTIVE_EVIDENCE_VERSION = "active-governed-optimization-result.v1"
MAX_POLICY_SECONDS = 366 * 24 * 60 * 60
MAX_MONITORING_PERIODS = 64


@dataclass(frozen=True)
class OptimizationMonitoringPeriod:
    """One exact half-open member of the canonical monitoring calendar."""

    period_id: str
    index: int
    start_at: datetime
    end_at: datetime

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        index: int,
        start_at: datetime,
        end_at: datetime,
    ) -> OptimizationMonitoringPeriod:
        """Create an identity derived from calendar membership and exact clocks."""

        period_id = _period_id(calendar_id, calendar_version, index, start_at, end_at)
        return cls(period_id=period_id, index=index, start_at=start_at, end_at=end_at)

    def __post_init__(self) -> None:
        require_token(self.period_id, "monitoring period_id")
        _require_exact_int(self.index, "monitoring period index", minimum=1, maximum=64)
        require_aware(self.start_at, "monitoring period start_at")
        require_aware(self.end_at, "monitoring period end_at")
        if self.start_at >= self.end_at:
            raise ValueError("monitoring period must have positive duration")


def _period_id(
    calendar_id: str,
    calendar_version: str,
    index: int,
    start_at: datetime,
    end_at: datetime,
) -> str:
    require_token(calendar_id, "monitoring calendar_id")
    require_token(calendar_version, "monitoring calendar_version")
    _require_exact_int(index, "monitoring period index", minimum=1, maximum=64)
    digest = hash_components(
        "governed-optimization-monitoring-period.v1",
        calendar_id,
        calendar_version,
        str(index),
        utc_text(start_at),
        utc_text(end_at),
    )
    return f"r8_monitoring_period:{digest[:24]}"


@dataclass(frozen=True)
class GovernedOptimizationMonitoringCalendar:
    """Complete, contiguous, owner-recorded period membership."""

    calendar_id: str
    calendar_version: str
    owner: str
    periods: tuple[OptimizationMonitoringPeriod, ...]
    recorded_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        owner: str,
        periods: tuple[OptimizationMonitoringPeriod, ...],
        recorded_at: datetime,
        valid_until: datetime,
    ) -> GovernedOptimizationMonitoringCalendar:
        """Seal an exact calendar without manufacturing missing members."""

        return cls(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            owner=owner,
            periods=periods,
            recorded_at=recorded_at,
            valid_until=valid_until,
            content_hash=_monitoring_calendar_hash_values(
                calendar_id, calendar_version, owner, periods, recorded_at, valid_until
            ),
        )

    def __post_init__(self) -> None:
        require_token(self.calendar_id, "monitoring calendar_id")
        require_token(self.calendar_version, "monitoring calendar_version")
        require_token(self.owner, "monitoring calendar owner")
        if self.calendar_version != MONITORING_CALENDAR_VERSION:
            raise ValueError("monitoring calendar version is unsupported")
        if self.owner != "portfolio":
            raise ValueError("monitoring calendar owner must be portfolio")
        require_aware(self.recorded_at, "monitoring calendar recorded_at")
        require_aware(self.valid_until, "monitoring calendar valid_until")
        if type(self.periods) is not tuple or not 1 <= len(self.periods) <= MAX_MONITORING_PERIODS:
            raise ValueError("monitoring calendar periods are incomplete")
        previous_end: datetime | None = None
        for expected_index, period in enumerate(self.periods, start=1):
            if type(period) is not OptimizationMonitoringPeriod:
                raise TypeError("monitoring calendar member type is invalid")
            OptimizationMonitoringPeriod.__post_init__(period)
            if period.index != expected_index:
                raise ValueError("monitoring calendar indexes are discontinuous")
            expected_id = _period_id(
                self.calendar_id,
                self.calendar_version,
                period.index,
                period.start_at,
                period.end_at,
            )
            if period.period_id != expected_id:
                raise ValueError("monitoring calendar member identity mismatch")
            if previous_end is not None and period.start_at != previous_end:
                raise ValueError("monitoring calendar must be exactly contiguous")
            previous_end = period.end_at
        if self.recorded_at > self.periods[0].start_at:
            raise ValueError("monitoring calendar must be recorded before its first period")
        if self.valid_until <= self.periods[-1].end_at:
            raise ValueError("monitoring calendar validity must cover every period")
        require_sha256(self.content_hash, "monitoring calendar content_hash")
        if self.content_hash != monitoring_calendar_hash(self):
            raise ValueError("monitoring calendar content hash mismatch")


def monitoring_calendar_hash(calendar: GovernedOptimizationMonitoringCalendar) -> str:
    """Hash the full ordered calendar membership and clocks."""

    return _monitoring_calendar_hash_values(
        calendar.calendar_id,
        calendar.calendar_version,
        calendar.owner,
        calendar.periods,
        calendar.recorded_at,
        calendar.valid_until,
    )


def _monitoring_calendar_hash_values(
    calendar_id: str,
    calendar_version: str,
    owner: str,
    periods: tuple[OptimizationMonitoringPeriod, ...],
    recorded_at: datetime,
    valid_until: datetime,
) -> str:
    return hash_components(
        "governed-optimization-monitoring-calendar.v1",
        calendar_id,
        calendar_version,
        owner,
        *(
            f"{item.period_id}|{item.index}|{utc_text(item.start_at)}|{utc_text(item.end_at)}"
            for item in periods
        ),
        utc_text(recorded_at),
        utc_text(valid_until),
    )


@dataclass(frozen=True)
class GovernedOptimizationMonitoringThreshold:
    """One policy-owned metric definition and explicit breach threshold."""

    metric_key: MonitoringMetricKey
    unit: MonitoringMetricUnit
    direction: MonitoringThresholdDirection
    source_owner: MonitoringSourceOwner
    threshold: Decimal
    evidence_namespace: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        metric_key: MonitoringMetricKey,
        threshold: Decimal,
        evidence_namespace: str,
    ) -> GovernedOptimizationMonitoringThreshold:
        """Create from the canonical typed metric catalog and an explicit value."""

        unit, direction, source_owner, _, _ = _METRIC_SEMANTICS[metric_key]
        return cls(
            metric_key=metric_key,
            unit=unit,
            direction=direction,
            source_owner=source_owner,
            threshold=threshold,
            evidence_namespace=evidence_namespace,
            content_hash=_monitoring_threshold_hash_values(
                metric_key,
                unit,
                direction,
                source_owner,
                threshold,
                evidence_namespace,
            ),
        )

    def __post_init__(self) -> None:
        if type(self.metric_key) is not MonitoringMetricKey:
            raise TypeError("monitoring threshold metric key is invalid")
        expected = _METRIC_SEMANTICS[self.metric_key]
        if (self.unit, self.direction, self.source_owner) != expected[:3]:
            raise ValueError("monitoring threshold semantics mismatch")
        _require_metric_value(self.metric_key, self.threshold)
        require_token(self.evidence_namespace, "monitoring evidence_namespace")
        require_sha256(self.content_hash, "monitoring threshold content_hash")
        if self.content_hash != monitoring_threshold_hash(self):
            raise ValueError("monitoring threshold content hash mismatch")


def monitoring_threshold_hash(threshold: GovernedOptimizationMonitoringThreshold) -> str:
    """Hash one complete metric definition."""

    return _monitoring_threshold_hash_values(
        threshold.metric_key,
        threshold.unit,
        threshold.direction,
        threshold.source_owner,
        threshold.threshold,
        threshold.evidence_namespace,
    )


def _monitoring_threshold_hash_values(
    metric_key: MonitoringMetricKey,
    unit: MonitoringMetricUnit,
    direction: MonitoringThresholdDirection,
    source_owner: MonitoringSourceOwner,
    threshold: Decimal,
    evidence_namespace: str,
) -> str:
    return hash_components(
        "governed-optimization-monitoring-threshold.v1",
        metric_key.value,
        unit.value,
        direction.value,
        source_owner.value,
        decimal_text(threshold),
        evidence_namespace,
    )


@dataclass(frozen=True)
class OptimizationPromotionSelector:
    """Identity-only selector for one current upstream Promotion."""

    capability_key: str
    decision_id: str
    decision_content_hash: str
    attestation_hash: str

    @classmethod
    def from_attestation(
        cls, attestation: ExactPromotionAttestation
    ) -> OptimizationPromotionSelector:
        """Project only canonical lookup identity from a trusted attestation."""

        ExactPromotionAttestation.__post_init__(attestation)
        return cls(
            capability_key=attestation.capability_key,
            decision_id=attestation.decision_id,
            decision_content_hash=attestation.decision_content_hash,
            attestation_hash=attestation.attestation_hash,
        )

    def __post_init__(self) -> None:
        require_token(self.capability_key, "monitoring Promotion capability_key")
        require_token(self.decision_id, "monitoring Promotion decision_id")
        require_sha256(self.decision_content_hash, "monitoring Promotion decision_content_hash")
        require_sha256(self.attestation_hash, "monitoring Promotion attestation_hash")


@dataclass(frozen=True)
class GovernedOptimizationMonitoringTarget:
    """Exact active R8 family, receipt, lifecycle, and upstream owner graph."""

    optimization_scope_id: str
    optimization_scope_hash: str
    result_id: str
    result_version: str
    result_hash: str
    receipt_id: str
    receipt_version: str
    receipt_hash: str
    r8_promotion_event_id: str
    r8_promotion_event_hash: str
    upstream_promotions: tuple[OptimizationPromotionSelector, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        active_result: ActiveGovernedOptimizationResultEvidence,
        receipt: GovernedOptimizationInputReceipt,
        upstream_promotions: tuple[ExactPromotionAttestation, ...],
    ) -> GovernedOptimizationMonitoringTarget:
        """Seal canonical selectors from trusted owner objects."""

        ActiveGovernedOptimizationResultEvidence.__post_init__(active_result)
        GovernedOptimizationInputReceipt.__post_init__(receipt)
        selectors = tuple(
            OptimizationPromotionSelector.from_attestation(item) for item in upstream_promotions
        )
        values = (
            active_result.result.problem_id,
            active_result.result.problem_hash,
            active_result.result.result_id,
            active_result.result.result_version,
            active_result.result.content_hash,
            receipt.receipt_id,
            receipt.receipt_version,
            receipt.content_hash,
            active_result.promotion_event_id,
            active_result.promotion_event_hash,
        )
        digest = _monitoring_target_hash_values(*values, selectors)
        return cls(*values, selectors, digest)

    def __post_init__(self) -> None:
        for label, value in (
            ("optimization_scope_id", self.optimization_scope_id),
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("receipt_id", self.receipt_id),
            ("receipt_version", self.receipt_version),
            ("r8_promotion_event_id", self.r8_promotion_event_id),
        ):
            require_token(value, f"monitoring target {label}")
        for label, value in (
            ("optimization_scope_hash", self.optimization_scope_hash),
            ("result_hash", self.result_hash),
            ("receipt_hash", self.receipt_hash),
            ("r8_promotion_event_hash", self.r8_promotion_event_hash),
        ):
            require_sha256(value, f"monitoring target {label}")
        if type(self.upstream_promotions) is not tuple:
            raise TypeError("monitoring target Promotions must be a tuple")
        for selector in self.upstream_promotions:
            if type(selector) is not OptimizationPromotionSelector:
                raise TypeError("monitoring target Promotion selector type is invalid")
            OptimizationPromotionSelector.__post_init__(selector)
        if tuple(item.capability_key for item in self.upstream_promotions) != ("r3", "r4", "r5"):
            raise ValueError("monitoring target requires canonical R3/R4/R5 Promotions")
        require_sha256(self.content_hash, "monitoring target content_hash")
        if self.content_hash != monitoring_target_hash(self):
            raise ValueError("monitoring target content hash mismatch")


def monitoring_target_hash(target: GovernedOptimizationMonitoringTarget) -> str:
    """Hash the complete policy-owned monitoring target graph."""

    return _monitoring_target_hash_values(
        target.optimization_scope_id,
        target.optimization_scope_hash,
        target.result_id,
        target.result_version,
        target.result_hash,
        target.receipt_id,
        target.receipt_version,
        target.receipt_hash,
        target.r8_promotion_event_id,
        target.r8_promotion_event_hash,
        target.upstream_promotions,
    )


def _monitoring_target_hash_values(
    optimization_scope_id: str,
    optimization_scope_hash: str,
    result_id: str,
    result_version: str,
    result_hash: str,
    receipt_id: str,
    receipt_version: str,
    receipt_hash: str,
    r8_promotion_event_id: str,
    r8_promotion_event_hash: str,
    upstream_promotions: tuple[OptimizationPromotionSelector, ...],
) -> str:
    return hash_components(
        "governed-optimization-monitoring-target.v1",
        optimization_scope_id,
        optimization_scope_hash,
        result_id,
        result_version,
        result_hash,
        receipt_id,
        receipt_version,
        receipt_hash,
        r8_promotion_event_id,
        r8_promotion_event_hash,
        *(
            f"{item.capability_key}|{item.decision_id}|{item.decision_content_hash}|{item.attestation_hash}"
            for item in upstream_promotions
        ),
    )


@dataclass(frozen=True)
class GovernedOptimizationMonitoringPolicy:
    """Versioned, content-addressed monitoring and review policy."""

    policy_id: str
    policy_scope_id: str
    policy_version: str
    owner: str
    target: GovernedOptimizationMonitoringTarget
    thresholds: tuple[GovernedOptimizationMonitoringThreshold, ...]
    required_consecutive_breaches: int
    minimum_complete_periods: int
    max_period_lag_seconds: int
    max_evidence_delay_seconds: int
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    calendar_recorded_at: datetime
    calendar_first_period_start_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        owner: str,
        target: GovernedOptimizationMonitoringTarget,
        thresholds: tuple[GovernedOptimizationMonitoringThreshold, ...],
        required_consecutive_breaches: int,
        minimum_complete_periods: int,
        max_period_lag_seconds: int,
        max_evidence_delay_seconds: int,
        calendar: GovernedOptimizationMonitoringCalendar,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> GovernedOptimizationMonitoringPolicy:
        """Seal all thresholds, freshness caps, and exact calendar identity."""

        body_hash = _monitoring_policy_body_hash(
            policy_scope_id=policy_id,
            owner=owner,
            target_hash=target.content_hash,
            thresholds=thresholds,
            required_consecutive_breaches=required_consecutive_breaches,
            minimum_complete_periods=minimum_complete_periods,
            max_period_lag_seconds=max_period_lag_seconds,
            max_evidence_delay_seconds=max_evidence_delay_seconds,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            calendar_hash=calendar.content_hash,
            calendar_recorded_at=calendar.recorded_at,
            calendar_first_period_start_at=calendar.periods[0].start_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
        )
        return cls(
            policy_id=f"r8_monitoring_policy:{body_hash[:24]}",
            policy_scope_id=policy_id,
            policy_version=MONITORING_POLICY_VERSION,
            owner=owner,
            target=target,
            thresholds=thresholds,
            required_consecutive_breaches=required_consecutive_breaches,
            minimum_complete_periods=minimum_complete_periods,
            max_period_lag_seconds=max_period_lag_seconds,
            max_evidence_delay_seconds=max_evidence_delay_seconds,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            calendar_hash=calendar.content_hash,
            calendar_recorded_at=calendar.recorded_at,
            calendar_first_period_start_at=calendar.periods[0].start_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            content_hash=body_hash,
        )

    def __post_init__(self) -> None:
        require_token(self.policy_id, "monitoring policy_id")
        require_token(self.policy_scope_id, "monitoring policy_scope_id")
        require_token(self.policy_version, "monitoring policy_version")
        require_token(self.owner, "monitoring policy owner")
        if self.policy_version != MONITORING_POLICY_VERSION:
            raise ValueError("monitoring policy version is unsupported")
        if self.owner != "research":
            raise ValueError("monitoring policy owner must be research")
        if type(self.target) is not GovernedOptimizationMonitoringTarget:
            raise TypeError("monitoring policy target type is invalid")
        GovernedOptimizationMonitoringTarget.__post_init__(self.target)
        if type(self.thresholds) is not tuple or len(self.thresholds) != len(MonitoringMetricKey):
            raise ValueError("monitoring policy requires the complete metric set")
        for item in self.thresholds:
            if type(item) is not GovernedOptimizationMonitoringThreshold:
                raise TypeError("monitoring policy threshold type is invalid")
            GovernedOptimizationMonitoringThreshold.__post_init__(item)
        keys = tuple(item.metric_key for item in self.thresholds)
        if keys != tuple(MonitoringMetricKey):
            raise ValueError("monitoring policy metric set must be canonical and complete")
        _require_exact_int(
            self.required_consecutive_breaches,
            "required_consecutive_breaches",
            minimum=2,
            maximum=MAX_MONITORING_PERIODS,
        )
        _require_exact_int(
            self.minimum_complete_periods,
            "minimum_complete_periods",
            minimum=self.required_consecutive_breaches,
            maximum=MAX_MONITORING_PERIODS,
        )
        _require_exact_int(
            self.max_period_lag_seconds,
            "max_period_lag_seconds",
            minimum=1,
            maximum=MAX_POLICY_SECONDS,
        )
        _require_exact_int(
            self.max_evidence_delay_seconds,
            "max_evidence_delay_seconds",
            minimum=0,
            maximum=MAX_POLICY_SECONDS,
        )
        require_token(self.calendar_id, "monitoring policy calendar_id")
        require_token(self.calendar_version, "monitoring policy calendar_version")
        require_sha256(self.calendar_hash, "monitoring policy calendar_hash")
        require_aware(self.calendar_recorded_at, "monitoring policy calendar_recorded_at")
        require_aware(
            self.calendar_first_period_start_at,
            "monitoring policy calendar_first_period_start_at",
        )
        require_aware(self.recorded_at, "monitoring policy recorded_at")
        require_aware(self.valid_until, "monitoring policy valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("monitoring policy validity window is invalid")
        if not (
            self.calendar_recorded_at <= self.recorded_at <= self.calendar_first_period_start_at
        ):
            raise ValueError("monitoring policy/calendar recording order is invalid")
        expected_hash = _monitoring_policy_body_hash(
            policy_scope_id=self.policy_scope_id,
            owner=self.owner,
            target_hash=self.target.content_hash,
            thresholds=self.thresholds,
            required_consecutive_breaches=self.required_consecutive_breaches,
            minimum_complete_periods=self.minimum_complete_periods,
            max_period_lag_seconds=self.max_period_lag_seconds,
            max_evidence_delay_seconds=self.max_evidence_delay_seconds,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            calendar_recorded_at=self.calendar_recorded_at,
            calendar_first_period_start_at=self.calendar_first_period_start_at,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        )
        require_sha256(self.content_hash, "monitoring policy content_hash")
        if self.content_hash != expected_hash:
            raise ValueError("monitoring policy content hash mismatch")
        if self.policy_id != f"r8_monitoring_policy:{expected_hash[:24]}":
            raise ValueError("monitoring policy identity is not content-addressed")


def _monitoring_policy_body_hash(
    *,
    policy_scope_id: str,
    owner: str,
    target_hash: str,
    thresholds: tuple[GovernedOptimizationMonitoringThreshold, ...],
    required_consecutive_breaches: int,
    minimum_complete_periods: int,
    max_period_lag_seconds: int,
    max_evidence_delay_seconds: int,
    calendar_id: str,
    calendar_version: str,
    calendar_hash: str,
    calendar_recorded_at: datetime,
    calendar_first_period_start_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> str:
    return hash_components(
        MONITORING_POLICY_VERSION,
        policy_scope_id,
        owner,
        target_hash,
        *(item.content_hash for item in thresholds),
        str(required_consecutive_breaches),
        str(minimum_complete_periods),
        str(max_period_lag_seconds),
        str(max_evidence_delay_seconds),
        calendar_id,
        calendar_version,
        calendar_hash,
        utc_text(calendar_recorded_at),
        utc_text(calendar_first_period_start_at),
        utc_text(recorded_at),
        utc_text(valid_until),
    )


@dataclass(frozen=True)
class ActiveGovernedOptimizationResultEvidence:
    """Exact result plus full lifecycle proving current Promotion state."""

    evidence_version: str
    result: GovernedOptimizationResearchResult
    lifecycle_events: tuple[OptimizationResearchLifecycleEvent, ...]
    promotion_event_id: str
    promotion_event_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result: GovernedOptimizationResearchResult,
        lifecycle_events: tuple[OptimizationResearchLifecycleEvent, ...],
    ) -> ActiveGovernedOptimizationResultEvidence:
        """Seal a fully replayed active lifecycle projection."""

        if not lifecycle_events:
            raise ValueError("active result evidence requires lifecycle events")
        promotion = lifecycle_events[-1]
        return cls(
            evidence_version=ACTIVE_EVIDENCE_VERSION,
            result=result,
            lifecycle_events=lifecycle_events,
            promotion_event_id=promotion.event_id,
            promotion_event_hash=promotion.content_hash,
            content_hash=_active_result_evidence_hash_values(
                result,
                lifecycle_events,
                promotion.event_id,
                promotion.content_hash,
            ),
        )

    def __post_init__(self) -> None:
        if self.evidence_version != ACTIVE_EVIDENCE_VERSION:
            raise ValueError("active result evidence version is unsupported")
        if type(self.result) is not GovernedOptimizationResearchResult:
            raise TypeError("active result type is invalid")
        GovernedOptimizationResearchResult.__post_init__(self.result)
        if self.result.status is not GovernedOptimizationResultStatus.COMPLETED:
            raise ValueError("only a completed optimization result can be active")
        if type(self.lifecycle_events) is not tuple:
            raise TypeError("active lifecycle events must be a tuple")
        for event in self.lifecycle_events:
            if type(event) is not OptimizationResearchLifecycleEvent:
                raise TypeError("active lifecycle event type is invalid")
            OptimizationResearchLifecycleEvent.__post_init__(event)
        if (
            derive_optimization_lifecycle_state(self.lifecycle_events)
            is not OptimizationLifecycleState.PROMOTION_ATTESTED
        ):
            raise ValueError("optimization result is not currently promoted")
        promotion = self.lifecycle_events[-1]
        if (
            promotion.event_type is not OptimizationLifecycleEventType.PROMOTION_ATTESTED
            or promotion.promotion_attestation is None
            or promotion.result_id != self.result.result_id
            or promotion.result_hash != self.result.content_hash
            or promotion.event_id != self.promotion_event_id
            or promotion.content_hash != self.promotion_event_hash
        ):
            raise ValueError("active result Promotion identity mismatch")
        require_sha256(self.promotion_event_hash, "active Promotion event hash")
        require_sha256(self.content_hash, "active result evidence content_hash")
        if self.content_hash != active_result_evidence_hash(self):
            raise ValueError("active result evidence content hash mismatch")


def active_result_evidence_hash(evidence: ActiveGovernedOptimizationResultEvidence) -> str:
    """Hash the result and complete lifecycle projection."""

    return _active_result_evidence_hash_values(
        evidence.result,
        evidence.lifecycle_events,
        evidence.promotion_event_id,
        evidence.promotion_event_hash,
    )


def _active_result_evidence_hash_values(
    result: GovernedOptimizationResearchResult,
    lifecycle_events: tuple[OptimizationResearchLifecycleEvent, ...],
    promotion_event_id: str,
    promotion_event_hash: str,
) -> str:
    return hash_components(
        ACTIVE_EVIDENCE_VERSION,
        result.result_id,
        result.result_version,
        result.content_hash,
        *(f"{item.event_id}|{item.content_hash}" for item in lifecycle_events),
        promotion_event_id,
        promotion_event_hash,
    )


@dataclass(frozen=True)
class OptimizationMonitoringSourceEvidence:
    """Exact Portfolio or Broker feedback seal for one period."""

    owner: MonitoringSourceOwner
    evidence_id: str
    evidence_version: str
    result_id: str
    result_hash: str
    receipt_id: str
    receipt_hash: str
    period_id: str
    metric_payload: tuple[OptimizationMonitoringOwnerMetricPayload, ...]
    observed_at: datetime
    available_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        owner: MonitoringSourceOwner,
        evidence_id: str,
        evidence_version: str,
        result_id: str,
        result_hash: str,
        receipt_id: str,
        receipt_hash: str,
        period_id: str,
        metric_payload: tuple[OptimizationMonitoringOwnerMetricPayload, ...],
        observed_at: datetime,
        available_at: datetime,
    ) -> OptimizationMonitoringSourceEvidence:
        """Seal exact owner evidence without deriving synthetic feedback."""

        return cls(
            owner=owner,
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            result_id=result_id,
            result_hash=result_hash,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            period_id=period_id,
            metric_payload=metric_payload,
            observed_at=observed_at,
            available_at=available_at,
            content_hash=_source_evidence_hash_values(
                owner,
                evidence_id,
                evidence_version,
                result_id,
                result_hash,
                receipt_id,
                receipt_hash,
                period_id,
                metric_payload,
                observed_at,
                available_at,
            ),
        )

    def __post_init__(self) -> None:
        if type(self.owner) is not MonitoringSourceOwner:
            raise TypeError("monitoring source owner is invalid")
        for label, value in (
            ("evidence_id", self.evidence_id),
            ("evidence_version", self.evidence_version),
            ("result_id", self.result_id),
            ("receipt_id", self.receipt_id),
            ("period_id", self.period_id),
        ):
            require_token(value, f"monitoring source {label}")
        require_sha256(self.result_hash, "monitoring source result_hash")
        require_sha256(self.receipt_hash, "monitoring source receipt_hash")
        if type(self.metric_payload) is not tuple:
            raise TypeError("monitoring source metric payload must be a tuple")
        expected_keys = tuple(
            key for key in MonitoringMetricKey if _METRIC_SEMANTICS[key][2] is self.owner
        )
        for item in self.metric_payload:
            if type(item) is not OptimizationMonitoringOwnerMetricPayload:
                raise TypeError("monitoring source metric payload type is invalid")
            OptimizationMonitoringOwnerMetricPayload.__post_init__(item)
        if tuple(item.metric_key for item in self.metric_payload) != expected_keys:
            raise ValueError("monitoring source metric payload is not canonical and complete")
        require_aware(self.observed_at, "monitoring source observed_at")
        require_aware(self.available_at, "monitoring source available_at")
        if self.available_at < self.observed_at:
            raise ValueError("monitoring source cannot be available before observation")
        require_sha256(self.content_hash, "monitoring source content_hash")
        if self.content_hash != source_evidence_hash(self):
            raise ValueError("monitoring source content hash mismatch")


def source_evidence_hash(evidence: OptimizationMonitoringSourceEvidence) -> str:
    """Hash every owner feedback identity and clock."""

    return _source_evidence_hash_values(
        evidence.owner,
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.result_id,
        evidence.result_hash,
        evidence.receipt_id,
        evidence.receipt_hash,
        evidence.period_id,
        evidence.metric_payload,
        evidence.observed_at,
        evidence.available_at,
    )


def _source_evidence_hash_values(
    owner: MonitoringSourceOwner,
    evidence_id: str,
    evidence_version: str,
    result_id: str,
    result_hash: str,
    receipt_id: str,
    receipt_hash: str,
    period_id: str,
    metric_payload: tuple[OptimizationMonitoringOwnerMetricPayload, ...],
    observed_at: datetime,
    available_at: datetime,
) -> str:
    return hash_components(
        "governed-optimization-monitoring-source.v1",
        owner.value,
        evidence_id,
        evidence_version,
        result_id,
        result_hash,
        receipt_id,
        receipt_hash,
        period_id,
        *(
            f"{item.metric_key.value}|{item.unit.value}|{decimal_text(item.value)}|"
            f"{item.evidence_namespace}"
            for item in metric_payload
        ),
        utc_text(observed_at),
        utc_text(available_at),
    )


@dataclass(frozen=True)
class OptimizationMonitoringMetricObservation:
    """Typed raw value bound to exact owner feedback and namespace."""

    metric_key: MonitoringMetricKey
    unit: MonitoringMetricUnit
    value: Decimal
    source_owner: MonitoringSourceOwner
    source_evidence_id: str
    source_evidence_hash: str
    evidence_namespace: str
    observed_at: datetime
    available_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        metric_key: MonitoringMetricKey,
        value: Decimal,
        source_evidence: OptimizationMonitoringSourceEvidence,
        evidence_namespace: str,
    ) -> OptimizationMonitoringMetricObservation:
        """Create one raw fact using only an exact owner evidence seal."""

        unit, _, source_owner, _, _ = _METRIC_SEMANTICS[metric_key]
        payload = next(
            (item for item in source_evidence.metric_payload if item.metric_key is metric_key),
            None,
        )
        if (
            payload is None
            or payload.value != value
            or payload.evidence_namespace != evidence_namespace
        ):
            raise ValueError("monitoring observation does not match owner metric payload")
        return cls(
            metric_key=metric_key,
            unit=unit,
            value=value,
            source_owner=source_owner,
            source_evidence_id=source_evidence.evidence_id,
            source_evidence_hash=source_evidence.content_hash,
            evidence_namespace=evidence_namespace,
            observed_at=source_evidence.observed_at,
            available_at=source_evidence.available_at,
            content_hash=_metric_observation_hash_values(
                metric_key,
                unit,
                value,
                source_owner,
                source_evidence.evidence_id,
                source_evidence.content_hash,
                evidence_namespace,
                source_evidence.observed_at,
                source_evidence.available_at,
            ),
        )

    def __post_init__(self) -> None:
        if type(self.metric_key) is not MonitoringMetricKey:
            raise TypeError("monitoring observation metric key is invalid")
        expected_unit, _, expected_owner, _, _ = _METRIC_SEMANTICS[self.metric_key]
        if self.unit is not expected_unit or self.source_owner is not expected_owner:
            raise ValueError("monitoring observation metric semantics mismatch")
        _require_metric_value(self.metric_key, self.value)
        require_token(self.source_evidence_id, "monitoring observation source_evidence_id")
        require_sha256(self.source_evidence_hash, "monitoring observation source_evidence_hash")
        require_token(self.evidence_namespace, "monitoring observation evidence_namespace")
        require_aware(self.observed_at, "monitoring observation observed_at")
        require_aware(self.available_at, "monitoring observation available_at")
        if self.available_at < self.observed_at:
            raise ValueError("monitoring observation availability precedes observation")
        require_sha256(self.content_hash, "monitoring observation content_hash")
        if self.content_hash != metric_observation_hash(self):
            raise ValueError("monitoring observation content hash mismatch")


def metric_observation_hash(observation: OptimizationMonitoringMetricObservation) -> str:
    """Hash a typed raw metric observation."""

    return _metric_observation_hash_values(
        observation.metric_key,
        observation.unit,
        observation.value,
        observation.source_owner,
        observation.source_evidence_id,
        observation.source_evidence_hash,
        observation.evidence_namespace,
        observation.observed_at,
        observation.available_at,
    )


def _metric_observation_hash_values(
    metric_key: MonitoringMetricKey,
    unit: MonitoringMetricUnit,
    value: Decimal,
    source_owner: MonitoringSourceOwner,
    source_evidence_id: str,
    source_evidence_hash: str,
    evidence_namespace: str,
    observed_at: datetime,
    available_at: datetime,
) -> str:
    return hash_components(
        "governed-optimization-monitoring-metric.v1",
        metric_key.value,
        unit.value,
        decimal_text(value),
        source_owner.value,
        source_evidence_id,
        source_evidence_hash,
        evidence_namespace,
        utc_text(observed_at),
        utc_text(available_at),
    )


@dataclass(frozen=True)
class OptimizationMonitoringPeriodObservation:
    """Complete eleven-metric raw observation for one calendar period."""

    observation_version: str
    period_id: str
    metrics: tuple[OptimizationMonitoringMetricObservation, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        period_id: str,
        metrics: tuple[OptimizationMonitoringMetricObservation, ...],
    ) -> OptimizationMonitoringPeriodObservation:
        """Canonicalize metric order while preserving every raw seal."""

        ordered = tuple(sorted(metrics, key=lambda item: _enum_index(item.metric_key)))
        return cls(
            observation_version=MONITORING_OBSERVATION_VERSION,
            period_id=period_id,
            metrics=ordered,
            content_hash=_period_observation_hash_values(period_id, ordered),
        )

    def __post_init__(self) -> None:
        if self.observation_version != MONITORING_OBSERVATION_VERSION:
            raise ValueError("monitoring observation version is unsupported")
        require_token(self.period_id, "monitoring observation period_id")
        if type(self.metrics) is not tuple or len(self.metrics) != len(MonitoringMetricKey):
            raise ValueError("monitoring observation metric set is incomplete")
        for metric in self.metrics:
            if type(metric) is not OptimizationMonitoringMetricObservation:
                raise TypeError("monitoring metric observation type is invalid")
            OptimizationMonitoringMetricObservation.__post_init__(metric)
        if tuple(item.metric_key for item in self.metrics) != tuple(MonitoringMetricKey):
            raise ValueError("monitoring observation metric set must be canonical and complete")
        require_sha256(self.content_hash, "monitoring period observation content_hash")
        if self.content_hash != period_observation_hash(self):
            raise ValueError("monitoring period observation content hash mismatch")


def period_observation_hash(observation: OptimizationMonitoringPeriodObservation) -> str:
    """Hash one complete period observation."""

    return _period_observation_hash_values(observation.period_id, observation.metrics)


def _period_observation_hash_values(
    period_id: str,
    metrics: tuple[OptimizationMonitoringMetricObservation, ...],
) -> str:
    return hash_components(
        MONITORING_OBSERVATION_VERSION,
        period_id,
        *(item.content_hash for item in metrics),
    )
