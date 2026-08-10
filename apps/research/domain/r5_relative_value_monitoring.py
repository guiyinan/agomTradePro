"""Pure evaluation rules for R5 post-promotion monitoring Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringMetric,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
    R5MonitoringPolicy,
    R5MonitoringTarget,
    R5MonitoringThreshold,
    R5MonitoringThresholdDirection,
    _require_aware,
    _require_hash,
    _require_int,
    _require_token,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)

MONITORING_ASSESSMENT_VERSION = "r5-post-promotion-monitoring-assessment.v1"


class R5MonitoringAssessmentStatus(StrEnum):
    """Four explicit monitoring outcomes."""

    BLOCKED = "blocked"
    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"


class R5MonitoringBlockerCode(StrEnum):
    """Stable fail-closed reasons for incomplete or non-exact owner graphs."""

    ACTIVE_LIFECYCLE_UNAVAILABLE = "active_lifecycle_unavailable"
    ACTIVE_LIFECYCLE_SUBSTITUTED = "active_lifecycle_substituted"
    ACTIVE_LIFECYCLE_INACTIVE = "active_lifecycle_inactive"
    FIXED_INCOME_UNAVAILABLE = "fixed_income_unavailable"
    FIXED_INCOME_SUBSTITUTED = "fixed_income_substituted"
    POLICY_UNAVAILABLE = "policy_unavailable"
    POLICY_SUBSTITUTED = "policy_substituted"
    POLICY_INACTIVE = "policy_inactive"
    CALENDAR_UNAVAILABLE = "calendar_unavailable"
    CALENDAR_SUBSTITUTED = "calendar_substituted"
    CALENDAR_INCOMPLETE = "calendar_incomplete"
    FACT_INCOMPLETE = "fact_incomplete"
    FACT_SUBSTITUTED = "fact_substituted"
    FACT_FUTURE_OR_STALE = "fact_future_or_stale"


@dataclass(frozen=True)
class R5MonitoringMetricResult:
    """Recomputed breach history for one pre-registered metric."""

    metric_key: R5MonitoringMetricKey
    unit: R5MonitoringMetricUnit
    direction: R5MonitoringThresholdDirection
    threshold: Decimal
    latest_value: Decimal
    breached_period_ids: tuple[str, ...]
    trailing_consecutive_breaches: int
    required_consecutive_breaches: int

    def __post_init__(self) -> None:
        if type(self.metric_key) is not R5MonitoringMetricKey:
            raise TypeError("monitoring metric result key is invalid")
        if type(self.unit) is not R5MonitoringMetricUnit:
            raise TypeError("monitoring metric result unit is invalid")
        if type(self.direction) is not R5MonitoringThresholdDirection:
            raise TypeError("monitoring metric result direction is invalid")
        R5MonitoringMetric(self.metric_key, self.unit, self.latest_value)
        R5MonitoringThreshold(
            self.metric_key,
            self.unit,
            self.direction,
            self.threshold,
            self.required_consecutive_breaches,
        )
        if type(self.breached_period_ids) is not tuple:
            raise TypeError("monitoring result period IDs must be a tuple")
        for period_id in self.breached_period_ids:
            _require_hash(period_id, "monitoring result breached period")
        if len(set(self.breached_period_ids)) != len(self.breached_period_ids):
            raise ValueError("monitoring result breach periods must be unique")
        _require_int(
            self.trailing_consecutive_breaches,
            "monitoring trailing breaches",
            minimum=0,
            maximum=64,
        )
        _require_int(
            self.required_consecutive_breaches,
            "monitoring required breaches",
            minimum=2,
            maximum=64,
        )


@dataclass(frozen=True)
class R5PostPromotionMonitoringAssessment:
    """Recomputable internal assessment with no automatic action authority."""

    assessment_id: str
    assessment_version: str
    result_id: str
    result_hash: str
    policy_id: str
    policy_hash: str
    calendar_hash: str
    latest_period_id: str | None
    fact_hashes: tuple[str, ...]
    metric_results: tuple[R5MonitoringMetricResult, ...]
    label_drift_period_ids: tuple[str, ...]
    data_drift_period_ids: tuple[str, ...]
    blocker_codes: tuple[R5MonitoringBlockerCode, ...]
    status: R5MonitoringAssessmentStatus
    evaluated_at: datetime
    manual_retirement_review_required: bool
    automatic_retirement: bool
    research_only: bool
    must_not_publish_current: bool
    must_not_decide: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_hash: str,
        policy_id: str,
        policy_hash: str,
        calendar_hash: str,
        latest_period_id: str | None,
        fact_hashes: tuple[str, ...],
        metric_results: tuple[R5MonitoringMetricResult, ...],
        label_drift_period_ids: tuple[str, ...],
        data_drift_period_ids: tuple[str, ...],
        blocker_codes: tuple[R5MonitoringBlockerCode, ...],
        status: R5MonitoringAssessmentStatus,
        evaluated_at: datetime,
    ) -> R5PostPromotionMonitoringAssessment:
        """Build a sealed assessment whose status is re-derived on validation."""

        values: tuple[object, ...] = (
            MONITORING_ASSESSMENT_VERSION,
            result_id,
            result_hash,
            policy_id,
            policy_hash,
            calendar_hash,
            latest_period_id,
            fact_hashes,
            metric_results,
            label_drift_period_ids,
            data_drift_period_ids,
            blocker_codes,
            status,
            evaluated_at,
            status is R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
            False,
            True,
            True,
            True,
            True,
        )
        digest = _assessment_hash_values(values)
        return cls(
            assessment_id=f"r5-monitoring-assessment:{digest[:24]}",
            assessment_version=MONITORING_ASSESSMENT_VERSION,
            result_id=result_id,
            result_hash=result_hash,
            policy_id=policy_id,
            policy_hash=policy_hash,
            calendar_hash=calendar_hash,
            latest_period_id=latest_period_id,
            fact_hashes=fact_hashes,
            metric_results=metric_results,
            label_drift_period_ids=label_drift_period_ids,
            data_drift_period_ids=data_drift_period_ids,
            blocker_codes=blocker_codes,
            status=status,
            evaluated_at=evaluated_at,
            manual_retirement_review_required=(
                status is R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
            ),
            automatic_retirement=False,
            research_only=True,
            must_not_publish_current=True,
            must_not_decide=True,
            must_not_execute=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "monitoring assessment_id")
        if self.assessment_version != MONITORING_ASSESSMENT_VERSION:
            raise ValueError("monitoring assessment version is unsupported")
        _require_token(self.result_id, "monitoring assessment result_id")
        _require_hash(self.result_hash, "monitoring assessment result_hash")
        _require_token(self.policy_id, "monitoring assessment policy_id")
        _require_hash(self.policy_hash, "monitoring assessment policy_hash")
        _require_hash(self.calendar_hash, "monitoring assessment calendar_hash")
        _require_aware(self.evaluated_at, "monitoring assessment evaluated_at")
        if type(self.status) is not R5MonitoringAssessmentStatus:
            raise TypeError("monitoring assessment status is invalid")
        for collection in (
            self.fact_hashes,
            self.metric_results,
            self.label_drift_period_ids,
            self.data_drift_period_ids,
            self.blocker_codes,
        ):
            if type(collection) is not tuple:
                raise TypeError("monitoring assessment collections must be tuples")
        for digest in self.fact_hashes:
            _require_hash(digest, "monitoring assessment fact hash")
        for period_id in (*self.label_drift_period_ids, *self.data_drift_period_ids):
            _require_hash(period_id, "monitoring assessment drift period")
        if len(set(self.fact_hashes)) != len(self.fact_hashes):
            raise ValueError("monitoring assessment fact hashes must be unique")
        for item in self.metric_results:
            if type(item) is not R5MonitoringMetricResult:
                raise TypeError("monitoring assessment metric result type is invalid")
            item.__post_init__()
        if self.metric_results and tuple(item.metric_key for item in self.metric_results) != tuple(
            R5MonitoringMetricKey
        ):
            raise ValueError("monitoring assessment metrics are non-canonical")
        for blocker in self.blocker_codes:
            if type(blocker) is not R5MonitoringBlockerCode:
                raise TypeError("monitoring assessment blocker type is invalid")
        if self.status is R5MonitoringAssessmentStatus.BLOCKED:
            if not self.blocker_codes or self.metric_results or self.latest_period_id is not None:
                raise ValueError("blocked monitoring assessment shape is invalid")
        else:
            if self.blocker_codes or len(self.metric_results) != len(R5MonitoringMetricKey):
                raise ValueError("available monitoring assessment shape is invalid")
            if self.latest_period_id is None:
                raise ValueError("available assessment requires latest period")
            _require_hash(self.latest_period_id, "monitoring assessment latest period")
            expected = _derive_status(
                self.metric_results,
                self.latest_period_id,
                self.label_drift_period_ids,
                self.data_drift_period_ids,
            )
            if self.status is not expected:
                raise ValueError("monitoring assessment status is not reproducible")
        if self.manual_retirement_review_required != (
            self.status is R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
        ):
            raise ValueError("monitoring assessment manual review flag differs")
        for label, value in (
            ("automatic_retirement", self.automatic_retirement),
            ("research_only", self.research_only),
            ("must_not_publish_current", self.must_not_publish_current),
            ("must_not_decide", self.must_not_decide),
            ("must_not_execute", self.must_not_execute),
        ):
            if type(value) is not bool:
                raise TypeError(f"monitoring assessment {label} must be bool")
        if self.automatic_retirement or not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_decide
            and self.must_not_execute
        ):
            raise ValueError("monitoring assessment safety boundary differs")
        _require_hash(self.content_hash, "monitoring assessment content_hash")
        expected_hash = monitoring_assessment_hash(self)
        if (
            self.content_hash != expected_hash
            or self.assessment_id != f"r5-monitoring-assessment:{expected_hash[:24]}"
        ):
            raise ValueError("monitoring assessment identity or content seal differs")

    def validated_copy(
        self,
        *,
        policy: R5MonitoringPolicy,
        calendar: R5MonitoringCalendar,
        facts: tuple[R5PostPromotionMonitoringFact, ...],
    ) -> R5PostPromotionMonitoringAssessment:
        """Replay the exact policy, calendar, facts, metrics, drift, and status."""

        self.__post_init__()
        if type(policy) is not R5MonitoringPolicy:
            raise TypeError("monitoring assessment replay policy type is invalid")
        if type(calendar) is not R5MonitoringCalendar:
            raise TypeError("monitoring assessment replay calendar type is invalid")
        if type(facts) is not tuple:
            raise TypeError("monitoring assessment replay facts must be a tuple")
        copied_policy = policy.validated_copy()
        copied_calendar = calendar.validated_copy()
        copied_facts = tuple(item.validated_copy() for item in facts)
        rebuilt = evaluate_r5_post_promotion_monitoring(
            requested_policy_id=copied_policy.policy_id,
            requested_policy_version=copied_policy.policy_version,
            expected_policy_hash=copied_policy.content_hash,
            active_lifecycle=copied_policy.target.active_lifecycle.validated_copy(),
            fixed_income=copied_policy.target.fixed_income.validated_copy(),
            policy=copied_policy,
            calendar=copied_calendar,
            portfolio_facts=copied_facts,
            evaluated_at=self.evaluated_at,
        )
        if rebuilt != self:
            raise ValueError("monitoring assessment full replay differs")
        return rebuilt


def _assessment_values(value: R5PostPromotionMonitoringAssessment) -> tuple[object, ...]:
    return (
        value.assessment_version,
        value.result_id,
        value.result_hash,
        value.policy_id,
        value.policy_hash,
        value.calendar_hash,
        value.latest_period_id,
        value.fact_hashes,
        value.metric_results,
        value.label_drift_period_ids,
        value.data_drift_period_ids,
        value.blocker_codes,
        value.status,
        value.evaluated_at,
        value.manual_retirement_review_required,
        value.automatic_retirement,
        value.research_only,
        value.must_not_publish_current,
        value.must_not_decide,
        value.must_not_execute,
    )


def _assessment_hash_values(values: tuple[object, ...]) -> str:
    return canonical_hash(
        {
            "schema": "research-r5-monitoring-assessment-content.v1",
            "fields": values,
        }
    )


def monitoring_assessment_hash(value: R5PostPromotionMonitoringAssessment) -> str:
    """Recompute every assessment field and safety flag."""

    return _assessment_hash_values(_assessment_values(value))


def _derive_status(
    metric_results: tuple[R5MonitoringMetricResult, ...],
    latest_period_id: str,
    label_drift_period_ids: tuple[str, ...],
    data_drift_period_ids: tuple[str, ...],
) -> R5MonitoringAssessmentStatus:
    review = bool(label_drift_period_ids or data_drift_period_ids) or any(
        item.trailing_consecutive_breaches >= item.required_consecutive_breaches
        for item in metric_results
    )
    if review:
        return R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    if any(latest_period_id in item.breached_period_ids for item in metric_results):
        return R5MonitoringAssessmentStatus.BREACHED
    return R5MonitoringAssessmentStatus.HEALTHY


def evaluate_r5_post_promotion_monitoring(
    *,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    active_lifecycle: R5MonitoringActiveLifecycle | None,
    fixed_income: R5MonitoringFixedIncomeEvidence | None,
    policy: R5MonitoringPolicy | None,
    calendar: R5MonitoringCalendar | None,
    portfolio_facts: tuple[R5PostPromotionMonitoringFact, ...],
    evaluated_at: datetime,
) -> R5PostPromotionMonitoringAssessment:
    """Validate exact owners and recompute health without taking lifecycle action."""

    _require_token(requested_policy_id, "requested monitoring policy_id")
    _require_token(requested_policy_version, "requested monitoring policy_version")
    _require_hash(expected_policy_hash, "expected monitoring policy hash")
    _require_aware(evaluated_at, "monitoring evaluated_at")
    blockers: list[R5MonitoringBlockerCode] = []
    valid_policy = _validated_policy(
        policy,
        requested_policy_id,
        requested_policy_version,
        expected_policy_hash,
        evaluated_at,
        blockers,
    )
    target = None if valid_policy is None else valid_policy.target
    valid_active = _validated_active(active_lifecycle, target, evaluated_at, blockers)
    valid_fixed_income = _validated_fixed_income(fixed_income, target, evaluated_at, blockers)
    valid_calendar = _validated_calendar(calendar, valid_policy, evaluated_at, blockers)
    valid_facts = _validated_facts(
        portfolio_facts,
        valid_policy,
        valid_calendar,
        valid_active,
        valid_fixed_income,
        evaluated_at,
        blockers,
    )
    result_id = target.fixed_income.result_id if target is not None else "r5-result:unavailable"
    result_hash = target.fixed_income.result_hash if target is not None else "0" * 64
    calendar_hash = valid_calendar.content_hash if valid_calendar is not None else "0" * 64
    if blockers:
        return R5PostPromotionMonitoringAssessment.create(
            result_id=result_id,
            result_hash=result_hash,
            policy_id=requested_policy_id,
            policy_hash=expected_policy_hash,
            calendar_hash=calendar_hash,
            latest_period_id=None,
            fact_hashes=tuple(item.content_hash for item in valid_facts),
            metric_results=(),
            label_drift_period_ids=(),
            data_drift_period_ids=(),
            blocker_codes=tuple(sorted(set(blockers), key=lambda item: item.value)),
            status=R5MonitoringAssessmentStatus.BLOCKED,
            evaluated_at=evaluated_at,
        )
    if valid_policy is None or valid_calendar is None:
        raise AssertionError("validated R5 monitoring owners unexpectedly missing")
    metric_results = _derive_metric_results(valid_policy, valid_facts)
    latest_period_id = valid_calendar.entries[-1].period_id
    label_drift = tuple(
        item.period_id
        for item in valid_facts
        if item.observed_label_hash != valid_policy.target.label_baseline.content_hash
    )
    data_drift = tuple(
        item.period_id
        for item in valid_facts
        if item.observed_data_schema_hash != valid_policy.target.data_schema.content_hash
    )
    status = _derive_status(metric_results, latest_period_id, label_drift, data_drift)
    return R5PostPromotionMonitoringAssessment.create(
        result_id=result_id,
        result_hash=result_hash,
        policy_id=requested_policy_id,
        policy_hash=expected_policy_hash,
        calendar_hash=valid_calendar.content_hash,
        latest_period_id=latest_period_id,
        fact_hashes=tuple(item.content_hash for item in valid_facts),
        metric_results=metric_results,
        label_drift_period_ids=label_drift,
        data_drift_period_ids=data_drift,
        blocker_codes=(),
        status=status,
        evaluated_at=evaluated_at,
    )


def _validated_policy(
    value: R5MonitoringPolicy | None,
    requested_id: str,
    requested_version: str,
    expected_hash: str,
    evaluated_at: datetime,
    blockers: list[R5MonitoringBlockerCode],
) -> R5MonitoringPolicy | None:
    if value is None:
        blockers.append(R5MonitoringBlockerCode.POLICY_UNAVAILABLE)
        return None
    try:
        if type(value) is not R5MonitoringPolicy:
            raise TypeError
        copied = value.validated_copy()
        if copied != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        blockers.append(R5MonitoringBlockerCode.POLICY_SUBSTITUTED)
        return None
    if (
        value.policy_id != requested_id
        or value.policy_version != requested_version
        or value.content_hash != expected_hash
    ):
        blockers.append(R5MonitoringBlockerCode.POLICY_SUBSTITUTED)
    if not value.recorded_at <= evaluated_at < value.valid_until:
        blockers.append(R5MonitoringBlockerCode.POLICY_INACTIVE)
    return copied


def _validated_active(
    value: R5MonitoringActiveLifecycle | None,
    target: R5MonitoringTarget | None,
    evaluated_at: datetime,
    blockers: list[R5MonitoringBlockerCode],
) -> R5MonitoringActiveLifecycle | None:
    if value is None:
        blockers.append(R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_UNAVAILABLE)
        return None
    try:
        if type(value) is not R5MonitoringActiveLifecycle:
            raise TypeError
        copied = value.validated_copy()
        if copied != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        blockers.append(R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_SUBSTITUTED)
        return None
    if target is None or copied != target.active_lifecycle:
        blockers.append(R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_SUBSTITUTED)
    if not copied.recorded_at <= evaluated_at < copied.valid_until:
        blockers.append(R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_INACTIVE)
    return copied


def _validated_fixed_income(
    value: R5MonitoringFixedIncomeEvidence | None,
    target: R5MonitoringTarget | None,
    evaluated_at: datetime,
    blockers: list[R5MonitoringBlockerCode],
) -> R5MonitoringFixedIncomeEvidence | None:
    if value is None:
        blockers.append(R5MonitoringBlockerCode.FIXED_INCOME_UNAVAILABLE)
        return None
    try:
        if type(value) is not R5MonitoringFixedIncomeEvidence:
            raise TypeError
        copied = value.validated_copy()
        if copied != value or copied.recorded_at > evaluated_at:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        blockers.append(R5MonitoringBlockerCode.FIXED_INCOME_SUBSTITUTED)
        return None
    if target is None or copied != target.fixed_income:
        blockers.append(R5MonitoringBlockerCode.FIXED_INCOME_SUBSTITUTED)
    return copied


def _validated_calendar(
    value: R5MonitoringCalendar | None,
    policy: R5MonitoringPolicy | None,
    evaluated_at: datetime,
    blockers: list[R5MonitoringBlockerCode],
) -> R5MonitoringCalendar | None:
    if value is None:
        blockers.append(R5MonitoringBlockerCode.CALENDAR_UNAVAILABLE)
        return None
    try:
        if type(value) is not R5MonitoringCalendar:
            raise TypeError
        copied = value.validated_copy()
        if copied != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        blockers.append(R5MonitoringBlockerCode.CALENDAR_SUBSTITUTED)
        return None
    if policy is None or (
        copied.owner != policy.calendar_owner
        or copied.content_hash != policy.calendar_hash
        or copied.recorded_at != policy.calendar_recorded_at
        or copied.entries[0].period_start != policy.calendar_first_period_start
        or copied.valid_until < policy.valid_until
    ):
        blockers.append(R5MonitoringBlockerCode.CALENDAR_SUBSTITUTED)
    if (
        policy is None
        or len(copied.entries) < policy.minimum_complete_periods
        or any(item.period_end > evaluated_at for item in copied.entries)
    ):
        blockers.append(R5MonitoringBlockerCode.CALENDAR_INCOMPLETE)
    return copied


def _validated_facts(
    values: tuple[R5PostPromotionMonitoringFact, ...],
    policy: R5MonitoringPolicy | None,
    calendar: R5MonitoringCalendar | None,
    active: R5MonitoringActiveLifecycle | None,
    fixed_income: R5MonitoringFixedIncomeEvidence | None,
    evaluated_at: datetime,
    blockers: list[R5MonitoringBlockerCode],
) -> tuple[R5PostPromotionMonitoringFact, ...]:
    if type(values) is not tuple or policy is None or calendar is None:
        blockers.append(R5MonitoringBlockerCode.FACT_INCOMPLETE)
        return ()
    if tuple(
        item.period_id for item in values if type(item) is R5PostPromotionMonitoringFact
    ) != tuple(item.period_id for item in calendar.entries) or len(values) != len(calendar.entries):
        blockers.append(R5MonitoringBlockerCode.FACT_INCOMPLETE)
    copies: list[R5PostPromotionMonitoringFact] = []
    for index, value in enumerate(values):
        try:
            if type(value) is not R5PostPromotionMonitoringFact:
                raise TypeError
            copied = value.validated_copy()
            if copied != value:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            blockers.append(R5MonitoringBlockerCode.FACT_SUBSTITUTED)
            continue
        copies.append(copied)
        if index >= len(calendar.entries) or not _fact_matches_graph(
            copied,
            calendar.entries[index],
            policy,
            active,
            fixed_income,
        ):
            blockers.append(R5MonitoringBlockerCode.FACT_SUBSTITUTED)
        freshness_deadline = copied.period_end + timedelta(
            seconds=policy.maximum_source_delay_seconds
        )
        if not (
            copied.source_projection.source_observed_at <= copied.period_end
            and copied.source_projection.owner_record.recorded_at <= copied.observed_at
            and copied.source_projection.owner_record.recorded_at
            <= evaluated_at
            < copied.source_projection.owner_record.valid_until
            and copied.observed_at
            <= copied.available_at
            <= copied.recorded_at
            <= freshness_deadline
            and copied.recorded_at <= evaluated_at < copied.valid_until
        ):
            blockers.append(R5MonitoringBlockerCode.FACT_FUTURE_OR_STALE)
    if calendar.entries and evaluated_at - calendar.entries[-1].period_end > timedelta(
        seconds=policy.maximum_period_age_seconds
    ):
        blockers.append(R5MonitoringBlockerCode.FACT_FUTURE_OR_STALE)
    return tuple(copies)


def _fact_matches_graph(
    fact: R5PostPromotionMonitoringFact,
    period: object,
    policy: R5MonitoringPolicy,
    active: R5MonitoringActiveLifecycle | None,
    fixed_income: R5MonitoringFixedIncomeEvidence | None,
) -> bool:
    target = policy.target
    return (
        fact.period_id == getattr(period, "period_id", None)
        and fact.period_start == getattr(period, "period_start", None)
        and fact.period_end == getattr(period, "period_end", None)
        and (fact.calendar_id, fact.calendar_version, fact.calendar_hash)
        == (
            policy.calendar_owner.owner_id,
            policy.calendar_owner.owner_version,
            policy.calendar_hash,
        )
        and (fact.policy_id, fact.policy_version, fact.policy_hash)
        == (policy.policy_id, policy.policy_version, policy.content_hash)
        and fact.target_hash == target.content_hash
        and (fact.scope_id, fact.scope_hash)
        == (target.active_lifecycle.scope_id, target.active_lifecycle.scope_hash)
        and (fact.decision_id, fact.decision_version, fact.decision_hash)
        == (
            target.active_lifecycle.decision_id,
            target.active_lifecycle.decision_version,
            target.active_lifecycle.decision_hash,
        )
        and fact.lifecycle_hash == target.active_lifecycle.content_hash
        and (
            fact.fixed_income_result_id,
            fact.fixed_income_result_version,
            fact.fixed_income_result_hash,
            fact.fixed_income_owner_seal_id,
            fact.fixed_income_owner_seal_version,
            fact.fixed_income_owner_seal_hash,
        )
        == (
            target.fixed_income.result_id,
            target.fixed_income.result_version,
            target.fixed_income.result_hash,
            target.fixed_income.owner_seal_id,
            target.fixed_income.owner_seal_version,
            target.fixed_income.owner_seal_hash,
        )
        and (fact.benchmark_owner, fact.benchmark_id, fact.benchmark_version, fact.benchmark_hash)
        == (
            target.benchmark.owner,
            target.benchmark.owner_id,
            target.benchmark.owner_version,
            target.benchmark.content_hash,
        )
        and (
            fact.cost_policy_owner,
            fact.cost_policy_id,
            fact.cost_policy_version,
            fact.cost_policy_hash,
        )
        == (
            target.cost_policy.owner,
            target.cost_policy.owner_id,
            target.cost_policy.owner_version,
            target.cost_policy.content_hash,
        )
        and (
            fact.liquidity_policy_owner,
            fact.liquidity_policy_id,
            fact.liquidity_policy_version,
            fact.liquidity_policy_hash,
        )
        == (
            target.liquidity_policy.owner,
            target.liquidity_policy.owner_id,
            target.liquidity_policy.owner_version,
            target.liquidity_policy.content_hash,
        )
        and active == target.active_lifecycle
        and fixed_income == target.fixed_income
    )


def _derive_metric_results(
    policy: R5MonitoringPolicy,
    facts: tuple[R5PostPromotionMonitoringFact, ...],
) -> tuple[R5MonitoringMetricResult, ...]:
    results: list[R5MonitoringMetricResult] = []
    for threshold in policy.thresholds:
        observations = tuple(
            next(item for item in fact.metrics if item.metric_key is threshold.metric_key)
            for fact in facts
        )
        breached = tuple(
            fact.period_id
            for fact, observation in zip(facts, observations, strict=True)
            if threshold.is_breached(observation.value)
        )
        trailing = 0
        for fact in reversed(facts):
            if fact.period_id not in breached:
                break
            trailing += 1
        results.append(
            R5MonitoringMetricResult(
                metric_key=threshold.metric_key,
                unit=threshold.unit,
                direction=threshold.direction,
                threshold=threshold.breach_threshold,
                latest_value=observations[-1].value,
                breached_period_ids=breached,
                trailing_consecutive_breaches=trailing,
                required_consecutive_breaches=(threshold.retirement_review_consecutive_breaches),
            )
        )
    return tuple(results)


__all__ = [
    "R5MonitoringAssessmentStatus",
    "R5MonitoringBlockerCode",
    "R5MonitoringMetricResult",
    "R5PostPromotionMonitoringAssessment",
    "evaluate_r5_post_promotion_monitoring",
    "monitoring_assessment_hash",
]
