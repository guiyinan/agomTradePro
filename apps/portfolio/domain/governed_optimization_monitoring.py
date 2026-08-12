"""Evaluate governed R8 post-promotion monitoring from exact owner evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
from .governed_optimization_monitoring_contracts import (
    MONITORING_ASSESSMENT_VERSION,
    ActiveGovernedOptimizationResultEvidence,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringPolicy,
    GovernedOptimizationMonitoringTarget,
    GovernedOptimizationMonitoringThreshold,
    OptimizationMonitoringMetricObservation,
    OptimizationMonitoringPeriod,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
    OptimizationPromotionSelector,
    active_result_evidence_hash,
    metric_observation_hash,
    monitoring_calendar_hash,
    monitoring_threshold_hash,
    period_observation_hash,
    source_evidence_hash,
)
from .governed_optimization_monitoring_metrics import (
    MonitoringAssessmentStatus,
    MonitoringBlockerCode,
    MonitoringMetricKey,
    MonitoringMetricResult,
    MonitoringMetricUnit,
    MonitoringSourceOwner,
    MonitoringThresholdDirection,
    OptimizationMonitoringOwnerMetricPayload,
    _enum_index,
    _require_exact_int,
)
from .optimization_input_receipt import GovernedOptimizationInputReceipt
from .optimization_research_result import GovernedOptimizationResearchResult


@dataclass(frozen=True)
class GovernedOptimizationMonitoringAssessment:
    """Recomputable, content-sealed internal monitoring assessment."""

    assessment_id: str
    assessment_version: str
    result_id: str
    result_hash: str
    policy_id: str
    policy_hash: str
    calendar_hash: str
    required_consecutive_breaches: int
    latest_period_id: str | None
    observation_hashes: tuple[str, ...]
    status: MonitoringAssessmentStatus
    metric_results: tuple[MonitoringMetricResult, ...]
    blocker_codes: tuple[MonitoringBlockerCode, ...]
    evaluated_at: datetime
    manual_retirement_review_required: bool
    automatic_retirement: bool
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool
    must_not_publish_current: bool
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
        required_consecutive_breaches: int,
        latest_period_id: str | None,
        observation_hashes: tuple[str, ...],
        status: MonitoringAssessmentStatus,
        metric_results: tuple[MonitoringMetricResult, ...],
        blocker_codes: tuple[MonitoringBlockerCode, ...],
        evaluated_at: datetime,
    ) -> GovernedOptimizationMonitoringAssessment:
        """Seal a status that is derivable from the included rule and results."""

        manual_review = status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
        digest = _monitoring_assessment_hash_values(
            result_id,
            result_hash,
            policy_id,
            policy_hash,
            calendar_hash,
            required_consecutive_breaches,
            latest_period_id,
            observation_hashes,
            status,
            metric_results,
            blocker_codes,
            evaluated_at,
            manual_review,
        )
        return cls(
            assessment_id=f"r8_monitoring_assessment:{digest[:24]}",
            assessment_version=MONITORING_ASSESSMENT_VERSION,
            result_id=result_id,
            result_hash=result_hash,
            policy_id=policy_id,
            policy_hash=policy_hash,
            calendar_hash=calendar_hash,
            required_consecutive_breaches=required_consecutive_breaches,
            latest_period_id=latest_period_id,
            observation_hashes=observation_hashes,
            status=status,
            metric_results=metric_results,
            blocker_codes=blocker_codes,
            evaluated_at=evaluated_at,
            manual_retirement_review_required=manual_review,
            automatic_retirement=False,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
            must_not_publish_current=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        require_token(self.assessment_id, "monitoring assessment_id")
        if self.assessment_version != MONITORING_ASSESSMENT_VERSION:
            raise ValueError("monitoring assessment version is unsupported")
        require_token(self.result_id, "monitoring assessment result_id")
        require_sha256(self.result_hash, "monitoring assessment result_hash")
        require_token(self.policy_id, "monitoring assessment policy_id")
        require_sha256(self.policy_hash, "monitoring assessment policy_hash")
        require_sha256(self.calendar_hash, "monitoring assessment calendar_hash")
        require_aware(self.evaluated_at, "monitoring assessment evaluated_at")
        if type(self.status) is not MonitoringAssessmentStatus:
            raise TypeError("monitoring assessment status is invalid")
        if type(self.metric_results) is not tuple or type(self.blocker_codes) is not tuple:
            raise TypeError("monitoring assessment collections must be tuples")
        if type(self.observation_hashes) is not tuple:
            raise TypeError("monitoring assessment observation hashes must be a tuple")
        for value in self.observation_hashes:
            require_sha256(value, "monitoring assessment observation hash")
        if len(set(self.observation_hashes)) != len(self.observation_hashes):
            raise ValueError("monitoring assessment observation hashes must be unique")
        for result in self.metric_results:
            if type(result) is not MonitoringMetricResult:
                raise TypeError("monitoring assessment metric result type is invalid")
            MonitoringMetricResult.__post_init__(result)
        if self.metric_results and tuple(item.metric_key for item in self.metric_results) != tuple(
            MonitoringMetricKey
        ):
            raise ValueError("monitoring assessment metric results must be canonical")
        for blocker in self.blocker_codes:
            if type(blocker) is not MonitoringBlockerCode:
                raise TypeError("monitoring assessment blocker type is invalid")
        if len(set(self.blocker_codes)) != len(self.blocker_codes):
            raise ValueError("monitoring assessment blocker codes must be unique")
        if self.status is MonitoringAssessmentStatus.BLOCKED:
            if not self.blocker_codes or self.metric_results or self.latest_period_id is not None:
                raise ValueError("blocked monitoring assessment shape is invalid")
            _require_exact_int(
                self.required_consecutive_breaches,
                "assessment required_consecutive_breaches",
                minimum=0,
                maximum=64,
            )
        else:
            if self.blocker_codes or len(self.metric_results) != len(MonitoringMetricKey):
                raise ValueError("available monitoring assessment shape is invalid")
            _require_exact_int(
                self.required_consecutive_breaches,
                "assessment required_consecutive_breaches",
                minimum=2,
                maximum=64,
            )
            latest_period_id = self.latest_period_id
            if latest_period_id is None:
                raise ValueError("available assessment requires latest_period_id")
            require_token(latest_period_id, "monitoring assessment latest_period_id")
            if not self.observation_hashes:
                raise ValueError("available assessment requires observation hashes")
            expected_status = _derive_assessment_status(
                self.metric_results,
                self.required_consecutive_breaches,
                latest_period_id,
            )
            if self.status is not expected_status:
                raise ValueError("monitoring assessment status does not match sealed evidence")
        if self.manual_retirement_review_required != (
            self.status is MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
        ):
            raise ValueError("manual retirement review flag mismatch")
        for flag_name, flag_value in (
            ("automatic_retirement", self.automatic_retirement),
            ("research_only", self.research_only),
            ("must_not_execute", self.must_not_execute),
            ("must_not_use_for_decision", self.must_not_use_for_decision),
            ("must_not_publish_current", self.must_not_publish_current),
        ):
            if type(flag_value) is not bool:
                raise TypeError(f"monitoring assessment {flag_name} must be bool")
        if self.automatic_retirement or not (
            self.research_only
            and self.must_not_execute
            and self.must_not_use_for_decision
            and self.must_not_publish_current
        ):
            raise ValueError("R8 monitoring assessment publication/action flags are invalid")
        require_sha256(self.content_hash, "monitoring assessment content_hash")
        if self.content_hash != monitoring_assessment_hash(self):
            raise ValueError("monitoring assessment content hash mismatch")
        if self.assessment_id != f"r8_monitoring_assessment:{self.content_hash[:24]}":
            raise ValueError("monitoring assessment identity mismatch")

    def validated_copy(
        self,
        *,
        policy: GovernedOptimizationMonitoringPolicy,
        calendar: GovernedOptimizationMonitoringCalendar,
        observations: tuple[OptimizationMonitoringPeriodObservation, ...],
    ) -> GovernedOptimizationMonitoringAssessment:
        """Revalidate policy rule, calendar membership, observations, and outcome."""

        self.__post_init__()
        GovernedOptimizationMonitoringPolicy.__post_init__(policy)
        GovernedOptimizationMonitoringCalendar.__post_init__(calendar)
        if (
            self.result_id != policy.target.result_id
            or self.result_hash != policy.target.result_hash
            or self.policy_id != policy.policy_id
            or self.policy_hash != policy.content_hash
            or self.calendar_hash != calendar.content_hash
            or self.required_consecutive_breaches != policy.required_consecutive_breaches
        ):
            raise ValueError("monitoring assessment policy binding mismatch")
        if self.status is MonitoringAssessmentStatus.BLOCKED:
            return self
        for observation in observations:
            OptimizationMonitoringPeriodObservation.__post_init__(observation)
        if (
            tuple(item.period_id for item in observations)
            != tuple(item.period_id for item in calendar.periods)
            or tuple(item.content_hash for item in observations) != self.observation_hashes
            or observations[-1].period_id != self.latest_period_id
            or derive_monitoring_metric_results(policy, calendar, observations)
            != self.metric_results
        ):
            raise ValueError("monitoring assessment observation binding mismatch")
        return self


def _derive_assessment_status(
    metric_results: tuple[MonitoringMetricResult, ...],
    required_consecutive_breaches: int,
    latest_period_id: str | None,
) -> MonitoringAssessmentStatus:
    drift = any(
        item.metric_key
        in {MonitoringMetricKey.LABEL_DRIFT_RATE, MonitoringMetricKey.DATA_DRIFT_SCORE}
        and item.breached_period_ids
        for item in metric_results
    )
    consecutive = any(
        item.trailing_consecutive_breaches >= required_consecutive_breaches
        for item in metric_results
    )
    latest = latest_period_id is not None and any(
        latest_period_id in item.breached_period_ids for item in metric_results
    )
    if drift or consecutive:
        return MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    return MonitoringAssessmentStatus.BREACHED if latest else MonitoringAssessmentStatus.HEALTHY


def monitoring_assessment_hash(assessment: GovernedOptimizationMonitoringAssessment) -> str:
    """Hash the complete recomputable assessment and non-publication flags."""

    return _monitoring_assessment_hash_values(
        assessment.result_id,
        assessment.result_hash,
        assessment.policy_id,
        assessment.policy_hash,
        assessment.calendar_hash,
        assessment.required_consecutive_breaches,
        assessment.latest_period_id,
        assessment.observation_hashes,
        assessment.status,
        assessment.metric_results,
        assessment.blocker_codes,
        assessment.evaluated_at,
        assessment.manual_retirement_review_required,
    )


def _monitoring_assessment_hash_values(
    result_id: str,
    result_hash: str,
    policy_id: str,
    policy_hash: str,
    calendar_hash: str,
    required_consecutive_breaches: int,
    latest_period_id: str | None,
    observation_hashes: tuple[str, ...],
    status: MonitoringAssessmentStatus,
    metric_results: tuple[MonitoringMetricResult, ...],
    blocker_codes: tuple[MonitoringBlockerCode, ...],
    evaluated_at: datetime,
    manual_retirement_review_required: bool,
) -> str:
    return hash_components(
        MONITORING_ASSESSMENT_VERSION,
        result_id,
        result_hash,
        policy_id,
        policy_hash,
        calendar_hash,
        str(required_consecutive_breaches),
        latest_period_id or "blocked:no-latest-period",
        *observation_hashes,
        status.value,
        *(
            f"{item.metric_key.value}|{decimal_text(item.latest_value)}|"
            f"{decimal_text(item.threshold)}|{','.join(item.breached_period_ids)}|"
            f"{item.trailing_consecutive_breaches}"
            for item in metric_results
        ),
        *(item.value for item in blocker_codes),
        utc_text(evaluated_at),
        str(manual_retirement_review_required),
        "automatic_retirement:false",
        "research_only",
        "must_not_execute",
        "must_not_use_for_decision",
        "must_not_publish_current",
    )


def evaluate_governed_optimization_monitoring(
    *,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    active_result: ActiveGovernedOptimizationResultEvidence | None,
    receipt: GovernedOptimizationInputReceipt | None,
    current_upstream_promotions: tuple[ExactPromotionAttestation, ...],
    policy: GovernedOptimizationMonitoringPolicy | None,
    calendar: GovernedOptimizationMonitoringCalendar | None,
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    observations: tuple[OptimizationMonitoringPeriodObservation, ...],
    evaluated_at: datetime,
) -> GovernedOptimizationMonitoringAssessment:
    """Recompute health and manual review need from exact owner evidence."""

    for label, value in (
        ("requested_policy_id", requested_policy_id),
        ("requested_policy_version", requested_policy_version),
    ):
        require_token(value, label)
    require_sha256(expected_policy_hash, "expected_policy_hash")
    require_aware(evaluated_at, "monitoring evaluated_at")
    blockers: list[MonitoringBlockerCode] = []
    _validate_policy_and_calendar(
        policy=policy,
        calendar=calendar,
        requested_policy_id=requested_policy_id,
        requested_policy_version=requested_policy_version,
        expected_policy_hash=expected_policy_hash,
        evaluated_at=evaluated_at,
        blockers=blockers,
    )
    target = (
        policy.target
        if type(policy) is GovernedOptimizationMonitoringPolicy
        and type(policy.target) is GovernedOptimizationMonitoringTarget
        else None
    )
    if target is not None:
        _validate_active_result(
            active_result=active_result,
            target=target,
            evaluated_at=evaluated_at,
            blockers=blockers,
        )
        _validate_receipt(
            receipt=receipt,
            active_result=active_result,
            target=target,
            evaluated_at=evaluated_at,
            blockers=blockers,
        )
        _validate_upstream_promotions(
            requested=target.upstream_promotions,
            current=current_upstream_promotions,
            receipt=receipt,
            evaluated_at=evaluated_at,
            blockers=blockers,
        )
    if (
        policy is not None
        and calendar is not None
        and receipt is not None
        and active_result is not None
    ):
        _validate_period_evidence(
            result=active_result.result,
            receipt=receipt,
            policy=policy,
            calendar=calendar,
            portfolio_evidence=portfolio_evidence,
            broker_evidence=broker_evidence,
            observations=observations,
            evaluated_at=evaluated_at,
            blockers=blockers,
        )
    if blockers:
        return _assessment(
            result_id=(
                target.result_id if target is not None else "r8-monitoring-target:unavailable"
            ),
            result_hash=(target.result_hash if target is not None else "0" * 64),
            policy_id=requested_policy_id,
            policy_hash=expected_policy_hash,
            calendar_hash=(calendar.content_hash if calendar is not None else "0" * 64),
            required_consecutive_breaches=(
                policy.required_consecutive_breaches
                if type(policy) is GovernedOptimizationMonitoringPolicy
                else 0
            ),
            latest_period_id=None,
            observation_hashes=(),
            status=MonitoringAssessmentStatus.BLOCKED,
            metric_results=(),
            blocker_codes=tuple(sorted(set(blockers), key=lambda item: item.value)),
            evaluated_at=evaluated_at,
        )
    if policy is None or calendar is None:
        raise AssertionError("validated monitoring evidence unexpectedly missing")
    metric_results = derive_monitoring_metric_results(policy, calendar, observations)
    latest_period_id = calendar.periods[-1].period_id
    status = _derive_assessment_status(
        metric_results,
        policy.required_consecutive_breaches,
        latest_period_id,
    )
    return _assessment(
        result_id=policy.target.result_id,
        result_hash=policy.target.result_hash,
        policy_id=requested_policy_id,
        policy_hash=expected_policy_hash,
        calendar_hash=calendar.content_hash,
        required_consecutive_breaches=policy.required_consecutive_breaches,
        latest_period_id=latest_period_id,
        observation_hashes=tuple(item.content_hash for item in observations),
        status=status,
        metric_results=metric_results,
        blocker_codes=(),
        evaluated_at=evaluated_at,
    )


def _validate_active_result(
    *,
    active_result: ActiveGovernedOptimizationResultEvidence | None,
    target: GovernedOptimizationMonitoringTarget,
    evaluated_at: datetime,
    blockers: list[MonitoringBlockerCode],
) -> None:
    if active_result is None:
        blockers.append(MonitoringBlockerCode.ACTIVE_RESULT_UNAVAILABLE)
        return
    try:
        ActiveGovernedOptimizationResultEvidence.__post_init__(active_result)
    except (AttributeError, TypeError, ValueError):
        blockers.append(MonitoringBlockerCode.ACTIVE_RESULT_SUBSTITUTED)
        return
    result = active_result.result
    if (
        result.problem_id != target.optimization_scope_id
        or result.problem_hash != target.optimization_scope_hash
        or result.result_id != target.result_id
        or result.result_version != target.result_version
        or result.content_hash != target.result_hash
        or active_result.promotion_event_id != target.r8_promotion_event_id
        or active_result.promotion_event_hash != target.r8_promotion_event_hash
    ):
        blockers.append(MonitoringBlockerCode.ACTIVE_RESULT_SUBSTITUTED)
    promotion = active_result.lifecycle_events[-1].promotion_attestation
    if promotion is None:
        blockers.append(MonitoringBlockerCode.ACTIVE_RESULT_INACTIVE)
    elif not (
        result.evaluated_at <= promotion.approved_at <= evaluated_at < result.valid_until
        and evaluated_at < promotion.valid_until
        and promotion.retired_at is None
    ):
        blockers.append(MonitoringBlockerCode.ACTIVE_RESULT_FUTURE_OR_EXPIRED)


def _validate_receipt(
    *,
    receipt: GovernedOptimizationInputReceipt | None,
    active_result: ActiveGovernedOptimizationResultEvidence | None,
    target: GovernedOptimizationMonitoringTarget,
    evaluated_at: datetime,
    blockers: list[MonitoringBlockerCode],
) -> None:
    if receipt is None:
        blockers.append(MonitoringBlockerCode.RECEIPT_UNAVAILABLE)
        return
    try:
        GovernedOptimizationInputReceipt.__post_init__(receipt)
    except (AttributeError, TypeError, ValueError):
        blockers.append(MonitoringBlockerCode.RECEIPT_SUBSTITUTED)
        return
    if (
        receipt.receipt_id != target.receipt_id
        or receipt.receipt_version != target.receipt_version
        or receipt.content_hash != target.receipt_hash
        or receipt.recorded_at > evaluated_at
    ):
        blockers.append(MonitoringBlockerCode.RECEIPT_SUBSTITUTED)
    if active_result is not None:
        result = active_result.result
        if (
            result.input_receipt_id != receipt.receipt_id
            or result.input_receipt_hash != receipt.content_hash
            or result.input_receipt_schema_version != receipt.receipt_version
            or result.input_set_id != receipt.input_set.input_set_id
            or result.input_set_hash != receipt.input_set.content_hash
        ):
            blockers.append(MonitoringBlockerCode.RECEIPT_SUBSTITUTED)


def _validate_upstream_promotions(
    *,
    requested: tuple[OptimizationPromotionSelector, ...],
    current: tuple[ExactPromotionAttestation, ...],
    receipt: GovernedOptimizationInputReceipt | None,
    evaluated_at: datetime,
    blockers: list[MonitoringBlockerCode],
) -> None:
    expected_capabilities = ("r3", "r4", "r5")
    try:
        if type(requested) is not tuple:
            raise TypeError
        for selector in requested:
            if type(selector) is not OptimizationPromotionSelector:
                raise TypeError
            OptimizationPromotionSelector.__post_init__(selector)
        if tuple(item.capability_key for item in requested) != expected_capabilities:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        blockers.append(MonitoringBlockerCode.UPSTREAM_PROMOTION_SUBSTITUTED)
        return
    if type(current) is not tuple or len(current) != 3 or receipt is None:
        blockers.append(MonitoringBlockerCode.UPSTREAM_PROMOTION_UNAVAILABLE)
        return
    receipt_by_key = {item.capability_key: item for item in receipt.input_set.promotions}
    current_by_key: dict[str, ExactPromotionAttestation] = {}
    try:
        for promotion in current:
            if type(promotion) is not ExactPromotionAttestation:
                raise TypeError
            ExactPromotionAttestation.__post_init__(promotion)
            current_by_key[promotion.capability_key] = promotion
    except (AttributeError, TypeError, ValueError):
        blockers.append(MonitoringBlockerCode.UPSTREAM_PROMOTION_SUBSTITUTED)
        return
    if (
        tuple(sorted(current_by_key)) != expected_capabilities
        or tuple(sorted(receipt_by_key)) != expected_capabilities
    ):
        blockers.append(MonitoringBlockerCode.UPSTREAM_PROMOTION_UNAVAILABLE)
        return
    for selector in requested:
        promotion = current_by_key[selector.capability_key]
        if (
            OptimizationPromotionSelector.from_attestation(promotion) != selector
            or receipt_by_key[selector.capability_key] != promotion
        ):
            blockers.append(MonitoringBlockerCode.UPSTREAM_PROMOTION_SUBSTITUTED)
        if not (
            promotion.approved_at <= evaluated_at < promotion.valid_until
            and promotion.retired_at is None
        ):
            blockers.append(MonitoringBlockerCode.UPSTREAM_PROMOTION_INACTIVE)


def _validate_policy_and_calendar(
    *,
    policy: GovernedOptimizationMonitoringPolicy | None,
    calendar: GovernedOptimizationMonitoringCalendar | None,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    evaluated_at: datetime,
    blockers: list[MonitoringBlockerCode],
) -> None:
    if policy is None:
        blockers.append(MonitoringBlockerCode.POLICY_UNAVAILABLE)
        return
    try:
        GovernedOptimizationMonitoringPolicy.__post_init__(policy)
    except (AttributeError, TypeError, ValueError):
        blockers.append(MonitoringBlockerCode.POLICY_SUBSTITUTED)
        return
    if (
        policy.policy_id != requested_policy_id
        or policy.policy_version != requested_policy_version
        or policy.content_hash != expected_policy_hash
    ):
        blockers.append(MonitoringBlockerCode.POLICY_SUBSTITUTED)
    if not policy.recorded_at <= evaluated_at < policy.valid_until:
        blockers.append(MonitoringBlockerCode.POLICY_INACTIVE)
    if calendar is None:
        blockers.append(MonitoringBlockerCode.CALENDAR_UNAVAILABLE)
        return
    try:
        GovernedOptimizationMonitoringCalendar.__post_init__(calendar)
    except (AttributeError, TypeError, ValueError):
        blockers.append(MonitoringBlockerCode.CALENDAR_SUBSTITUTED)
        return
    if (
        calendar.calendar_id != policy.calendar_id
        or calendar.calendar_version != policy.calendar_version
        or calendar.content_hash != policy.calendar_hash
        or calendar.recorded_at != policy.calendar_recorded_at
        or calendar.periods[0].start_at != policy.calendar_first_period_start_at
        or not (calendar.recorded_at <= policy.recorded_at <= calendar.periods[0].start_at)
    ):
        blockers.append(MonitoringBlockerCode.CALENDAR_SUBSTITUTED)
    if len(calendar.periods) < policy.minimum_complete_periods or any(
        period.end_at > evaluated_at for period in calendar.periods
    ):
        blockers.append(MonitoringBlockerCode.CALENDAR_INCOMPLETE)
    elif evaluated_at - calendar.periods[-1].end_at > timedelta(
        seconds=policy.max_period_lag_seconds
    ):
        blockers.append(MonitoringBlockerCode.CALENDAR_STALE)
    if policy.recorded_at > calendar.periods[0].start_at or evaluated_at >= calendar.valid_until:
        blockers.append(MonitoringBlockerCode.CALENDAR_STALE)


def _validate_period_evidence(
    *,
    result: GovernedOptimizationResearchResult,
    receipt: GovernedOptimizationInputReceipt,
    policy: GovernedOptimizationMonitoringPolicy,
    calendar: GovernedOptimizationMonitoringCalendar,
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
    observations: tuple[OptimizationMonitoringPeriodObservation, ...],
    evaluated_at: datetime,
    blockers: list[MonitoringBlockerCode],
) -> None:
    period_ids = tuple(item.period_id for item in calendar.periods)
    if (
        type(portfolio_evidence) is not tuple
        or type(broker_evidence) is not tuple
        or tuple(item.period_id for item in portfolio_evidence) != period_ids
        or tuple(item.period_id for item in broker_evidence) != period_ids
    ):
        blockers.append(MonitoringBlockerCode.SOURCE_EVIDENCE_INCOMPLETE)
        return
    evidence_by_key: dict[
        tuple[MonitoringSourceOwner, str], OptimizationMonitoringSourceEvidence
    ] = {}
    period_by_id = {item.period_id: item for item in calendar.periods}
    for expected_owner, evidence_items in (
        (MonitoringSourceOwner.PORTFOLIO, portfolio_evidence),
        (MonitoringSourceOwner.BROKER_EXECUTION, broker_evidence),
    ):
        for evidence in evidence_items:
            try:
                if type(evidence) is not OptimizationMonitoringSourceEvidence:
                    raise TypeError
                OptimizationMonitoringSourceEvidence.__post_init__(evidence)
            except (AttributeError, TypeError, ValueError):
                blockers.append(MonitoringBlockerCode.SOURCE_EVIDENCE_SUBSTITUTED)
                continue
            if (
                evidence.owner is not expected_owner
                or evidence.result_id != result.result_id
                or evidence.result_hash != result.content_hash
                or evidence.receipt_id != receipt.receipt_id
                or evidence.receipt_hash != receipt.content_hash
            ):
                blockers.append(MonitoringBlockerCode.SOURCE_EVIDENCE_SUBSTITUTED)
            period = period_by_id[evidence.period_id]
            max_available = period.end_at + timedelta(seconds=policy.max_evidence_delay_seconds)
            if (
                not period.start_at <= evidence.observed_at <= period.end_at
                or not evidence.observed_at <= evidence.available_at <= max_available
                or evidence.available_at > evaluated_at
            ):
                blockers.append(MonitoringBlockerCode.SOURCE_EVIDENCE_FUTURE_OR_STALE)
            evidence_by_key[(expected_owner, evidence.period_id)] = evidence
    if (
        type(observations) is not tuple
        or tuple(item.period_id for item in observations) != period_ids
    ):
        blockers.append(MonitoringBlockerCode.OBSERVATION_INCOMPLETE)
        return
    thresholds = {item.metric_key: item for item in policy.thresholds}
    for observation in observations:
        try:
            if type(observation) is not OptimizationMonitoringPeriodObservation:
                raise TypeError
            OptimizationMonitoringPeriodObservation.__post_init__(observation)
        except (AttributeError, TypeError, ValueError):
            blockers.append(MonitoringBlockerCode.OBSERVATION_SUBSTITUTED)
            continue
        for metric in observation.metrics:
            threshold = thresholds[metric.metric_key]
            metric_evidence = evidence_by_key.get((metric.source_owner, observation.period_id))
            owner_payload = (
                None
                if metric_evidence is None
                else next(
                    (
                        item
                        for item in metric_evidence.metric_payload
                        if item.metric_key is metric.metric_key
                    ),
                    None,
                )
            )
            if (
                metric_evidence is None
                or owner_payload is None
                or metric.unit is not threshold.unit
                or metric.source_owner is not threshold.source_owner
                or metric.evidence_namespace != threshold.evidence_namespace
                or metric.unit is not owner_payload.unit
                or metric.value != owner_payload.value
                or metric.evidence_namespace != owner_payload.evidence_namespace
                or metric.source_evidence_id != metric_evidence.evidence_id
                or metric.source_evidence_hash != metric_evidence.content_hash
                or metric.observed_at != metric_evidence.observed_at
                or metric.available_at != metric_evidence.available_at
            ):
                blockers.append(MonitoringBlockerCode.OBSERVATION_SUBSTITUTED)


def derive_monitoring_metric_results(
    policy: GovernedOptimizationMonitoringPolicy,
    calendar: GovernedOptimizationMonitoringCalendar,
    observations: tuple[OptimizationMonitoringPeriodObservation, ...],
) -> tuple[MonitoringMetricResult, ...]:
    observations_by_period = {item.period_id: item for item in observations}
    results: list[MonitoringMetricResult] = []
    for threshold in policy.thresholds:
        breaches: list[str] = []
        breach_flags: list[bool] = []
        latest_value = Decimal("0")
        for period in calendar.periods:
            observation = observations_by_period[period.period_id]
            metric = observation.metrics[_enum_index(threshold.metric_key)]
            latest_value = metric.value
            breached = (
                metric.value < threshold.threshold
                if threshold.direction is MonitoringThresholdDirection.MINIMUM
                else metric.value > threshold.threshold
            )
            breach_flags.append(breached)
            if breached:
                breaches.append(period.period_id)
        trailing = 0
        for breached in reversed(breach_flags):
            if not breached:
                break
            trailing += 1
        results.append(
            MonitoringMetricResult(
                metric_key=threshold.metric_key,
                latest_value=latest_value,
                threshold=threshold.threshold,
                breached_period_ids=tuple(breaches),
                trailing_consecutive_breaches=trailing,
            )
        )
    return tuple(results)


def _assessment(
    *,
    result_id: str,
    result_hash: str,
    policy_id: str,
    policy_hash: str,
    calendar_hash: str,
    required_consecutive_breaches: int,
    latest_period_id: str | None,
    observation_hashes: tuple[str, ...],
    status: MonitoringAssessmentStatus,
    metric_results: tuple[MonitoringMetricResult, ...],
    blocker_codes: tuple[MonitoringBlockerCode, ...],
    evaluated_at: datetime,
) -> GovernedOptimizationMonitoringAssessment:
    return GovernedOptimizationMonitoringAssessment.create(
        result_id=result_id,
        result_hash=result_hash,
        policy_id=policy_id,
        policy_hash=policy_hash,
        calendar_hash=calendar_hash,
        required_consecutive_breaches=required_consecutive_breaches,
        latest_period_id=latest_period_id,
        observation_hashes=observation_hashes,
        status=status,
        metric_results=metric_results,
        blocker_codes=blocker_codes,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "ActiveGovernedOptimizationResultEvidence",
    "GovernedOptimizationMonitoringAssessment",
    "GovernedOptimizationMonitoringCalendar",
    "GovernedOptimizationMonitoringPolicy",
    "GovernedOptimizationMonitoringTarget",
    "GovernedOptimizationMonitoringThreshold",
    "MonitoringAssessmentStatus",
    "MonitoringBlockerCode",
    "MonitoringMetricKey",
    "MonitoringMetricResult",
    "MonitoringMetricUnit",
    "MonitoringSourceOwner",
    "MonitoringThresholdDirection",
    "OptimizationMonitoringMetricObservation",
    "OptimizationMonitoringOwnerMetricPayload",
    "OptimizationMonitoringPeriod",
    "OptimizationMonitoringPeriodObservation",
    "OptimizationMonitoringSourceEvidence",
    "OptimizationPromotionSelector",
    "active_result_evidence_hash",
    "evaluate_governed_optimization_monitoring",
    "metric_observation_hash",
    "monitoring_assessment_hash",
    "monitoring_calendar_hash",
    "monitoring_threshold_hash",
    "period_observation_hash",
    "source_evidence_hash",
]
