"""Pure evaluation of R4 post-promotion monitoring evidence.

This module derives a research-only health or retirement-review assessment. It
never retires a promotion, publishes current state, authorizes a portfolio
decision, or executes anything. Evidence value objects live in the sibling
``r4_promotion_monitoring_contracts`` module and are re-exported here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .r4_promotion_decision import (
    R4PromotionDecision,
    R4PromotionDecisionOutcome,
    create_r4_promotion_decision,
    r4_promotion_decision_hash,
)
from .r4_promotion_evidence import (
    R4PromotionR3AttestationEvidence,
    r4_promotion_r3_attestation_evidence_hash,
)
from .r4_promotion_lifecycle import R4PromotionDecisionIdentity
from .r4_promotion_monitoring_contracts import (
    REQUIRED_R4_MONITORING_METRICS,
    R4MonitoringMetricKey,
    R4MonitoringMetricObservation,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPeriodEntry,
    R4MonitoringPolicy,
    R4MonitoringThreshold,
    R4MonitoringThresholdDirection,
    _decimal_text,
    _decision_identity_payload,
    _hash_payload,
    _hashes_equal,
    _is_hash,
    _require_aware,
    _require_hash,
    _require_metric_domain,
    _require_token,
    _utc_text,
    derive_r4_monitoring_period_id,
    r4_monitoring_observation_hash,
    r4_monitoring_period_calendar_hash,
    r4_monitoring_policy_hash,
)
from .r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
    r4_promotion_portfolio_record_seal_hash,
)
from .r4_promotion_scope_policy import r4_promotion_policy_hash
from .r4_promotion_trial import r4_promotion_trial_seal_hash


class R4MonitoringAssessmentStatus(StrEnum):
    """Internal assessment state with no lifecycle side effect."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"
    BLOCKED = "blocked"


class R4MonitoringBlockerCode(StrEnum):
    """Stable reasons why an assessment cannot be trusted."""

    ACTIVE_DECISION_MISSING = "r4_monitoring.active_decision.missing"
    ACTIVE_DECISION_INVALID = "r4_monitoring.active_decision.invalid"
    PORTFOLIO_RESULT_MISSING = "r4_monitoring.portfolio_result.missing"
    PORTFOLIO_RESULT_INVALID = "r4_monitoring.portfolio_result.invalid"
    R3_ATTESTATION_MISSING = "r4_monitoring.r3_attestation.missing"
    R3_ATTESTATION_INVALID = "r4_monitoring.r3_attestation.invalid"
    POLICY_MISSING = "r4_monitoring.policy.missing"
    POLICY_BINDING_MISMATCH = "r4_monitoring.policy.binding_mismatch"
    POLICY_HASH_MISMATCH = "r4_monitoring.policy.hash_mismatch"
    POLICY_FROM_FUTURE = "r4_monitoring.policy.from_future"
    POLICY_INACTIVE = "r4_monitoring.policy.inactive"
    POLICY_CAUSALITY_INVALID = "r4_monitoring.policy.causality_invalid"
    PERIOD_CALENDAR_MISSING = "r4_monitoring.period_calendar.missing"
    PERIOD_CALENDAR_BINDING_MISMATCH = "r4_monitoring.period_calendar.binding_mismatch"
    PERIOD_CALENDAR_HASH_MISMATCH = "r4_monitoring.period_calendar.hash_mismatch"
    PERIOD_CALENDAR_FROM_FUTURE = "r4_monitoring.period_calendar.from_future"
    PERIOD_CALENDAR_INACTIVE = "r4_monitoring.period_calendar.inactive"
    PERIOD_CALENDAR_HORIZON_INVALID = "r4_monitoring.period_calendar.horizon_invalid"
    OBSERVATIONS_MISSING = "r4_monitoring.observations.missing"
    OBSERVATION_IDENTITY_DUPLICATE = "r4_monitoring.observation.identity_duplicate"
    OBSERVATION_PERIOD_DUPLICATE = "r4_monitoring.observation.period_duplicate"
    OBSERVATION_PERIOD_NOT_IN_CALENDAR = "r4_monitoring.observation.period_not_in_calendar"
    OBSERVATION_PERIOD_FROM_FUTURE = "r4_monitoring.observation.period_from_future"
    OBSERVATION_PERIOD_COVERAGE_INCOMPLETE = "r4_monitoring.observation.period_coverage_incomplete"
    OBSERVATION_BINDING_MISMATCH = "r4_monitoring.observation.binding_mismatch"
    OBSERVATION_OWNER_MISMATCH = "r4_monitoring.observation.owner_mismatch"
    PORTFOLIO_BINDING_MISMATCH = "r4_monitoring.observation.portfolio_binding_mismatch"
    R3_BINDING_MISMATCH = "r4_monitoring.observation.r3_binding_mismatch"
    PIT_MANIFEST_MISMATCH = "r4_monitoring.observation.pit_manifest_mismatch"
    EVIDENCE_REF_MISMATCH = "r4_monitoring.observation.evidence_ref_mismatch"
    LABEL_PROTOCOL_MISMATCH = "r4_monitoring.observation.label_protocol_mismatch"
    OBSERVATION_HASH_MISMATCH = "r4_monitoring.observation.hash_mismatch"
    OBSERVATION_FROM_FUTURE = "r4_monitoring.observation.from_future"
    OBSERVATION_STALE = "r4_monitoring.observation.stale"
    OBSERVATION_COUNT_INSUFFICIENT = "r4_monitoring.observation.count_insufficient"
    METRIC_MISSING = "r4_monitoring.metric.missing"
    METRIC_DUPLICATE = "r4_monitoring.metric.duplicate"
    METRIC_UNIT_MISMATCH = "r4_monitoring.metric.unit_mismatch"
    METRIC_DOMAIN_INVALID = "r4_monitoring.metric.domain_invalid"


@dataclass(frozen=True)
class R4MonitoringMetricResult:
    """Latest threshold state and trailing breach count for one metric."""

    metric_key: R4MonitoringMetricKey
    unit: str
    latest_value: Decimal
    breach_threshold: Decimal
    direction: R4MonitoringThresholdDirection
    latest_breached: bool
    trailing_consecutive_breaches: int
    retirement_review_consecutive_breaches: int


@dataclass(frozen=True)
class R4MonitoringAssessment:
    """Content-sealed internal result that never mutates lifecycle state."""

    active_decision: R4PromotionDecisionIdentity
    requested_policy_id: str
    requested_policy_version: str
    expected_policy_hash: str
    active_decision_hash: str | None
    policy_hash: str | None
    evaluated_at: datetime
    status: R4MonitoringAssessmentStatus
    observation_hashes: tuple[str, ...]
    metric_results: tuple[R4MonitoringMetricResult, ...]
    blockers: tuple[R4MonitoringBlockerCode, ...]
    label_drift_detected: bool
    data_drift_detected: bool
    retirement_review_required: bool
    review_reason_codes: tuple[str, ...]
    automatic_retirement: bool = False
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_publish_current: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.requested_policy_id, "R4MonitoringAssessment.requested_policy_id")
        _require_token(
            self.requested_policy_version,
            "R4MonitoringAssessment.requested_policy_version",
        )
        _require_hash(self.expected_policy_hash, "R4MonitoringAssessment.expected_policy_hash")
        if self.active_decision_hash is not None:
            _require_hash(self.active_decision_hash, "R4MonitoringAssessment.active_decision_hash")
        if self.policy_hash is not None:
            _require_hash(self.policy_hash, "R4MonitoringAssessment.policy_hash")
        _require_aware(self.evaluated_at, "R4MonitoringAssessment.evaluated_at")
        if not isinstance(self.status, R4MonitoringAssessmentStatus):
            raise ValueError("R4 monitoring assessment status is invalid")
        if not isinstance(self.blockers, tuple) or any(
            not isinstance(item, R4MonitoringBlockerCode) for item in self.blockers
        ):
            raise ValueError("R4 monitoring assessment blockers are invalid")
        if len(self.blockers) != len(set(self.blockers)):
            raise ValueError("R4 monitoring blockers must be unique")
        if not isinstance(self.observation_hashes, tuple):
            raise ValueError("R4 monitoring observation hashes must be a tuple")
        if len(self.observation_hashes) != len(set(self.observation_hashes)):
            raise ValueError("R4 monitoring observation hashes must be unique")
        for digest in self.observation_hashes:
            _require_hash(digest, "R4MonitoringAssessment.observation_hash")
        if not isinstance(self.metric_results, tuple) or any(
            type(item) is not R4MonitoringMetricResult for item in self.metric_results
        ):
            raise ValueError("R4 monitoring metric results are invalid")
        if not isinstance(self.review_reason_codes, tuple):
            raise ValueError("R4 monitoring review reasons must be a tuple")
        for reason in self.review_reason_codes:
            _require_token(reason, "R4MonitoringAssessment.review_reason")
        if self.review_reason_codes != tuple(sorted(set(self.review_reason_codes))):
            raise ValueError("R4 monitoring review reasons must be canonical and unique")
        for flag_name in (
            "label_drift_detected",
            "data_drift_detected",
            "retirement_review_required",
            "automatic_retirement",
            "research_only",
            "must_not_use_for_decision",
            "must_not_publish_current",
            "must_not_execute",
        ):
            if type(getattr(self, flag_name)) is not bool:
                raise ValueError(f"R4 monitoring assessment {flag_name} must be boolean")
        if self.status is R4MonitoringAssessmentStatus.BLOCKED:
            if (
                not self.blockers
                or self.metric_results
                or self.review_reason_codes
                or self.label_drift_detected
                or self.data_drift_detected
                or self.retirement_review_required
            ):
                raise ValueError("blocked R4 monitoring assessment shape is invalid")
        else:
            if self.blockers:
                raise ValueError("non-blocked R4 monitoring assessment cannot contain blockers")
            if any(
                not isinstance(item.metric_key, R4MonitoringMetricKey)
                for item in self.metric_results
            ):
                raise ValueError("R4 monitoring assessment metric key is invalid")
            metric_keys = tuple(item.metric_key for item in self.metric_results)
            if (
                len(metric_keys) != len(REQUIRED_R4_MONITORING_METRICS)
                or len(metric_keys) != len(set(metric_keys))
                or frozenset(metric_keys) != REQUIRED_R4_MONITORING_METRICS
            ):
                raise ValueError(
                    "non-blocked R4 monitoring assessment requires every required metric"
                )
            expected_reasons = _expected_review_reason_codes(
                metric_results=self.metric_results,
                label_drift_detected=self.label_drift_detected,
                data_drift_detected=self.data_drift_detected,
            )
            if self.review_reason_codes != expected_reasons:
                raise ValueError("R4 monitoring drift/review reasons are inconsistent")
            expected_review = bool(expected_reasons)
            if self.retirement_review_required is not expected_review:
                raise ValueError("R4 monitoring review flag is inconsistent with its reasons")
            any_latest_breach = any(item.latest_breached for item in self.metric_results)
            expected_status = (
                R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
                if expected_review
                else (
                    R4MonitoringAssessmentStatus.BREACHED
                    if any_latest_breach
                    else R4MonitoringAssessmentStatus.HEALTHY
                )
            )
            if self.status is not expected_status:
                raise ValueError("R4 monitoring assessment status is inconsistent")
        if self.automatic_retirement:
            raise ValueError("R4 monitoring cannot automatically retire a promotion")
        if not (
            self.research_only
            and self.must_not_use_for_decision
            and self.must_not_publish_current
            and self.must_not_execute
        ):
            raise ValueError("R4 monitoring assessment cannot authorize production behavior")
        object.__setattr__(self, "content_hash", _assessment_hash(self))


def _expected_review_reason_codes(
    *,
    metric_results: tuple[R4MonitoringMetricResult, ...],
    label_drift_detected: bool,
    data_drift_detected: bool,
) -> tuple[str, ...]:
    reasons = [
        f"r4_monitoring.review.metric.{item.metric_key.value}.consecutive_breach"
        for item in metric_results
        if item.latest_breached
        and item.trailing_consecutive_breaches >= item.retirement_review_consecutive_breaches
    ]
    if label_drift_detected:
        reasons.append("r4_monitoring.review.label_drift")
    if data_drift_detected:
        reasons.append("r4_monitoring.review.data_drift")
    return tuple(sorted(set(reasons)))


def evaluate_r4_promotion_monitoring(
    *,
    requested_active_decision: R4PromotionDecisionIdentity,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    active_decision: R4PromotionDecision | None,
    portfolio_result: R4PromotionPortfolioRecordSeal | None,
    current_r3_attestation: R4PromotionR3AttestationEvidence | None,
    policy: R4MonitoringPolicy | None,
    period_calendar: R4MonitoringPeriodCalendar | None,
    observations: tuple[R4MonitoringObservation, ...],
    evaluated_at: datetime,
) -> R4MonitoringAssessment:
    """Recompute post-promotion health from exact owner evidence."""

    _require_token(requested_policy_id, "requested_policy_id")
    _require_token(requested_policy_version, "requested_policy_version")
    _require_hash(expected_policy_hash, "expected_policy_hash")
    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[R4MonitoringBlockerCode] = []

    if active_decision is None:
        blockers.append(R4MonitoringBlockerCode.ACTIVE_DECISION_MISSING)
    elif not _decision_is_exact(active_decision, requested_active_decision, evaluated_at):
        blockers.append(R4MonitoringBlockerCode.ACTIVE_DECISION_INVALID)

    if portfolio_result is None:
        blockers.append(R4MonitoringBlockerCode.PORTFOLIO_RESULT_MISSING)
    elif active_decision is None or not _portfolio_is_exact(
        portfolio_result,
        active_decision,
        evaluated_at,
    ):
        blockers.append(R4MonitoringBlockerCode.PORTFOLIO_RESULT_INVALID)

    if current_r3_attestation is None:
        blockers.append(R4MonitoringBlockerCode.R3_ATTESTATION_MISSING)
    elif active_decision is None or not _r3_is_exact(
        current_r3_attestation,
        active_decision,
        evaluated_at,
    ):
        blockers.append(R4MonitoringBlockerCode.R3_ATTESTATION_INVALID)

    if policy is None:
        blockers.append(R4MonitoringBlockerCode.POLICY_MISSING)
    else:
        try:
            validated_policy = policy.validated_copy()
            recomputed_policy_hash = r4_monitoring_policy_hash(validated_policy)
        except (AttributeError, TypeError, ValueError):
            validated_policy = None
            recomputed_policy_hash = None
        if (
            policy.policy_id != requested_policy_id
            or policy.policy_version != requested_policy_version
            or policy.active_decision != requested_active_decision
        ):
            blockers.append(R4MonitoringBlockerCode.POLICY_BINDING_MISMATCH)
        if (
            validated_policy is None
            or not _hashes_equal(policy.content_hash, recomputed_policy_hash)
            or not _hashes_equal(recomputed_policy_hash, expected_policy_hash)
        ):
            blockers.append(R4MonitoringBlockerCode.POLICY_HASH_MISMATCH)
        if policy.recorded_at > evaluated_at:
            blockers.append(R4MonitoringBlockerCode.POLICY_FROM_FUTURE)
        if not policy.is_active_at(evaluated_at):
            blockers.append(R4MonitoringBlockerCode.POLICY_INACTIVE)
        if active_decision is not None and policy.recorded_at < active_decision.recorded_at:
            blockers.append(R4MonitoringBlockerCode.POLICY_CAUSALITY_INVALID)

    if period_calendar is None:
        blockers.append(R4MonitoringBlockerCode.PERIOD_CALENDAR_MISSING)
    elif policy is not None:
        try:
            recomputed_calendar_hash = r4_monitoring_period_calendar_hash(period_calendar)
        except (AttributeError, TypeError, ValueError):
            recomputed_calendar_hash = None
        if (
            period_calendar.source_owner != policy.expected_period_calendar_owner
            or period_calendar.calendar_id != policy.expected_period_calendar_id
            or period_calendar.calendar_version != policy.expected_period_calendar_version
        ):
            blockers.append(R4MonitoringBlockerCode.PERIOD_CALENDAR_BINDING_MISMATCH)
        if not _hashes_equal(
            period_calendar.content_hash, recomputed_calendar_hash
        ) or not _hashes_equal(
            recomputed_calendar_hash,
            policy.expected_period_calendar_hash,
        ):
            blockers.append(R4MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH)
        if period_calendar.recorded_at > evaluated_at:
            blockers.append(R4MonitoringBlockerCode.PERIOD_CALENDAR_FROM_FUTURE)
        if not period_calendar.is_active_at(evaluated_at):
            blockers.append(R4MonitoringBlockerCode.PERIOD_CALENDAR_INACTIVE)
        if (
            period_calendar.valid_from != policy.active_from
            or period_calendar.valid_until != policy.active_until
            or period_calendar.recorded_at > policy.recorded_at
        ):
            blockers.append(R4MonitoringBlockerCode.PERIOD_CALENDAR_HORIZON_INVALID)

    blockers.extend(
        _observation_blockers(
            requested_active_decision=requested_active_decision,
            active_decision=active_decision,
            portfolio_result=portfolio_result,
            current_r3_attestation=current_r3_attestation,
            policy=policy,
            period_calendar=period_calendar,
            observations=observations,
            evaluated_at=evaluated_at,
        )
    )
    unique_blockers = tuple(dict.fromkeys(blockers))
    if unique_blockers:
        return _blocked_assessment(
            active_decision=requested_active_decision,
            requested_policy_id=requested_policy_id,
            requested_policy_version=requested_policy_version,
            expected_policy_hash=expected_policy_hash,
            active_decision_hash=(
                None if active_decision is None else active_decision.content_hash
            ),
            policy_hash=None if policy is None else policy.content_hash,
            evaluated_at=evaluated_at,
            observations=observations,
            blockers=unique_blockers,
        )

    assert active_decision is not None
    assert policy is not None
    ordered = tuple(
        sorted(observations, key=lambda item: (item.period_start, item.period_end, item.period_id))
    )
    thresholds = {item.metric_key: item for item in policy.thresholds}
    results: list[R4MonitoringMetricResult] = []
    any_latest_breach = False
    for metric_key in sorted(REQUIRED_R4_MONITORING_METRICS, key=lambda item: item.value):
        threshold = thresholds[metric_key]
        values = tuple(
            next(metric.value for metric in observation.metrics if metric.metric_key is metric_key)
            for observation in ordered
        )
        breached = tuple(threshold.is_breached(value) for value in values)
        trailing = 0
        for is_breached in reversed(breached):
            if not is_breached:
                break
            trailing += 1
        latest_breached = breached[-1]
        any_latest_breach = any_latest_breach or latest_breached
        results.append(
            R4MonitoringMetricResult(
                metric_key=metric_key,
                unit=threshold.unit,
                latest_value=values[-1],
                breach_threshold=threshold.breach_threshold,
                direction=threshold.direction,
                latest_breached=latest_breached,
                trailing_consecutive_breaches=trailing,
                retirement_review_consecutive_breaches=(
                    threshold.retirement_review_consecutive_breaches
                ),
            )
        )
    label_drift = any(
        not _hashes_equal(
            observation.observed_label_set_hash,
            policy.expected_label_set_hash,
        )
        for observation in ordered
    )
    data_drift = any(
        not _hashes_equal(
            observation.observed_data_schema_hash,
            policy.expected_data_schema_hash,
        )
        for observation in ordered
    )
    metric_results = tuple(results)
    review_reason_codes = _expected_review_reason_codes(
        metric_results=metric_results,
        label_drift_detected=label_drift,
        data_drift_detected=data_drift,
    )
    review_required = bool(review_reason_codes)
    status = (
        R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
        if review_required
        else (
            R4MonitoringAssessmentStatus.BREACHED
            if any_latest_breach
            else R4MonitoringAssessmentStatus.HEALTHY
        )
    )
    return R4MonitoringAssessment(
        active_decision=requested_active_decision,
        requested_policy_id=requested_policy_id,
        requested_policy_version=requested_policy_version,
        expected_policy_hash=expected_policy_hash,
        active_decision_hash=active_decision.content_hash,
        policy_hash=policy.content_hash,
        evaluated_at=evaluated_at,
        status=status,
        observation_hashes=tuple(item.content_hash for item in ordered),
        metric_results=metric_results,
        blockers=(),
        label_drift_detected=label_drift,
        data_drift_detected=data_drift,
        retirement_review_required=review_required,
        review_reason_codes=review_reason_codes,
    )


def _decision_is_exact(
    decision: R4PromotionDecision,
    requested: R4PromotionDecisionIdentity,
    evaluated_at: datetime,
) -> bool:
    try:
        rebuilt = create_r4_promotion_decision(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            policy=decision.policy,
            trial=decision.trial,
            as_of=decision.decided_at,
            recorded_at=decision.recorded_at,
        )
        seals_valid = (
            _hashes_equal(decision.content_hash, r4_promotion_decision_hash(decision))
            and _hashes_equal(
                decision.policy.content_hash, r4_promotion_policy_hash(decision.policy)
            )
            and _hashes_equal(
                decision.trial.content_hash, r4_promotion_trial_seal_hash(decision.trial)
            )
            and _hashes_equal(
                decision.trial.portfolio_record.content_hash,
                r4_promotion_portfolio_record_seal_hash(decision.trial.portfolio_record),
            )
            and _hashes_equal(
                decision.trial.current_r3_attestation.content_hash,
                r4_promotion_r3_attestation_evidence_hash(decision.trial.current_r3_attestation),
            )
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        rebuilt == decision
        and seals_valid
        and R4PromotionDecisionIdentity.from_decision(decision) == requested
        and decision.outcome is R4PromotionDecisionOutcome.APPROVED
        and decision.recorded_at <= evaluated_at < decision.valid_until
    )


def _portfolio_is_exact(
    record: R4PromotionPortfolioRecordSeal,
    decision: R4PromotionDecision,
    evaluated_at: datetime,
) -> bool:
    try:
        sealed = _hashes_equal(
            record.content_hash,
            r4_promotion_portfolio_record_seal_hash(record),
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        sealed
        and record == decision.trial.portfolio_record
        and record.recorded_at <= evaluated_at < record.valid_until
    )


def _r3_is_exact(
    evidence: R4PromotionR3AttestationEvidence,
    decision: R4PromotionDecision,
    evaluated_at: datetime,
) -> bool:
    try:
        sealed = _hashes_equal(
            evidence.content_hash,
            r4_promotion_r3_attestation_evidence_hash(evidence),
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        sealed
        and evidence == decision.trial.current_r3_attestation
        and evidence.is_active_at(evaluated_at)
    )


def _observation_blockers(
    *,
    requested_active_decision: R4PromotionDecisionIdentity,
    active_decision: R4PromotionDecision | None,
    portfolio_result: R4PromotionPortfolioRecordSeal | None,
    current_r3_attestation: R4PromotionR3AttestationEvidence | None,
    policy: R4MonitoringPolicy | None,
    period_calendar: R4MonitoringPeriodCalendar | None,
    observations: tuple[R4MonitoringObservation, ...],
    evaluated_at: datetime,
) -> tuple[R4MonitoringBlockerCode, ...]:
    blockers: list[R4MonitoringBlockerCode] = []
    if not observations:
        return (R4MonitoringBlockerCode.OBSERVATIONS_MISSING,)
    if not isinstance(observations, tuple) or any(
        not isinstance(item, R4MonitoringObservation) for item in observations
    ):
        return (R4MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH,)
    try:
        ordered = tuple(
            sorted(
                observations, key=lambda item: (item.period_start, item.period_end, item.period_id)
            )
        )
    except (AttributeError, TypeError, ValueError):
        return (R4MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH,)
    identities = tuple((item.observation_id, item.observation_version) for item in ordered)
    if len(identities) != len(set(identities)):
        blockers.append(R4MonitoringBlockerCode.OBSERVATION_IDENTITY_DUPLICATE)
    period_ids = tuple(item.period_id for item in ordered)
    if len(period_ids) != len(set(period_ids)):
        blockers.append(R4MonitoringBlockerCode.OBSERVATION_PERIOD_DUPLICATE)
    completed_entries: tuple[R4MonitoringPeriodEntry, ...] = ()
    calendar_members: dict[str, R4MonitoringPeriodEntry] = {}
    if period_calendar is not None:
        completed_entries = tuple(
            item
            for item in sorted(
                period_calendar.entries,
                key=lambda value: (value.period_start, value.period_end, value.period_id),
            )
            if item.period_end <= evaluated_at
        )
        calendar_members = {item.period_id.lower(): item for item in period_calendar.entries}
        if not completed_entries or tuple(
            item.period_id.lower() for item in completed_entries
        ) != tuple(item.period_id.lower() for item in ordered):
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_PERIOD_COVERAGE_INCOMPLETE)
    for observation in ordered:
        try:
            recomputed_hash = r4_monitoring_observation_hash(observation)
        except (AttributeError, TypeError, ValueError):
            recomputed_hash = None
        if not _hashes_equal(observation.content_hash, recomputed_hash):
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH)
        member = calendar_members.get(
            observation.period_id.lower() if _is_hash(observation.period_id) else ""
        )
        if member is None or (
            observation.period_start,
            observation.period_end,
        ) != (member.period_start, member.period_end):
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_PERIOD_NOT_IN_CALENDAR)
        if observation.period_end > evaluated_at:
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_PERIOD_FROM_FUTURE)
        if policy is None:
            continue
        if (
            observation.active_decision != requested_active_decision
            or observation.policy_id != policy.policy_id
            or observation.policy_version != policy.policy_version
            or not _hashes_equal(observation.policy_hash, policy.content_hash)
            or observation.period_calendar_id != policy.expected_period_calendar_id
            or observation.period_calendar_version != policy.expected_period_calendar_version
            or not _hashes_equal(
                observation.period_calendar_hash,
                policy.expected_period_calendar_hash,
            )
        ):
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_BINDING_MISMATCH)
        if observation.source_owner != policy.expected_source_owner:
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_OWNER_MISMATCH)
        if portfolio_result is None or (
            observation.portfolio_record_id != portfolio_result.record_id
            or not _hashes_equal(observation.portfolio_record_hash, portfolio_result.record_hash)
            or not _hashes_equal(
                observation.portfolio_record_content_hash,
                portfolio_result.content_hash,
            )
        ):
            blockers.append(R4MonitoringBlockerCode.PORTFOLIO_BINDING_MISMATCH)
        if current_r3_attestation is None or not _hashes_equal(
            observation.r3_attestation_content_hash,
            current_r3_attestation.content_hash,
        ):
            blockers.append(R4MonitoringBlockerCode.R3_BINDING_MISMATCH)
        if observation.pit_manifest_id != policy.expected_pit_manifest_id or not _hashes_equal(
            observation.pit_manifest_hash,
            policy.expected_pit_manifest_hash,
        ):
            blockers.append(R4MonitoringBlockerCode.PIT_MANIFEST_MISMATCH)
        if not observation.evidence_ref.startswith(policy.expected_evidence_ref_prefix):
            blockers.append(R4MonitoringBlockerCode.EVIDENCE_REF_MISMATCH)
        if observation.label_protocol_version != policy.expected_label_protocol_version:
            blockers.append(R4MonitoringBlockerCode.LABEL_PROTOCOL_MISMATCH)
        if observation.recorded_at > evaluated_at or observation.available_at > evaluated_at:
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_FROM_FUTURE)
        if observation.valid_until <= evaluated_at:
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_STALE)
        metric_keys = tuple(item.metric_key for item in observation.metrics)
        if len(metric_keys) != len(set(metric_keys)):
            blockers.append(R4MonitoringBlockerCode.METRIC_DUPLICATE)
        if frozenset(metric_keys) != REQUIRED_R4_MONITORING_METRICS:
            blockers.append(R4MonitoringBlockerCode.METRIC_MISSING)
        threshold_by_key = {item.metric_key: item for item in policy.thresholds}
        for metric in observation.metrics:
            threshold = threshold_by_key.get(metric.metric_key)
            if threshold is None:
                blockers.append(R4MonitoringBlockerCode.METRIC_MISSING)
                continue
            if metric.unit != threshold.unit:
                blockers.append(R4MonitoringBlockerCode.METRIC_UNIT_MISMATCH)
            try:
                _require_metric_domain(metric.metric_key, metric.value, "metric.value")
            except (AttributeError, TypeError, ValueError):
                blockers.append(R4MonitoringBlockerCode.METRIC_DOMAIN_INVALID)
    if policy is not None:
        if len(ordered) < policy.minimum_observation_count:
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_COUNT_INSUFFICIENT)
        latest = ordered[-1]
        if evaluated_at - latest.period_end > timedelta(
            seconds=policy.maximum_observation_age_seconds
        ):
            blockers.append(R4MonitoringBlockerCode.OBSERVATION_STALE)
    if active_decision is None:
        blockers.append(R4MonitoringBlockerCode.ACTIVE_DECISION_MISSING)
    return tuple(dict.fromkeys(blockers))


def _blocked_assessment(
    *,
    active_decision: R4PromotionDecisionIdentity,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    active_decision_hash: str | None,
    policy_hash: str | None,
    evaluated_at: datetime,
    observations: tuple[R4MonitoringObservation, ...],
    blockers: tuple[R4MonitoringBlockerCode, ...],
) -> R4MonitoringAssessment:
    return R4MonitoringAssessment(
        active_decision=active_decision,
        requested_policy_id=requested_policy_id,
        requested_policy_version=requested_policy_version,
        expected_policy_hash=expected_policy_hash,
        active_decision_hash=(active_decision_hash if _is_hash(active_decision_hash) else None),
        policy_hash=policy_hash if _is_hash(policy_hash) else None,
        evaluated_at=evaluated_at,
        status=R4MonitoringAssessmentStatus.BLOCKED,
        observation_hashes=tuple(
            dict.fromkeys(
                item.content_hash
                for item in observations
                if isinstance(item, R4MonitoringObservation) and _is_hash(item.content_hash)
            )
        ),
        metric_results=(),
        blockers=blockers,
        label_drift_detected=False,
        data_drift_detected=False,
        retirement_review_required=False,
        review_reason_codes=(),
    )


def _assessment_hash(assessment: R4MonitoringAssessment) -> str:
    return _hash_payload(
        {
            "schema": "research-r4-monitoring-assessment.v1",
            "active_decision": _decision_identity_payload(assessment.active_decision),
            "requested_policy": [
                assessment.requested_policy_id,
                assessment.requested_policy_version,
                assessment.expected_policy_hash.lower(),
            ],
            "active_decision_hash": assessment.active_decision_hash,
            "policy_hash": assessment.policy_hash,
            "evaluated_at": _utc_text(assessment.evaluated_at),
            "status": assessment.status.value,
            "observation_hashes": list(assessment.observation_hashes),
            "metric_results": [
                {
                    "metric_key": item.metric_key.value,
                    "unit": item.unit,
                    "latest_value": _decimal_text(item.latest_value),
                    "breach_threshold": _decimal_text(item.breach_threshold),
                    "direction": item.direction.value,
                    "latest_breached": item.latest_breached,
                    "trailing_consecutive_breaches": item.trailing_consecutive_breaches,
                    "retirement_review_consecutive_breaches": (
                        item.retirement_review_consecutive_breaches
                    ),
                }
                for item in assessment.metric_results
            ],
            "blockers": [item.value for item in assessment.blockers],
            "label_drift_detected": assessment.label_drift_detected,
            "data_drift_detected": assessment.data_drift_detected,
            "retirement_review_required": assessment.retirement_review_required,
            "review_reason_codes": list(assessment.review_reason_codes),
            "automatic_retirement": False,
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_publish_current": True,
            "must_not_execute": True,
        }
    )


__all__ = [
    "REQUIRED_R4_MONITORING_METRICS",
    "R4MonitoringAssessment",
    "R4MonitoringAssessmentStatus",
    "R4MonitoringBlockerCode",
    "R4MonitoringMetricKey",
    "R4MonitoringMetricObservation",
    "R4MonitoringMetricResult",
    "R4MonitoringObservation",
    "R4MonitoringPeriodCalendar",
    "R4MonitoringPeriodEntry",
    "R4MonitoringPolicy",
    "R4MonitoringThreshold",
    "R4MonitoringThresholdDirection",
    "derive_r4_monitoring_period_id",
    "evaluate_r4_promotion_monitoring",
    "r4_monitoring_observation_hash",
    "r4_monitoring_period_calendar_hash",
    "r4_monitoring_policy_hash",
]
