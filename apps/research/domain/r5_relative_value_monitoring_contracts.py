"""Pure contracts for R5 post-promotion monitoring Phase A."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from apps.fixed_income.domain.evidence import canonical_hash, decimal_text
from apps.research.domain.r5_relative_value_monitoring_owners import (
    R5MonitoringOwnerRef,
    R5MonitoringOwnerRole,
)

MAX_MONITORING_PERIODS = 64
MAX_POLICY_SECONDS = 366 * 24 * 60 * 60
MONITORING_POLICY_VERSION = "r5-post-promotion-monitoring-policy.v1"


def _require_token(value: object, label: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be an exact bounded token")
    return value


def _require_hash(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


def _require_int(
    value: object,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside its governed integer range")
    return value


def _require_decimal(value: object, label: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{label} must be an exact finite Decimal")
    return value


class R5MonitoringMetricKey(StrEnum):
    """Canonical R5 monitoring measures; no caller-defined aliases exist."""

    COVERAGE_RATIO = "coverage_ratio"
    EXCESS_NET_RETURN = "excess_net_return"
    DRAWDOWN_INCREASE = "drawdown_increase"
    TOTAL_TARGET_COST = "total_target_cost"
    LIQUIDITY_BREACH = "liquidity_breach"
    PEAK_CAPACITY_UTILIZATION = "peak_capacity_utilization"
    REALIZED_CREDIT_LOSS = "realized_credit_loss"


class R5MonitoringMetricUnit(StrEnum):
    """Exact unit semantics for each canonical measure."""

    RATIO = "ratio"
    RETURN_RATE = "return_rate"
    COST_RATE = "cost_rate"
    BINARY = "binary"
    LOSS_RATE = "loss_rate"


class R5MonitoringThresholdDirection(StrEnum):
    """Healthy-side comparison direction."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


_METRIC_UNIT: dict[R5MonitoringMetricKey, R5MonitoringMetricUnit] = {
    R5MonitoringMetricKey.COVERAGE_RATIO: R5MonitoringMetricUnit.RATIO,
    R5MonitoringMetricKey.EXCESS_NET_RETURN: R5MonitoringMetricUnit.RETURN_RATE,
    R5MonitoringMetricKey.DRAWDOWN_INCREASE: R5MonitoringMetricUnit.RETURN_RATE,
    R5MonitoringMetricKey.TOTAL_TARGET_COST: R5MonitoringMetricUnit.COST_RATE,
    R5MonitoringMetricKey.LIQUIDITY_BREACH: R5MonitoringMetricUnit.RATIO,
    R5MonitoringMetricKey.PEAK_CAPACITY_UTILIZATION: R5MonitoringMetricUnit.RATIO,
    R5MonitoringMetricKey.REALIZED_CREDIT_LOSS: R5MonitoringMetricUnit.LOSS_RATE,
}
_METRIC_DIRECTION: dict[R5MonitoringMetricKey, R5MonitoringThresholdDirection] = {
    key: (
        R5MonitoringThresholdDirection.AT_LEAST
        if key
        in {
            R5MonitoringMetricKey.COVERAGE_RATIO,
            R5MonitoringMetricKey.EXCESS_NET_RETURN,
        }
        else R5MonitoringThresholdDirection.AT_MOST
    )
    for key in R5MonitoringMetricKey
}


def _validate_metric_value(key: R5MonitoringMetricKey, value: object, label: str) -> Decimal:
    decimal = _require_decimal(value, label)
    if key in {
        R5MonitoringMetricKey.COVERAGE_RATIO,
        R5MonitoringMetricKey.TOTAL_TARGET_COST,
        R5MonitoringMetricKey.LIQUIDITY_BREACH,
        R5MonitoringMetricKey.PEAK_CAPACITY_UTILIZATION,
        R5MonitoringMetricKey.REALIZED_CREDIT_LOSS,
    } and not Decimal("0") <= decimal <= Decimal("1"):
        raise ValueError(f"{label} must be within [0, 1]")
    if key is R5MonitoringMetricKey.DRAWDOWN_INCREASE and not (
        Decimal("-1") <= decimal <= Decimal("1")
    ):
        raise ValueError(f"{label} must be within [-1, 1]")
    if key is R5MonitoringMetricKey.EXCESS_NET_RETURN and not (
        Decimal("-2") <= decimal <= Decimal("2")
    ):
        raise ValueError(f"{label} must be within [-2, 2]")
    return decimal


@dataclass(frozen=True)
class R5MonitoringPeriodEntry:
    """One canonical, non-overlapping monitoring period member."""

    period_id: str
    period_start: datetime
    period_end: datetime

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        period_start: datetime,
        period_end: datetime,
    ) -> R5MonitoringPeriodEntry:
        """Derive the member identity from its exact calendar and window."""

        _require_token(calendar_id, "calendar_id")
        _require_token(calendar_version, "calendar_version")
        _require_aware(period_start, "period_start")
        _require_aware(period_end, "period_end")
        if period_start >= period_end:
            raise ValueError("R5 monitoring period must be non-empty")
        digest = canonical_hash(
            {
                "schema": "research-r5-monitoring-period.v1",
                "calendar_id": calendar_id,
                "calendar_version": calendar_version,
                "period_start": period_start,
                "period_end": period_end,
            }
        )
        return cls(digest, period_start, period_end)

    def __post_init__(self) -> None:
        _require_hash(self.period_id, "period_id")
        _require_aware(self.period_start, "period_start")
        _require_aware(self.period_end, "period_end")
        if self.period_start >= self.period_end:
            raise ValueError("R5 monitoring period must be non-empty")


@dataclass(frozen=True)
class R5MonitoringCalendar:
    """Content-addressed owner calendar with complete contiguous members."""

    owner: R5MonitoringOwnerRef
    entries: tuple[R5MonitoringPeriodEntry, ...]
    recorded_at: datetime
    valid_until: datetime
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        owner: R5MonitoringOwnerRef,
        entries: tuple[R5MonitoringPeriodEntry, ...],
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R5MonitoringCalendar:
        """Create a canonical calendar without filling missing periods."""

        return cls(owner, entries, recorded_at, valid_until)

    def __post_init__(self) -> None:
        if (
            type(self.owner) is not R5MonitoringOwnerRef
            or self.owner.role is not R5MonitoringOwnerRole.CALENDAR
        ):
            raise ValueError("R5 monitoring calendar must be Research-owned")
        self.owner.__post_init__()
        if type(self.entries) is not tuple or not 1 <= len(self.entries) <= MAX_MONITORING_PERIODS:
            raise ValueError("R5 monitoring calendar requires a bounded complete tuple")
        for item in self.entries:
            if type(item) is not R5MonitoringPeriodEntry:
                raise TypeError("R5 monitoring calendar member type is invalid")
            item.__post_init__()
            expected = R5MonitoringPeriodEntry.create(
                calendar_id=self.owner.owner_id,
                calendar_version=self.owner.owner_version,
                period_start=item.period_start,
                period_end=item.period_end,
            )
            if item != expected:
                raise ValueError("R5 monitoring calendar member identity differs")
        if tuple(sorted(self.entries, key=lambda item: item.period_start)) != self.entries:
            raise ValueError("R5 monitoring calendar order is non-canonical")
        if len({item.period_id for item in self.entries}) != len(self.entries):
            raise ValueError("R5 monitoring calendar member IDs must be unique")
        if any(
            left.period_end != right.period_start
            for left, right in zip(self.entries, self.entries[1:], strict=False)
        ):
            raise ValueError("R5 monitoring calendar members must be contiguous")
        _require_aware(self.recorded_at, "calendar recorded_at")
        _require_aware(self.valid_until, "calendar valid_until")
        if not self.recorded_at <= self.entries[0].period_start:
            raise ValueError("R5 monitoring calendar was not known before its first member")
        if self.owner.recorded_at != self.recorded_at:
            raise ValueError("R5 monitoring calendar owner clock differs")
        if self.valid_until <= self.entries[-1].period_end:
            raise ValueError(
                "R5 monitoring calendar validity must cover evaluation after period end"
            )
        if self.valid_until > self.owner.valid_until:
            raise ValueError("R5 monitoring calendar exceeds its owner validity")
        object.__setattr__(self, "content_hash", monitoring_calendar_hash(self))

    def validated_copy(self) -> R5MonitoringCalendar:
        """Deeply rebuild the complete calendar."""

        return R5MonitoringCalendar.create(
            owner=self.owner.validated_copy(),
            entries=tuple(
                R5MonitoringPeriodEntry(item.period_id, item.period_start, item.period_end)
                for item in self.entries
            ),
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        )


def monitoring_calendar_hash(calendar: R5MonitoringCalendar) -> str:
    """Recompute the exact calendar seal."""

    return canonical_hash(
        {
            "schema": "research-r5-monitoring-calendar.v1",
            "owner": calendar.owner,
            "entries": tuple(
                (item.period_id, item.period_start, item.period_end) for item in calendar.entries
            ),
            "recorded_at": calendar.recorded_at,
            "valid_until": calendar.valid_until,
        }
    )


@dataclass(frozen=True)
class R5MonitoringActiveLifecycle:
    """Exact active R5 decision and lifecycle projection."""

    scope_id: str
    scope_hash: str
    decision_id: str
    decision_version: str
    decision_hash: str
    trial_id: str
    trial_hash: str
    fixed_income_owner_seal_hashes: tuple[str, ...]
    stream_id: str
    latest_event_id: str
    latest_event_hash: str
    promoted_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        scope_hash: str,
        decision_id: str,
        decision_version: str,
        decision_hash: str,
        trial_id: str,
        trial_hash: str,
        fixed_income_owner_seal_hashes: tuple[str, ...],
        stream_id: str,
        latest_event_id: str,
        latest_event_hash: str,
        promoted_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R5MonitoringActiveLifecycle:
        """Create one sealed lifecycle projection from trusted owner values."""

        return cls(
            scope_id,
            scope_hash,
            decision_id,
            decision_version,
            decision_hash,
            trial_id,
            trial_hash,
            fixed_income_owner_seal_hashes,
            stream_id,
            latest_event_id,
            latest_event_hash,
            promoted_at,
            recorded_at,
            valid_until,
        )

    def __post_init__(self) -> None:
        for label, value in (
            ("scope_id", self.scope_id),
            ("decision_id", self.decision_id),
            ("decision_version", self.decision_version),
            ("trial_id", self.trial_id),
            ("stream_id", self.stream_id),
            ("latest_event_id", self.latest_event_id),
        ):
            _require_token(value, f"active lifecycle {label}")
        for label, value in (
            ("scope_hash", self.scope_hash),
            ("decision_hash", self.decision_hash),
            ("trial_hash", self.trial_hash),
            ("latest_event_hash", self.latest_event_hash),
        ):
            _require_hash(value, f"active lifecycle {label}")
        if (
            type(self.fixed_income_owner_seal_hashes) is not tuple
            or not self.fixed_income_owner_seal_hashes
        ):
            raise ValueError("active lifecycle requires fixed-income owner seals")
        for digest in self.fixed_income_owner_seal_hashes:
            _require_hash(digest, "active lifecycle fixed-income owner seal")
        if self.fixed_income_owner_seal_hashes != tuple(
            sorted(set(self.fixed_income_owner_seal_hashes))
        ):
            raise ValueError("active lifecycle fixed-income seals must be canonical")
        for label, clock_value in (
            ("promoted_at", self.promoted_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, f"active lifecycle {label}")
        if not self.promoted_at <= self.recorded_at < self.valid_until:
            raise ValueError("active lifecycle clocks are invalid")
        object.__setattr__(self, "content_hash", active_lifecycle_hash(self))

    def validated_copy(self) -> R5MonitoringActiveLifecycle:
        """Rebuild the exact active projection."""

        return R5MonitoringActiveLifecycle.create(
            scope_id=self.scope_id,
            scope_hash=self.scope_hash,
            decision_id=self.decision_id,
            decision_version=self.decision_version,
            decision_hash=self.decision_hash,
            trial_id=self.trial_id,
            trial_hash=self.trial_hash,
            fixed_income_owner_seal_hashes=tuple(self.fixed_income_owner_seal_hashes),
            stream_id=self.stream_id,
            latest_event_id=self.latest_event_id,
            latest_event_hash=self.latest_event_hash,
            promoted_at=self.promoted_at,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        )


def active_lifecycle_hash(value: R5MonitoringActiveLifecycle) -> str:
    """Recompute the active lifecycle projection seal."""

    return canonical_hash(
        {
            "schema": "research-r5-monitoring-active-lifecycle.v1",
            "scope": (value.scope_id, value.scope_hash),
            "decision": (value.decision_id, value.decision_version, value.decision_hash),
            "trial": (value.trial_id, value.trial_hash),
            "fixed_income_owner_seals": value.fixed_income_owner_seal_hashes,
            "stream": (value.stream_id, value.latest_event_id, value.latest_event_hash),
            "clocks": (value.promoted_at, value.recorded_at, value.valid_until),
        }
    )


@dataclass(frozen=True)
class R5MonitoringFixedIncomeEvidence:
    """Exact fixed-income result and owner-record projection."""

    result_id: str
    result_version: str
    result_hash: str
    owner_seal_id: str
    owner_seal_version: str
    owner_seal_hash: str
    recorded_at: datetime
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_version: str,
        result_hash: str,
        owner_seal_id: str,
        owner_seal_version: str,
        owner_seal_hash: str,
        recorded_at: datetime,
    ) -> R5MonitoringFixedIncomeEvidence:
        """Create one fixed-income evidence seal."""

        return cls(
            result_id,
            result_version,
            result_hash,
            owner_seal_id,
            owner_seal_version,
            owner_seal_hash,
            recorded_at,
        )

    def __post_init__(self) -> None:
        for label, value in (
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("owner_seal_id", self.owner_seal_id),
            ("owner_seal_version", self.owner_seal_version),
        ):
            _require_token(value, f"fixed-income evidence {label}")
        _require_hash(self.result_hash, "fixed-income evidence result_hash")
        _require_hash(self.owner_seal_hash, "fixed-income evidence owner_seal_hash")
        _require_aware(self.recorded_at, "fixed-income evidence recorded_at")
        object.__setattr__(self, "content_hash", fixed_income_evidence_hash(self))

    def validated_copy(self) -> R5MonitoringFixedIncomeEvidence:
        """Rebuild the fixed-income projection."""

        return R5MonitoringFixedIncomeEvidence.create(
            result_id=self.result_id,
            result_version=self.result_version,
            result_hash=self.result_hash,
            owner_seal_id=self.owner_seal_id,
            owner_seal_version=self.owner_seal_version,
            owner_seal_hash=self.owner_seal_hash,
            recorded_at=self.recorded_at,
        )


def fixed_income_evidence_hash(value: R5MonitoringFixedIncomeEvidence) -> str:
    """Recompute the fixed-income projection seal."""

    return canonical_hash(
        {
            "schema": "research-r5-monitoring-fixed-income-evidence.v1",
            "result": (value.result_id, value.result_version, value.result_hash),
            "owner_seal": (
                value.owner_seal_id,
                value.owner_seal_version,
                value.owner_seal_hash,
            ),
            "recorded_at": value.recorded_at,
        }
    )


@dataclass(frozen=True)
class R5MonitoringTarget:
    """Policy-owned exact active result and supporting owner graph."""

    active_lifecycle: R5MonitoringActiveLifecycle
    fixed_income: R5MonitoringFixedIncomeEvidence
    benchmark: R5MonitoringOwnerRef
    cost_policy: R5MonitoringOwnerRef
    liquidity_policy: R5MonitoringOwnerRef
    label_baseline: R5MonitoringOwnerRef
    data_schema: R5MonitoringOwnerRef
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        active_lifecycle: R5MonitoringActiveLifecycle,
        fixed_income: R5MonitoringFixedIncomeEvidence,
        benchmark: R5MonitoringOwnerRef,
        cost_policy: R5MonitoringOwnerRef,
        liquidity_policy: R5MonitoringOwnerRef,
        label_baseline: R5MonitoringOwnerRef,
        data_schema: R5MonitoringOwnerRef,
    ) -> R5MonitoringTarget:
        """Bind all exact owner projections into one target."""

        return cls(
            active_lifecycle,
            fixed_income,
            benchmark,
            cost_policy,
            liquidity_policy,
            label_baseline,
            data_schema,
        )

    def __post_init__(self) -> None:
        if type(self.active_lifecycle) is not R5MonitoringActiveLifecycle:
            raise TypeError("monitoring target active lifecycle type is invalid")
        if type(self.fixed_income) is not R5MonitoringFixedIncomeEvidence:
            raise TypeError("monitoring target fixed-income evidence type is invalid")
        self.active_lifecycle.__post_init__()
        self.fixed_income.__post_init__()
        governed_owners = (
            (self.benchmark, R5MonitoringOwnerRole.BENCHMARK),
            (self.cost_policy, R5MonitoringOwnerRole.COST_POLICY),
            (self.liquidity_policy, R5MonitoringOwnerRole.LIQUIDITY_POLICY),
            (self.label_baseline, R5MonitoringOwnerRole.LABEL_BASELINE),
            (self.data_schema, R5MonitoringOwnerRole.DATA_SCHEMA),
        )
        for item, expected_role in governed_owners:
            if type(item) is not R5MonitoringOwnerRef:
                raise TypeError("monitoring target owner ref type is invalid")
            item.__post_init__()
            if item.role is not expected_role:
                raise ValueError("monitoring target owner role differs")
        if (
            self.fixed_income.owner_seal_hash
            not in self.active_lifecycle.fixed_income_owner_seal_hashes
        ):
            raise ValueError("fixed-income owner seal is outside the active decision")
        if self.fixed_income.recorded_at > self.active_lifecycle.promoted_at or any(
            item.recorded_at > self.active_lifecycle.promoted_at
            or item.valid_until <= self.active_lifecycle.promoted_at
            for item, _ in governed_owners
        ):
            raise ValueError("monitoring target was not known before the active decision")
        object.__setattr__(self, "content_hash", monitoring_target_hash(self))

    def validated_copy(self) -> R5MonitoringTarget:
        """Deeply rebuild the exact target graph."""

        return R5MonitoringTarget.create(
            active_lifecycle=self.active_lifecycle.validated_copy(),
            fixed_income=self.fixed_income.validated_copy(),
            benchmark=self.benchmark.validated_copy(),
            cost_policy=self.cost_policy.validated_copy(),
            liquidity_policy=self.liquidity_policy.validated_copy(),
            label_baseline=self.label_baseline.validated_copy(),
            data_schema=self.data_schema.validated_copy(),
        )


def monitoring_target_hash(value: R5MonitoringTarget) -> str:
    """Recompute the complete target graph seal."""

    return canonical_hash(
        {
            "schema": "research-r5-monitoring-target.v1",
            "active_lifecycle_hash": value.active_lifecycle.content_hash,
            "fixed_income_hash": value.fixed_income.content_hash,
            "benchmark": value.benchmark,
            "cost_policy": value.cost_policy,
            "liquidity_policy": value.liquidity_policy,
            "label_baseline": value.label_baseline,
            "data_schema": value.data_schema,
        }
    )


@dataclass(frozen=True)
class R5MonitoringMetric:
    """One typed metric value with canonical unit and domain."""

    metric_key: R5MonitoringMetricKey
    unit: R5MonitoringMetricUnit
    value: Decimal

    @classmethod
    def canonical(
        cls,
        metric_key: R5MonitoringMetricKey,
        value: Decimal,
    ) -> R5MonitoringMetric:
        """Construct a metric with its fixed unit."""

        return cls(metric_key, _METRIC_UNIT[metric_key], value)

    def __post_init__(self) -> None:
        if type(self.metric_key) is not R5MonitoringMetricKey:
            raise TypeError("R5 monitoring metric key is invalid")
        if (
            type(self.unit) is not R5MonitoringMetricUnit
            or self.unit is not _METRIC_UNIT[self.metric_key]
        ):
            raise ValueError("R5 monitoring metric unit is non-canonical")
        _validate_metric_value(self.metric_key, self.value, "monitoring metric value")


@dataclass(frozen=True)
class R5MonitoringThreshold:
    """Pre-registered metric boundary and consecutive-review rule."""

    metric_key: R5MonitoringMetricKey
    unit: R5MonitoringMetricUnit
    direction: R5MonitoringThresholdDirection
    breach_threshold: Decimal
    retirement_review_consecutive_breaches: int

    @classmethod
    def canonical(
        cls,
        *,
        metric_key: R5MonitoringMetricKey,
        breach_threshold: Decimal,
        retirement_review_consecutive_breaches: int,
    ) -> R5MonitoringThreshold:
        """Construct a threshold with fixed unit and direction."""

        return cls(
            metric_key,
            _METRIC_UNIT[metric_key],
            _METRIC_DIRECTION[metric_key],
            breach_threshold,
            retirement_review_consecutive_breaches,
        )

    def __post_init__(self) -> None:
        if type(self.metric_key) is not R5MonitoringMetricKey:
            raise TypeError("R5 monitoring threshold key is invalid")
        if (
            type(self.unit) is not R5MonitoringMetricUnit
            or self.unit is not _METRIC_UNIT[self.metric_key]
        ):
            raise ValueError("R5 monitoring threshold unit is non-canonical")
        if (
            type(self.direction) is not R5MonitoringThresholdDirection
            or self.direction is not _METRIC_DIRECTION[self.metric_key]
        ):
            raise ValueError("R5 monitoring threshold direction is non-canonical")
        _validate_metric_value(
            self.metric_key,
            self.breach_threshold,
            "monitoring breach threshold",
        )
        _require_int(
            self.retirement_review_consecutive_breaches,
            "retirement review consecutive breaches",
            minimum=2,
            maximum=MAX_MONITORING_PERIODS,
        )

    def is_breached(self, value: Decimal) -> bool:
        """Evaluate one value against the exact healthy-side direction."""

        _validate_metric_value(self.metric_key, value, "monitoring value")
        if self.direction is R5MonitoringThresholdDirection.AT_LEAST:
            return value < self.breach_threshold
        return value > self.breach_threshold


@dataclass(frozen=True)
class R5MonitoringPolicy:
    """Pre-registered content-addressed post-promotion policy."""

    policy_id: str
    policy_scope_id: str
    policy_version: str
    target: R5MonitoringTarget
    calendar_owner: R5MonitoringOwnerRef
    calendar_hash: str
    calendar_recorded_at: datetime
    calendar_first_period_start: datetime
    thresholds: tuple[R5MonitoringThreshold, ...]
    minimum_complete_periods: int
    maximum_period_age_seconds: int
    maximum_source_delay_seconds: int
    recorded_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_scope_id: str,
        target: R5MonitoringTarget,
        calendar: R5MonitoringCalendar,
        thresholds: tuple[R5MonitoringThreshold, ...],
        minimum_complete_periods: int,
        maximum_period_age_seconds: int,
        maximum_source_delay_seconds: int,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R5MonitoringPolicy:
        """Create a policy whose identity derives from every governed field."""

        digest = _policy_hash_values(
            policy_scope_id,
            target,
            calendar,
            thresholds,
            minimum_complete_periods,
            maximum_period_age_seconds,
            maximum_source_delay_seconds,
            recorded_at,
            valid_until,
        )
        return cls(
            f"r5-monitoring-policy:{digest[:24]}",
            policy_scope_id,
            MONITORING_POLICY_VERSION,
            target,
            calendar.owner,
            calendar.content_hash,
            calendar.recorded_at,
            calendar.entries[0].period_start,
            thresholds,
            minimum_complete_periods,
            maximum_period_age_seconds,
            maximum_source_delay_seconds,
            recorded_at,
            valid_until,
            digest,
        )

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "monitoring policy_id")
        _require_token(self.policy_scope_id, "monitoring policy_scope_id")
        if self.policy_version != MONITORING_POLICY_VERSION:
            raise ValueError("monitoring policy version is unsupported")
        self.target.__post_init__()
        self.calendar_owner.__post_init__()
        _require_hash(self.calendar_hash, "monitoring policy calendar_hash")
        if type(self.thresholds) is not tuple or len(self.thresholds) != len(R5MonitoringMetricKey):
            raise ValueError("monitoring policy requires all seven thresholds")
        for item in self.thresholds:
            if type(item) is not R5MonitoringThreshold:
                raise TypeError("monitoring policy threshold type is invalid")
            item.__post_init__()
        if tuple(item.metric_key for item in self.thresholds) != tuple(R5MonitoringMetricKey):
            raise ValueError("monitoring policy thresholds are not canonical")
        _require_int(
            self.minimum_complete_periods,
            "minimum complete periods",
            minimum=2,
            maximum=MAX_MONITORING_PERIODS,
        )
        _require_int(
            self.maximum_period_age_seconds,
            "maximum period age",
            minimum=1,
            maximum=MAX_POLICY_SECONDS,
        )
        _require_int(
            self.maximum_source_delay_seconds,
            "maximum source delay",
            minimum=1,
            maximum=MAX_POLICY_SECONDS,
        )
        for label, value in (
            ("calendar_recorded_at", self.calendar_recorded_at),
            ("calendar_first_period_start", self.calendar_first_period_start),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(value, f"monitoring policy {label}")
        if not (
            self.target.fixed_income.recorded_at
            <= self.target.active_lifecycle.promoted_at
            <= self.target.active_lifecycle.recorded_at
            <= self.calendar_recorded_at
            <= self.recorded_at
            <= self.calendar_first_period_start
            < self.valid_until
            <= self.target.active_lifecycle.valid_until
        ):
            raise ValueError("monitoring policy owner clocks are invalid")
        owner_validities = (
            self.calendar_owner.valid_until,
            self.target.benchmark.valid_until,
            self.target.cost_policy.valid_until,
            self.target.liquidity_policy.valid_until,
            self.target.label_baseline.valid_until,
            self.target.data_schema.valid_until,
        )
        if self.calendar_owner.role is not R5MonitoringOwnerRole.CALENDAR or any(
            self.valid_until > owner_valid_until for owner_valid_until in owner_validities
        ):
            raise ValueError("monitoring policy exceeds an exact owner validity")
        _require_hash(self.content_hash, "monitoring policy content_hash")
        expected = monitoring_policy_hash(self)
        if (
            self.content_hash != expected
            or self.policy_id != f"r5-monitoring-policy:{expected[:24]}"
        ):
            raise ValueError("monitoring policy identity or content seal differs")

    def validated_copy(self) -> R5MonitoringPolicy:
        """Deeply rebuild and revalidate the policy graph."""

        rebuilt = R5MonitoringPolicy(
            self.policy_id,
            self.policy_scope_id,
            self.policy_version,
            self.target.validated_copy(),
            self.calendar_owner.validated_copy(),
            self.calendar_hash,
            self.calendar_recorded_at,
            self.calendar_first_period_start,
            tuple(
                R5MonitoringThreshold(
                    item.metric_key,
                    item.unit,
                    item.direction,
                    item.breach_threshold,
                    item.retirement_review_consecutive_breaches,
                )
                for item in self.thresholds
            ),
            self.minimum_complete_periods,
            self.maximum_period_age_seconds,
            self.maximum_source_delay_seconds,
            self.recorded_at,
            self.valid_until,
            self.content_hash,
        )
        if rebuilt != self:
            raise ValueError("monitoring policy validated copy differs")
        return rebuilt


def _policy_hash_values(
    policy_scope_id: str,
    target: R5MonitoringTarget,
    calendar: R5MonitoringCalendar,
    thresholds: tuple[R5MonitoringThreshold, ...],
    minimum_complete_periods: int,
    maximum_period_age_seconds: int,
    maximum_source_delay_seconds: int,
    recorded_at: datetime,
    valid_until: datetime,
) -> str:
    return canonical_hash(
        {
            "schema": MONITORING_POLICY_VERSION,
            "policy_scope_id": policy_scope_id,
            "target_hash": target.content_hash,
            "calendar": (
                calendar.owner,
                calendar.content_hash,
                calendar.recorded_at,
                calendar.entries[0].period_start,
            ),
            "thresholds": tuple(
                (
                    item.metric_key,
                    item.unit,
                    item.direction,
                    decimal_text(item.breach_threshold),
                    item.retirement_review_consecutive_breaches,
                )
                for item in thresholds
            ),
            "minimum_complete_periods": minimum_complete_periods,
            "maximum_period_age_seconds": maximum_period_age_seconds,
            "maximum_source_delay_seconds": maximum_source_delay_seconds,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
        }
    )


def monitoring_policy_hash(policy: R5MonitoringPolicy) -> str:
    """Recompute the complete policy seal without trusting its ID."""

    return canonical_hash(
        {
            "schema": MONITORING_POLICY_VERSION,
            "policy_scope_id": policy.policy_scope_id,
            "target_hash": policy.target.content_hash,
            "calendar": (
                policy.calendar_owner,
                policy.calendar_hash,
                policy.calendar_recorded_at,
                policy.calendar_first_period_start,
            ),
            "thresholds": tuple(
                (
                    item.metric_key,
                    item.unit,
                    item.direction,
                    decimal_text(item.breach_threshold),
                    item.retirement_review_consecutive_breaches,
                )
                for item in policy.thresholds
            ),
            "minimum_complete_periods": policy.minimum_complete_periods,
            "maximum_period_age_seconds": policy.maximum_period_age_seconds,
            "maximum_source_delay_seconds": policy.maximum_source_delay_seconds,
            "recorded_at": policy.recorded_at,
            "valid_until": policy.valid_until,
        }
    )


__all__ = [
    "R5MonitoringActiveLifecycle",
    "R5MonitoringCalendar",
    "R5MonitoringFixedIncomeEvidence",
    "R5MonitoringMetric",
    "R5MonitoringMetricKey",
    "R5MonitoringMetricUnit",
    "R5MonitoringOwnerRef",
    "R5MonitoringOwnerRole",
    "R5MonitoringPeriodEntry",
    "R5MonitoringPolicy",
    "R5MonitoringTarget",
    "R5MonitoringThreshold",
    "R5MonitoringThresholdDirection",
]
