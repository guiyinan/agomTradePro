"""Exact Research-owned R1 forecast promotion policy and decision evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult


class R1PromotionPolicyStatus(str, Enum):
    """Owner-controlled policy availability."""

    ACTIVE = "active"


class R1PromotionTrialState(str, Enum):
    """Typed state derived exclusively from an Equity trial result."""

    ELIGIBLE_FOR_PROMOTION = "eligible_for_promotion"
    NOT_ELIGIBLE = "not_eligible"


class R1PromotionDecisionOutcome(str, Enum):
    """Automatically derived Research decision outcome."""

    APPROVED = "approved"
    REJECTED = "rejected"


class R1PromotionGateCode(str, Enum):
    """Typed Research gates evaluated over one complete Equity trial."""

    REQUIRED_TRIAL_STATE = "required_trial_state"
    MINIMUM_METRIC_COVERAGE = "minimum_metric_coverage"
    ALL_METRIC_COMPARISONS_PASS = "all_metric_comparisons_pass"
    ALL_INVALIDATION_OUTCOMES_PASS = "all_invalidation_outcomes_pass"


def _require_token(value: str, field_name: str) -> None:
    if not value or len(value) > 192 or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_unit_interval(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or not Decimal("0") <= value <= 1:
        raise ValueError(f"{field_name} must be a finite Decimal within [0, 1]")


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("canonical decimal must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "canonical datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _promotion_scope_payload(
    *,
    owner: str,
    capability: str,
    purpose: str,
    subject_code: str,
    industry_code: str,
    candidate_scenario: str,
    horizon_quarters: int,
    calendar_schedule_hash: str,
    metric_codes: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema": "research-r1-promotion-scope.v1",
        "authority": [owner, capability, purpose],
        "subject": [subject_code, industry_code, candidate_scenario],
        "horizon_quarters": horizon_quarters,
        "calendar_schedule_hash": calendar_schedule_hash,
        "metric_codes": list(metric_codes),
    }


@dataclass(frozen=True)
class R1PromotionScope:
    """Stable semantic stream scope derived from exact Equity trial evidence."""

    scope_id: str
    owner: str
    capability: str
    purpose: str
    subject_code: str
    industry_code: str
    candidate_scenario: str
    horizon_quarters: int
    calendar_schedule_hash: str
    metric_codes: tuple[str, ...]
    content_hash: str

    @classmethod
    def from_result(cls, result: ForecastBaselineTrialResult) -> R1PromotionScope:
        """Derive a deterministic scope without caller-provided grouping keys."""

        if not result.forecasts:
            raise ValueError("R1 promotion scope requires forecast evidence")
        first = result.forecasts[0]
        if any(
            item.subject_code != first.subject_code
            or item.industry_code != first.industry_code
            or item.candidate_scenario is not first.candidate_scenario
            for item in result.forecasts
        ):
            raise ValueError("R1 promotion forecasts cross semantic scopes")
        if (
            result.actual_manifest.subject_code != first.subject_code
            or result.actual_manifest.industry_code != first.industry_code
        ):
            raise ValueError("R1 promotion actual manifest crosses the forecast scope")
        metric_codes = tuple(sorted(result.metric_evaluation_order))
        horizon_quarters = max(item.horizon_quarters for item in result.forecasts)
        digest = _hash_payload(
            _promotion_scope_payload(
                owner="research",
                capability="r1",
                purpose="valuation",
                subject_code=first.subject_code,
                industry_code=first.industry_code,
                candidate_scenario=first.candidate_scenario.value,
                horizon_quarters=horizon_quarters,
                calendar_schedule_hash=result.research_trial.calendar_schedule_hash,
                metric_codes=metric_codes,
            )
        )
        return cls(
            scope_id=f"r1v:{digest}",
            owner="research",
            capability="r1",
            purpose="valuation",
            subject_code=first.subject_code,
            industry_code=first.industry_code,
            candidate_scenario=first.candidate_scenario.value,
            horizon_quarters=horizon_quarters,
            calendar_schedule_hash=result.research_trial.calendar_schedule_hash,
            metric_codes=metric_codes,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R1 promotion scope_id")
        if self.owner != "research" or self.capability != "r1" or self.purpose != "valuation":
            raise ValueError("R1 promotion scope authority is invalid")
        for field_name, value in (
            ("subject_code", self.subject_code),
            ("industry_code", self.industry_code),
            ("candidate_scenario", self.candidate_scenario),
        ):
            _require_token(value, f"R1 promotion scope {field_name}")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters < 1:
            raise ValueError("R1 promotion scope horizon_quarters must be positive")
        _require_hash(self.calendar_schedule_hash, "R1 promotion scope calendar_schedule_hash")
        if not self.metric_codes or self.metric_codes != tuple(sorted(set(self.metric_codes))):
            raise ValueError("R1 promotion scope metric_codes must be unique and ordered")
        for metric_code in self.metric_codes:
            _require_token(metric_code, "R1 promotion scope metric_code")
        _require_hash(self.content_hash, "R1 promotion scope content_hash")
        expected_hash = r1_promotion_scope_hash(self)
        if self.content_hash != expected_hash or self.scope_id != f"r1v:{expected_hash}":
            raise ValueError("R1 promotion scope identity or content hash mismatch")


def r1_promotion_scope_hash(scope: R1PromotionScope) -> str:
    """Recompute the canonical semantic scope digest."""

    return _hash_payload(
        _promotion_scope_payload(
            owner=scope.owner,
            capability=scope.capability,
            purpose=scope.purpose,
            subject_code=scope.subject_code,
            industry_code=scope.industry_code,
            candidate_scenario=scope.candidate_scenario,
            horizon_quarters=scope.horizon_quarters,
            calendar_schedule_hash=scope.calendar_schedule_hash,
            metric_codes=scope.metric_codes,
        )
    )


@dataclass(frozen=True)
class R1ForecastPromotionPolicy:
    """Versioned Research policy governing one exact R1 valuation trial."""

    policy_id: str
    policy_version: str
    owner: str
    capability: str
    purpose: str
    promotion_scope: R1PromotionScope
    status: R1PromotionPolicyStatus
    required_trial_state: R1PromotionTrialState
    minimum_metric_coverage: Decimal
    require_all_metric_comparisons_pass: bool
    require_all_invalidation_outcomes_pass: bool
    decision_validity_seconds: int
    approved_at: datetime
    recorded_at: datetime
    active_from: datetime
    active_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        owner: str,
        capability: str,
        purpose: str,
        promotion_scope: R1PromotionScope,
        status: R1PromotionPolicyStatus,
        required_trial_state: R1PromotionTrialState,
        minimum_metric_coverage: Decimal,
        require_all_metric_comparisons_pass: bool,
        require_all_invalidation_outcomes_pass: bool,
        decision_validity_seconds: int,
        approved_at: datetime,
        recorded_at: datetime,
        active_from: datetime,
        active_until: datetime,
    ) -> R1ForecastPromotionPolicy:
        """Seal owner policy fields without applying an implicit default."""

        digest = _hash_payload(
            _promotion_policy_payload(
                policy_id=policy_id,
                policy_version=policy_version,
                owner=owner,
                capability=capability,
                purpose=purpose,
                promotion_scope=promotion_scope,
                status=status,
                required_trial_state=required_trial_state,
                minimum_metric_coverage=minimum_metric_coverage,
                require_all_metric_comparisons_pass=require_all_metric_comparisons_pass,
                require_all_invalidation_outcomes_pass=(require_all_invalidation_outcomes_pass),
                decision_validity_seconds=decision_validity_seconds,
                approved_at=approved_at,
                recorded_at=recorded_at,
                active_from=active_from,
                active_until=active_until,
            )
        )
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            owner=owner,
            capability=capability,
            purpose=purpose,
            promotion_scope=promotion_scope,
            status=status,
            required_trial_state=required_trial_state,
            minimum_metric_coverage=minimum_metric_coverage,
            require_all_metric_comparisons_pass=require_all_metric_comparisons_pass,
            require_all_invalidation_outcomes_pass=require_all_invalidation_outcomes_pass,
            decision_validity_seconds=decision_validity_seconds,
            approved_at=approved_at,
            recorded_at=recorded_at,
            active_from=active_from,
            active_until=active_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate Research authority, receipt time and canonical content hash."""

        _require_token(self.policy_id, "R1 promotion policy_id")
        _require_token(self.policy_version, "R1 promotion policy_version")
        if self.owner != "research" or self.capability != "r1" or self.purpose != "valuation":
            raise ValueError("R1 promotion policy authority is invalid")
        if (
            self.promotion_scope.owner != self.owner
            or self.promotion_scope.capability != self.capability
            or self.promotion_scope.purpose != self.purpose
        ):
            raise ValueError("R1 promotion policy scope authority is invalid")
        if self.status is not R1PromotionPolicyStatus.ACTIVE:
            raise ValueError("R1 promotion policy must be active")
        if self.required_trial_state is not R1PromotionTrialState.ELIGIBLE_FOR_PROMOTION:
            raise ValueError("R1 promotion policy must require an eligible trial")
        _require_unit_interval(self.minimum_metric_coverage, "minimum_metric_coverage")
        if (
            type(self.require_all_metric_comparisons_pass) is not bool
            or type(self.require_all_invalidation_outcomes_pass) is not bool
        ):
            raise ValueError("R1 promotion policy gates must be booleans")
        if not (
            self.require_all_metric_comparisons_pass and self.require_all_invalidation_outcomes_pass
        ):
            raise ValueError("active R1 promotion policy cannot weaken Equity trial gates")
        if (
            isinstance(self.decision_validity_seconds, bool)
            or self.decision_validity_seconds < 1
            or self.decision_validity_seconds > 31_536_000
        ):
            raise ValueError("decision_validity_seconds must be within one year")
        for field_name, value in (
            ("policy approved_at", self.approved_at),
            ("policy recorded_at", self.recorded_at),
            ("policy active_from", self.active_from),
            ("policy active_until", self.active_until),
        ):
            _require_aware(value, field_name)
        if not self.approved_at <= self.recorded_at <= self.active_from < self.active_until:
            raise ValueError("R1 promotion policy receipt/active window is invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R1 promotion policy must remain research-only")
        _require_hash(self.content_hash, "R1 promotion policy content_hash")
        if self.content_hash != r1_forecast_promotion_policy_hash(self):
            raise ValueError("R1 promotion policy content hash mismatch")


def _promotion_policy_payload(
    *,
    policy_id: str,
    policy_version: str,
    owner: str,
    capability: str,
    purpose: str,
    promotion_scope: R1PromotionScope,
    status: R1PromotionPolicyStatus,
    required_trial_state: R1PromotionTrialState,
    minimum_metric_coverage: Decimal,
    require_all_metric_comparisons_pass: bool,
    require_all_invalidation_outcomes_pass: bool,
    decision_validity_seconds: int,
    approved_at: datetime,
    recorded_at: datetime,
    active_from: datetime,
    active_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r1-forecast-promotion-policy.v1",
        "identity": [policy_id, policy_version, owner, capability, purpose],
        "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
        "status": status.value,
        "required_trial_state": required_trial_state.value,
        "gates": {
            "minimum_metric_coverage": _decimal_text(minimum_metric_coverage),
            "require_all_metric_comparisons_pass": require_all_metric_comparisons_pass,
            "require_all_invalidation_outcomes_pass": (require_all_invalidation_outcomes_pass),
        },
        "decision_validity_seconds": decision_validity_seconds,
        "window": [
            _utc_text(approved_at),
            _utc_text(recorded_at),
            _utc_text(active_from),
            _utc_text(active_until),
        ],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r1_forecast_promotion_policy_hash(policy: R1ForecastPromotionPolicy) -> str:
    """Recompute one exact Research R1 policy digest."""

    return _hash_payload(
        _promotion_policy_payload(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            owner=policy.owner,
            capability=policy.capability,
            purpose=policy.purpose,
            promotion_scope=policy.promotion_scope,
            status=policy.status,
            required_trial_state=policy.required_trial_state,
            minimum_metric_coverage=policy.minimum_metric_coverage,
            require_all_metric_comparisons_pass=policy.require_all_metric_comparisons_pass,
            require_all_invalidation_outcomes_pass=(policy.require_all_invalidation_outcomes_pass),
            decision_validity_seconds=policy.decision_validity_seconds,
            approved_at=policy.approved_at,
            recorded_at=policy.recorded_at,
            active_from=policy.active_from,
            active_until=policy.active_until,
        )
    )


@dataclass(frozen=True)
class R1PromotionPolicyIdentity:
    """Full stable identity of the Research policy used by a decision."""

    policy_id: str
    policy_version: str
    content_hash: str
    owner: str
    capability: str
    purpose: str

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "decision policy_id")
        _require_token(self.policy_version, "decision policy_version")
        _require_hash(self.content_hash, "decision policy content_hash")
        if self.owner != "research" or self.capability != "r1" or self.purpose != "valuation":
            raise ValueError("decision policy authority is invalid")


@dataclass(frozen=True)
class R1PromotionPolicyGateOutcome:
    """One deterministic policy gate result sealed into the decision."""

    gate_code: R1PromotionGateCode
    passes: bool
    reason_code: str
    observed_coverage: Decimal | None = None
    required_coverage: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.passes) is not bool:
            raise ValueError("promotion gate passes must be boolean")
        expected_reason = "" if self.passes else f"{self.gate_code.value}_not_met"
        if self.reason_code != expected_reason:
            raise ValueError("promotion gate reason does not match gate state")
        if self.gate_code is R1PromotionGateCode.MINIMUM_METRIC_COVERAGE:
            if self.observed_coverage is None or self.required_coverage is None:
                raise ValueError("coverage gate requires observed and required Decimal values")
            _require_unit_interval(self.observed_coverage, "observed promotion coverage")
            _require_unit_interval(self.required_coverage, "required promotion coverage")
            if self.passes != (self.observed_coverage >= self.required_coverage):
                raise ValueError("coverage gate state is inconsistent")
        elif self.observed_coverage is not None or self.required_coverage is not None:
            raise ValueError("non-coverage gate cannot carry Decimal coverage values")


@dataclass(frozen=True)
class R1PromotionForecastIdentity:
    """Exact persisted forecast identity sealed by the trial result."""

    forecast_id: str
    forecast_version: int
    content_hash: str
    subject_code: str
    industry_code: str
    candidate_scenario: str
    horizon_quarters: int
    metric_codes: tuple[str, ...]
    target_period_end: date
    as_of_time: datetime
    persisted_at: datetime

    def __post_init__(self) -> None:
        _require_token(self.forecast_id, "promotion forecast_id")
        _require_token(self.subject_code, "promotion forecast subject_code")
        _require_token(self.industry_code, "promotion forecast industry_code")
        _require_token(self.candidate_scenario, "promotion forecast candidate_scenario")
        if isinstance(self.forecast_version, bool) or self.forecast_version < 1:
            raise ValueError("promotion forecast_version must be positive")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters < 1:
            raise ValueError("promotion forecast horizon_quarters must be positive")
        if not self.metric_codes or self.metric_codes != tuple(sorted(set(self.metric_codes))):
            raise ValueError("promotion forecast metric_codes must be unique and ordered")
        for metric_code in self.metric_codes:
            _require_token(metric_code, "promotion forecast metric_code")
        _require_hash(self.content_hash, "promotion forecast content_hash")
        _require_aware(self.as_of_time, "promotion forecast as_of_time")
        _require_aware(self.persisted_at, "promotion forecast persisted_at")
        if self.persisted_at < self.as_of_time:
            raise ValueError("promotion forecast persistence predates its knowledge time")


@dataclass(frozen=True)
class R1PromotionMetricEvidence:
    """Canonical Decimal comparison evidence used by the promotion policy."""

    metric_code: str
    error_metric: str
    forecast_error: Decimal
    baseline_error: Decimal
    improvement: Decimal
    sample_count: int
    coverage: Decimal
    passes: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "promotion metric_code")
        _require_token(self.error_metric, "promotion error_metric")
        for field_name, value in (
            ("forecast_error", self.forecast_error),
            ("baseline_error", self.baseline_error),
            ("improvement", self.improvement),
        ):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"promotion {field_name} must be a finite Decimal")
        if isinstance(self.sample_count, bool) or self.sample_count < 0:
            raise ValueError("promotion metric sample_count must be non-negative")
        _require_unit_interval(self.coverage, "promotion metric coverage")
        if type(self.passes) is not bool:
            raise ValueError("promotion metric passes must be boolean")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("promotion metric reason_codes must be unique and ordered")


@dataclass(frozen=True)
class R1PromotionInvalidationEvidence:
    """Exact invalidation outcome sealed by the Equity result."""

    rule_code: str
    metric_code: str
    passes: bool
    triggered_at: date | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.rule_code, "promotion invalidation rule_code")
        _require_token(self.metric_code, "promotion invalidation metric_code")
        if type(self.passes) is not bool or self.passes != (self.triggered_at is None):
            raise ValueError("promotion invalidation state is inconsistent")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("promotion invalidation reason_codes must be unique and ordered")


@dataclass(frozen=True)
class R1ForecastTrialPromotionSeal:
    """Complete typed identity surface of one Equity forecast-baseline result."""

    result_id: str
    result_version: str
    result_content_hash: str
    spec_id: str
    spec_version: str
    spec_content_hash: str
    artifact_id: str
    artifact_version: str
    artifact_content_hash: str
    promotion_scope: R1PromotionScope
    forecasts: tuple[R1PromotionForecastIdentity, ...]
    research_trial_id: str
    research_trial_version: str
    research_trial_content_hash: str
    split_spec_hash: str
    parameter_hash: str
    calendar_schedule_hash: str
    evaluation_policy_id: str
    evaluation_policy_version: str
    evaluation_policy_content_hash: str
    actual_manifest_id: str
    actual_manifest_version: str
    actual_manifest_content_hash: str
    expected_period_ends: tuple[date, ...]
    metric_codes: tuple[str, ...]
    metric_evidence: tuple[R1PromotionMetricEvidence, ...]
    invalidation_evidence: tuple[R1PromotionInvalidationEvidence, ...]
    trial_state: R1PromotionTrialState
    evaluated_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def from_result(
        cls,
        result: ForecastBaselineTrialResult,
    ) -> R1ForecastTrialPromotionSeal:
        """Project the full promotion-relevant identity from an Equity result."""

        promotion_scope = R1PromotionScope.from_result(result)
        forecasts = tuple(
            R1PromotionForecastIdentity(
                forecast_id=item.forecast_id,
                forecast_version=item.forecast_version,
                content_hash=item.forecast_content_hash,
                subject_code=item.subject_code,
                industry_code=item.industry_code,
                candidate_scenario=item.candidate_scenario.value,
                horizon_quarters=item.horizon_quarters,
                metric_codes=tuple(sorted(code for code, _ in item.metric_values)),
                target_period_end=item.target_period_end,
                as_of_time=item.as_of_time,
                persisted_at=item.persisted_at,
            )
            for item in result.forecasts
        )
        metrics = tuple(
            R1PromotionMetricEvidence(
                metric_code=item.metric_code,
                error_metric=item.error_metric.value,
                forecast_error=item.forecast_error,
                baseline_error=item.baseline_error,
                improvement=item.improvement,
                sample_count=item.sample_count,
                coverage=item.coverage,
                passes=item.passes,
                reason_codes=tuple(sorted(item.reason_codes)),
            )
            for item in result.metric_comparisons
        )
        invalidations = tuple(
            R1PromotionInvalidationEvidence(
                rule_code=item.rule_code,
                metric_code=item.metric_code,
                passes=item.passes,
                triggered_at=item.triggered_at,
                reason_codes=tuple(sorted(item.reason_codes)),
            )
            for item in result.invalidation_outcomes
        )
        trial_state = (
            R1PromotionTrialState.ELIGIBLE_FOR_PROMOTION
            if result.eligible_for_promotion
            else R1PromotionTrialState.NOT_ELIGIBLE
        )
        digest = _hash_payload(
            _trial_seal_payload(
                result_id=result.result_id,
                result_version=result.result_version,
                result_content_hash=result.content_hash,
                spec_id=result.spec_id,
                spec_version=result.spec_version,
                spec_content_hash=result.spec_content_hash,
                artifact_id=result.baseline_artifact_id,
                artifact_version=result.baseline_artifact_version,
                artifact_content_hash=result.baseline_artifact_content_hash,
                promotion_scope=promotion_scope,
                forecasts=forecasts,
                research_trial_id=result.research_trial.trial_id,
                research_trial_version=result.research_trial.trial_version,
                research_trial_content_hash=result.research_trial.trial_content_hash,
                split_spec_hash=result.research_trial.split_spec_hash,
                parameter_hash=result.research_trial.parameter_hash,
                calendar_schedule_hash=result.research_trial.calendar_schedule_hash,
                evaluation_policy_id=result.research_trial.evaluation_policy.policy_id,
                evaluation_policy_version=(result.research_trial.evaluation_policy.policy_version),
                evaluation_policy_content_hash=(
                    result.research_trial.evaluation_policy.policy_content_hash
                ),
                actual_manifest_id=result.actual_manifest.manifest_id,
                actual_manifest_version=result.actual_manifest.manifest_version,
                actual_manifest_content_hash=result.actual_manifest.manifest_content_hash,
                expected_period_ends=result.expected_period_ends,
                metric_codes=result.metric_evaluation_order,
                metric_evidence=metrics,
                invalidation_evidence=invalidations,
                trial_state=trial_state,
                evaluated_at=result.evaluated_at,
                valid_until=result.valid_until,
            )
        )
        return cls(
            result_id=result.result_id,
            result_version=result.result_version,
            result_content_hash=result.content_hash,
            spec_id=result.spec_id,
            spec_version=result.spec_version,
            spec_content_hash=result.spec_content_hash,
            artifact_id=result.baseline_artifact_id,
            artifact_version=result.baseline_artifact_version,
            artifact_content_hash=result.baseline_artifact_content_hash,
            promotion_scope=promotion_scope,
            forecasts=forecasts,
            research_trial_id=result.research_trial.trial_id,
            research_trial_version=result.research_trial.trial_version,
            research_trial_content_hash=result.research_trial.trial_content_hash,
            split_spec_hash=result.research_trial.split_spec_hash,
            parameter_hash=result.research_trial.parameter_hash,
            calendar_schedule_hash=result.research_trial.calendar_schedule_hash,
            evaluation_policy_id=result.research_trial.evaluation_policy.policy_id,
            evaluation_policy_version=result.research_trial.evaluation_policy.policy_version,
            evaluation_policy_content_hash=(
                result.research_trial.evaluation_policy.policy_content_hash
            ),
            actual_manifest_id=result.actual_manifest.manifest_id,
            actual_manifest_version=result.actual_manifest.manifest_version,
            actual_manifest_content_hash=result.actual_manifest.manifest_content_hash,
            expected_period_ends=result.expected_period_ends,
            metric_codes=result.metric_evaluation_order,
            metric_evidence=metrics,
            invalidation_evidence=invalidations,
            trial_state=trial_state,
            evaluated_at=result.evaluated_at,
            valid_until=result.valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate full identity, completeness and canonical seal hash."""

        for field_name, value in (
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("spec_id", self.spec_id),
            ("spec_version", self.spec_version),
            ("artifact_id", self.artifact_id),
            ("artifact_version", self.artifact_version),
            ("research_trial_id", self.research_trial_id),
            ("research_trial_version", self.research_trial_version),
            ("evaluation_policy_id", self.evaluation_policy_id),
            ("evaluation_policy_version", self.evaluation_policy_version),
            ("actual_manifest_id", self.actual_manifest_id),
            ("actual_manifest_version", self.actual_manifest_version),
        ):
            _require_token(value, f"trial seal {field_name}")
        for field_name, value in (
            ("result_content_hash", self.result_content_hash),
            ("spec_content_hash", self.spec_content_hash),
            ("artifact_content_hash", self.artifact_content_hash),
            ("research_trial_content_hash", self.research_trial_content_hash),
            ("split_spec_hash", self.split_spec_hash),
            ("parameter_hash", self.parameter_hash),
            ("calendar_schedule_hash", self.calendar_schedule_hash),
            ("evaluation_policy_content_hash", self.evaluation_policy_content_hash),
            ("actual_manifest_content_hash", self.actual_manifest_content_hash),
        ):
            _require_hash(value, f"trial seal {field_name}")
        _require_aware(self.evaluated_at, "trial seal evaluated_at")
        _require_aware(self.valid_until, "trial seal valid_until")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("trial seal validity must follow evaluation")
        forecast_periods = tuple(item.target_period_end for item in self.forecasts)
        metric_codes = tuple(item.metric_code for item in self.metric_evidence)
        if (
            self.promotion_scope.calendar_schedule_hash != self.calendar_schedule_hash
            or self.promotion_scope.metric_codes != tuple(sorted(self.metric_codes))
            or any(
                item.subject_code != self.promotion_scope.subject_code
                or item.industry_code != self.promotion_scope.industry_code
                or item.candidate_scenario != self.promotion_scope.candidate_scenario
                or item.metric_codes != self.promotion_scope.metric_codes
                for item in self.forecasts
            )
            or max(item.horizon_quarters for item in self.forecasts)
            != self.promotion_scope.horizon_quarters
        ):
            raise ValueError("trial seal promotion scope does not match forecast evidence")
        if (
            not self.forecasts
            or forecast_periods != self.expected_period_ends
            or len(forecast_periods) != len(set(forecast_periods))
        ):
            raise ValueError("trial seal forecasts must cover exact expected periods")
        if (
            not self.metric_evidence
            or metric_codes != self.metric_codes
            or len(metric_codes) != len(set(metric_codes))
        ):
            raise ValueError("trial seal metrics must cover exact evaluation order")
        expected_state = (
            R1PromotionTrialState.ELIGIBLE_FOR_PROMOTION
            if all(item.passes for item in self.metric_evidence)
            and all(item.passes for item in self.invalidation_evidence)
            else R1PromotionTrialState.NOT_ELIGIBLE
        )
        if self.trial_state is not expected_state:
            raise ValueError("trial seal state does not match metric/invalidation evidence")
        _require_hash(self.content_hash, "trial seal content_hash")
        if self.content_hash != r1_forecast_trial_promotion_seal_hash(self):
            raise ValueError("trial promotion seal content hash mismatch")


def _trial_seal_payload(
    *,
    result_id: str,
    result_version: str,
    result_content_hash: str,
    spec_id: str,
    spec_version: str,
    spec_content_hash: str,
    artifact_id: str,
    artifact_version: str,
    artifact_content_hash: str,
    promotion_scope: R1PromotionScope,
    forecasts: tuple[R1PromotionForecastIdentity, ...],
    research_trial_id: str,
    research_trial_version: str,
    research_trial_content_hash: str,
    split_spec_hash: str,
    parameter_hash: str,
    calendar_schedule_hash: str,
    evaluation_policy_id: str,
    evaluation_policy_version: str,
    evaluation_policy_content_hash: str,
    actual_manifest_id: str,
    actual_manifest_version: str,
    actual_manifest_content_hash: str,
    expected_period_ends: tuple[date, ...],
    metric_codes: tuple[str, ...],
    metric_evidence: tuple[R1PromotionMetricEvidence, ...],
    invalidation_evidence: tuple[R1PromotionInvalidationEvidence, ...],
    trial_state: R1PromotionTrialState,
    evaluated_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r1-forecast-trial-promotion-seal.v1",
        "result": [
            result_id,
            result_version,
            result_content_hash,
        ],
        "spec": [spec_id, spec_version, spec_content_hash],
        "artifact": [
            artifact_id,
            artifact_version,
            artifact_content_hash,
        ],
        "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
        "forecasts": [
            [
                item.forecast_id,
                item.forecast_version,
                item.content_hash,
                item.subject_code,
                item.industry_code,
                item.candidate_scenario,
                item.horizon_quarters,
                list(item.metric_codes),
                item.target_period_end.isoformat(),
                _utc_text(item.as_of_time),
                _utc_text(item.persisted_at),
            ]
            for item in forecasts
            if isinstance(item, R1PromotionForecastIdentity)
        ],
        "research_authorization": [
            research_trial_id,
            research_trial_version,
            research_trial_content_hash,
            split_spec_hash,
            parameter_hash,
            calendar_schedule_hash,
            evaluation_policy_id,
            evaluation_policy_version,
            evaluation_policy_content_hash,
        ],
        "actual_manifest": [
            actual_manifest_id,
            actual_manifest_version,
            actual_manifest_content_hash,
        ],
        "expected_period_ends": [item.isoformat() for item in expected_period_ends],
        "metric_codes": list(metric_codes),
        "metric_evidence": [
            [
                item.metric_code,
                item.error_metric,
                _decimal_text(item.forecast_error),
                _decimal_text(item.baseline_error),
                _decimal_text(item.improvement),
                item.sample_count,
                _decimal_text(item.coverage),
                item.passes,
                list(item.reason_codes),
            ]
            for item in metric_evidence
        ],
        "invalidation_evidence": [
            [
                item.rule_code,
                item.metric_code,
                item.passes,
                item.triggered_at.isoformat() if item.triggered_at is not None else None,
                list(item.reason_codes),
            ]
            for item in invalidation_evidence
        ],
        "trial_state": trial_state.value,
        "window": [_utc_text(evaluated_at), _utc_text(valid_until)],
    }


def r1_forecast_trial_promotion_seal_hash(seal: R1ForecastTrialPromotionSeal) -> str:
    """Recompute the complete typed Equity result identity seal."""

    return _hash_payload(
        _trial_seal_payload(
            result_id=seal.result_id,
            result_version=seal.result_version,
            result_content_hash=seal.result_content_hash,
            spec_id=seal.spec_id,
            spec_version=seal.spec_version,
            spec_content_hash=seal.spec_content_hash,
            artifact_id=seal.artifact_id,
            artifact_version=seal.artifact_version,
            artifact_content_hash=seal.artifact_content_hash,
            promotion_scope=seal.promotion_scope,
            forecasts=seal.forecasts,
            research_trial_id=seal.research_trial_id,
            research_trial_version=seal.research_trial_version,
            research_trial_content_hash=seal.research_trial_content_hash,
            split_spec_hash=seal.split_spec_hash,
            parameter_hash=seal.parameter_hash,
            calendar_schedule_hash=seal.calendar_schedule_hash,
            evaluation_policy_id=seal.evaluation_policy_id,
            evaluation_policy_version=seal.evaluation_policy_version,
            evaluation_policy_content_hash=seal.evaluation_policy_content_hash,
            actual_manifest_id=seal.actual_manifest_id,
            actual_manifest_version=seal.actual_manifest_version,
            actual_manifest_content_hash=seal.actual_manifest_content_hash,
            expected_period_ends=seal.expected_period_ends,
            metric_codes=seal.metric_codes,
            metric_evidence=seal.metric_evidence,
            invalidation_evidence=seal.invalidation_evidence,
            trial_state=seal.trial_state,
            evaluated_at=seal.evaluated_at,
            valid_until=seal.valid_until,
        )
    )


@dataclass(frozen=True)
class R1ForecastPromotionDecision:
    """Research-owned automatic decision over one exact Equity R1 result."""

    decision_id: str
    decision_version: str
    owner: str
    capability: str
    purpose: str
    promotion_scope: R1PromotionScope
    outcome: R1PromotionDecisionOutcome
    policy: R1ForecastPromotionPolicy
    trial: R1ForecastTrialPromotionSeal
    policy_gate_outcomes: tuple[R1PromotionPolicyGateOutcome, ...]
    reason_codes: tuple[str, ...]
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        """Validate derived outcome, exact references and canonical decision hash."""

        _require_token(self.decision_id, "R1 promotion decision_id")
        _require_token(self.decision_version, "R1 promotion decision_version")
        if self.owner != "research" or self.capability != "r1" or self.purpose != "valuation":
            raise ValueError("R1 promotion decision authority is invalid")
        if (
            self.policy.owner != self.owner
            or self.policy.capability != self.capability
            or self.promotion_scope != self.policy.promotion_scope
            or self.promotion_scope != self.trial.promotion_scope
        ):
            raise ValueError("R1 promotion decision policy authority was substituted")
        if not self.reason_codes or self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("R1 promotion decision reason_codes must be unique and ordered")
        _require_aware(self.decided_at, "R1 promotion decided_at")
        _require_aware(self.recorded_at, "R1 promotion recorded_at")
        _require_aware(self.valid_until, "R1 promotion valid_until")
        if not (
            self.trial.evaluated_at
            <= self.decided_at
            <= self.recorded_at
            < self.valid_until
            <= self.trial.valid_until
        ):
            raise ValueError("R1 promotion decision window is outside the trial window")
        expected_gate_outcomes = _evaluate_policy_gates(self.policy, self.trial)
        if self.policy_gate_outcomes != expected_gate_outcomes:
            raise ValueError("R1 promotion policy gate outcomes were substituted")
        rejection_reasons = tuple(
            sorted(item.reason_code for item in self.policy_gate_outcomes if not item.passes)
        )
        if self.outcome is R1PromotionDecisionOutcome.APPROVED:
            if (
                self.trial.trial_state is not R1PromotionTrialState.ELIGIBLE_FOR_PROMOTION
                or rejection_reasons
                or self.reason_codes != ("promotion_policy_satisfied",)
            ):
                raise ValueError("approved R1 promotion requires the canonical success reason")
        elif not rejection_reasons or self.reason_codes != rejection_reasons:
            raise ValueError("rejected R1 promotion reasons do not match the trial evidence")
        if not (
            self.policy.recorded_at <= self.decided_at < self.policy.active_until
            and self.policy.active_from <= self.decided_at
            and self.valid_until <= self.policy.active_until
        ):
            raise ValueError("R1 promotion decision is outside the sealed policy window")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R1 promotion decision must remain research-only")
        _require_hash(self.content_hash, "R1 promotion decision content_hash")
        if self.content_hash != r1_forecast_promotion_decision_hash(self):
            raise ValueError("R1 promotion decision content hash mismatch")


def create_r1_forecast_promotion_decision(
    *,
    decision_id: str,
    decision_version: str,
    policy: R1ForecastPromotionPolicy,
    result: ForecastBaselineTrialResult,
    as_of: datetime,
    recorded_at: datetime,
) -> R1ForecastPromotionDecision:
    """Derive approved/rejected without caller-provided outcome or attestation."""

    _require_aware(as_of, "R1 promotion as_of")
    _require_aware(recorded_at, "R1 promotion recorded_at")
    if not policy.recorded_at <= as_of or not policy.active_from <= as_of < policy.active_until:
        raise ValueError("R1 promotion policy is unavailable or inactive at as_of")
    if not result.evaluated_at <= as_of < result.valid_until:
        raise ValueError("Equity forecast trial result is inactive at as_of")
    if not (result.research_only and result.must_not_use_for_decision and result.must_not_execute):
        raise ValueError("Equity forecast trial result must remain research-only")
    trial = R1ForecastTrialPromotionSeal.from_result(result)
    if policy.promotion_scope != trial.promotion_scope:
        raise ValueError("R1 promotion policy does not govern the trial scope")
    gate_outcomes = _evaluate_policy_gates(policy, trial)
    blockers = [item.reason_code for item in gate_outcomes if not item.passes]
    outcome = (
        R1PromotionDecisionOutcome.APPROVED if not blockers else R1PromotionDecisionOutcome.REJECTED
    )
    reasons = ("promotion_policy_satisfied",) if not blockers else tuple(sorted(set(blockers)))
    valid_until = r1_forecast_promotion_decision_valid_until(
        policy=policy,
        result=result,
        as_of=as_of,
    )
    digest = _hash_payload(
        _promotion_decision_payload(
            decision_id=decision_id,
            decision_version=decision_version,
            owner="research",
            capability="r1",
            purpose="valuation",
            promotion_scope=trial.promotion_scope,
            outcome=outcome,
            policy=policy,
            trial=trial,
            policy_gate_outcomes=gate_outcomes,
            reason_codes=reasons,
            decided_at=as_of,
            recorded_at=recorded_at,
            valid_until=valid_until,
        )
    )
    return R1ForecastPromotionDecision(
        decision_id=decision_id,
        decision_version=decision_version,
        owner="research",
        capability="r1",
        purpose="valuation",
        promotion_scope=trial.promotion_scope,
        outcome=outcome,
        policy=policy,
        trial=trial,
        policy_gate_outcomes=gate_outcomes,
        reason_codes=reasons,
        decided_at=as_of,
        recorded_at=recorded_at,
        valid_until=valid_until,
        content_hash=digest,
    )


def r1_forecast_promotion_decision_valid_until(
    *,
    policy: R1ForecastPromotionPolicy,
    result: ForecastBaselineTrialResult,
    as_of: datetime,
) -> datetime:
    """Return the sole canonical upper bound for one decision receipt."""

    _require_aware(as_of, "R1 promotion validity as_of")
    return min(
        result.valid_until,
        policy.active_until,
        as_of + timedelta(seconds=policy.decision_validity_seconds),
    )


def _promotion_decision_payload(
    *,
    decision_id: str,
    decision_version: str,
    owner: str,
    capability: str,
    purpose: str,
    promotion_scope: R1PromotionScope,
    outcome: R1PromotionDecisionOutcome,
    policy: R1ForecastPromotionPolicy,
    trial: R1ForecastTrialPromotionSeal,
    policy_gate_outcomes: tuple[R1PromotionPolicyGateOutcome, ...],
    reason_codes: tuple[str, ...],
    decided_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r1-forecast-promotion-decision.v1",
        "identity": [decision_id, decision_version, owner, capability, purpose],
        "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
        "outcome": outcome.value,
        "policy": [
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
            policy.owner,
            policy.capability,
            policy.purpose,
        ],
        "policy_gate_outcomes": [
            [
                item.gate_code.value,
                item.passes,
                item.reason_code,
                (
                    _decimal_text(item.observed_coverage)
                    if item.observed_coverage is not None
                    else None
                ),
                (
                    _decimal_text(item.required_coverage)
                    if item.required_coverage is not None
                    else None
                ),
            ]
            for item in policy_gate_outcomes
        ],
        "trial": {
            "result": [trial.result_id, trial.result_version, trial.result_content_hash],
            "spec": [trial.spec_id, trial.spec_version, trial.spec_content_hash],
            "artifact": [
                trial.artifact_id,
                trial.artifact_version,
                trial.artifact_content_hash,
            ],
            "forecast_identities": [
                [item.forecast_id, item.forecast_version, item.content_hash]
                for item in trial.forecasts
            ],
            "research_authorization": [
                trial.research_trial_id,
                trial.research_trial_version,
                trial.research_trial_content_hash,
                trial.split_spec_hash,
                trial.parameter_hash,
                trial.calendar_schedule_hash,
                trial.evaluation_policy_id,
                trial.evaluation_policy_version,
                trial.evaluation_policy_content_hash,
            ],
            "actual_manifest": [
                trial.actual_manifest_id,
                trial.actual_manifest_version,
                trial.actual_manifest_content_hash,
            ],
            "promotion_seal_hash": trial.content_hash,
        },
        "reason_codes": list(reason_codes),
        "window": [_utc_text(decided_at), _utc_text(recorded_at), _utc_text(valid_until)],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r1_forecast_promotion_decision_hash(decision: R1ForecastPromotionDecision) -> str:
    """Recompute one exact Research promotion decision digest."""

    return _hash_payload(
        _promotion_decision_payload(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            owner=decision.owner,
            capability=decision.capability,
            purpose=decision.purpose,
            promotion_scope=decision.promotion_scope,
            outcome=decision.outcome,
            policy=decision.policy,
            trial=decision.trial,
            policy_gate_outcomes=decision.policy_gate_outcomes,
            reason_codes=decision.reason_codes,
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            valid_until=decision.valid_until,
        )
    )


def _evaluate_policy_gates(
    policy: R1ForecastPromotionPolicy,
    trial: R1ForecastTrialPromotionSeal,
) -> tuple[R1PromotionPolicyGateOutcome, ...]:
    minimum_coverage = min(item.coverage for item in trial.metric_evidence)
    values = (
        (
            R1PromotionGateCode.REQUIRED_TRIAL_STATE,
            trial.trial_state is policy.required_trial_state,
            None,
            None,
        ),
        (
            R1PromotionGateCode.MINIMUM_METRIC_COVERAGE,
            minimum_coverage >= policy.minimum_metric_coverage,
            minimum_coverage,
            policy.minimum_metric_coverage,
        ),
        (
            R1PromotionGateCode.ALL_METRIC_COMPARISONS_PASS,
            all(item.passes for item in trial.metric_evidence),
            None,
            None,
        ),
        (
            R1PromotionGateCode.ALL_INVALIDATION_OUTCOMES_PASS,
            all(item.passes for item in trial.invalidation_evidence),
            None,
            None,
        ),
    )
    return tuple(
        R1PromotionPolicyGateOutcome(
            gate_code=gate_code,
            passes=passes,
            reason_code="" if passes else f"{gate_code.value}_not_met",
            observed_coverage=observed,
            required_coverage=required,
        )
        for gate_code, passes, observed, required in values
    )


__all__ = [
    "R1ForecastPromotionDecision",
    "R1ForecastPromotionPolicy",
    "R1ForecastTrialPromotionSeal",
    "R1PromotionDecisionOutcome",
    "R1PromotionForecastIdentity",
    "R1PromotionGateCode",
    "R1PromotionInvalidationEvidence",
    "R1PromotionMetricEvidence",
    "R1PromotionPolicyIdentity",
    "R1PromotionPolicyGateOutcome",
    "R1PromotionPolicyStatus",
    "R1PromotionScope",
    "R1PromotionTrialState",
    "create_r1_forecast_promotion_decision",
    "r1_forecast_promotion_decision_hash",
    "r1_forecast_promotion_decision_valid_until",
    "r1_forecast_promotion_policy_hash",
    "r1_forecast_trial_promotion_seal_hash",
    "r1_promotion_scope_hash",
]
