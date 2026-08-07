"""Fail-closed execution of the R6 state-model qualification gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from apps.research.domain.advanced_state_model import (
    AdvancedStateModelAssessment,
    AdvancedStateModelAssessmentStatus,
    AdvancedStateModelCandidateEvidence,
    StateModelLifecycleStatus,
)
from apps.research.domain.state_model_baseline import (
    BaselineEvidenceState,
    BaselineShortfallDecision,
    BaselineShortfallReport,
)
from apps.research.domain.state_model_qualification_contracts import (
    REQUIRED_QUALIFICATION_METRIC_KEYS,
    AdvancedStateModelAssessmentAttestation,
    ComparativeMetricResult,
    PolicyCoefficientSign,
    StateModelComparativeStudyEvidence,
    StateModelDerivedMetricBundle,
    StateModelQualificationBlockerCode,
    StateModelQualificationPolicy,
    StateModelQualificationStatus,
    StateModelStudyPreregistration,
    _canonical_hash,
    _require_aware,
    _require_sha256,
    _require_token,
)


@dataclass(frozen=True, init=False)
class StateModelQualificationAssessment:
    """Canonical research-only evidence for a later human promotion review."""

    status: StateModelQualificationStatus
    study_id: str
    candidate_id: str | None
    candidate_version: str | None
    study_hash: str | None
    preregistration_hash: str | None
    baseline_shortfall_report_hash: str | None
    candidate_evidence_hash: str | None
    advanced_assessment_hash: str | None
    pit_manifest_canonical_hash: str | None
    artifact_attestation_hash: str | None
    advanced_threshold_hash: str | None
    derived_metric_bundle_hash: str | None
    policy_hash: str | None
    assessed_at: datetime
    metric_results: tuple[ComparativeMetricResult, ...]
    blockers: tuple[StateModelQualificationBlockerCode, ...]
    may_request_promotion_review: bool
    promotion_decision_present: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    content_hash: str = field(init=False)

    def __new__(cls) -> StateModelQualificationAssessment:
        """Reject direct construction outside the module-private qualification gate."""

        raise TypeError("qualification assessments must be minted by the qualification gate")

    def __post_init__(self) -> None:
        if not isinstance(self.status, StateModelQualificationStatus):
            raise ValueError("state-model qualification status is invalid")
        _require_token(self.study_id, "StateModelQualificationAssessment.study_id")
        if self.candidate_id is not None:
            _require_token(
                self.candidate_id,
                "StateModelQualificationAssessment.candidate_id",
            )
        if self.candidate_version is not None:
            _require_token(
                self.candidate_version,
                "StateModelQualificationAssessment.candidate_version",
            )
        _require_aware(self.assessed_at, "StateModelQualificationAssessment.assessed_at")
        for field_name in (
            "study_hash",
            "preregistration_hash",
            "baseline_shortfall_report_hash",
            "candidate_evidence_hash",
            "advanced_assessment_hash",
            "pit_manifest_canonical_hash",
            "artifact_attestation_hash",
            "advanced_threshold_hash",
            "derived_metric_bundle_hash",
            "policy_hash",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_sha256(value, f"StateModelQualificationAssessment.{field_name}")
        _require_sha256(self.content_hash, "StateModelQualificationAssessment.content_hash")
        if len(self.blockers) != len(set(self.blockers)) or any(
            not isinstance(blocker, StateModelQualificationBlockerCode) for blocker in self.blockers
        ):
            raise ValueError("qualification assessment blockers must be unique stable codes")
        metric_keys = tuple(result.metric_key for result in self.metric_results)
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("qualification assessment metric results must be uniquely keyed")
        if self.status is StateModelQualificationStatus.EVIDENCE_COMPLETE:
            if self.blockers or not self.may_request_promotion_review:
                raise ValueError("complete qualification evidence cannot contain blockers")
            if (
                frozenset(metric_keys) != REQUIRED_QUALIFICATION_METRIC_KEYS
                or len(metric_keys) != len(REQUIRED_QUALIFICATION_METRIC_KEYS)
                or any(not result.passed for result in self.metric_results)
            ):
                raise ValueError("complete qualification evidence requires seven passed metrics")
            required = (
                self.candidate_id,
                self.candidate_version,
                self.study_hash,
                self.preregistration_hash,
                self.baseline_shortfall_report_hash,
                self.candidate_evidence_hash,
                self.advanced_assessment_hash,
                self.pit_manifest_canonical_hash,
                self.artifact_attestation_hash,
                self.advanced_threshold_hash,
                self.derived_metric_bundle_hash,
                self.policy_hash,
            )
            if any(value is None for value in required):
                raise ValueError("complete qualification evidence requires exact references")
        elif not self.blockers or self.may_request_promotion_review:
            raise ValueError("blocked qualification evidence requires blockers")
        if (
            self.promotion_decision_present is not False
            or self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_replace_regime is not True
        ):
            raise ValueError(
                "qualification evidence cannot authorize a decision or Regime replacement"
            )
        if self.content_hash.lower() != self.calculated_content_hash:
            raise ValueError("state-model qualification assessment content_hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return a digest sealing the complete qualification outcome."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


def _mint_state_model_qualification_assessment(
    *,
    status: StateModelQualificationStatus,
    study_id: str,
    candidate_id: str | None,
    candidate_version: str | None,
    study_hash: str | None,
    preregistration_hash: str | None,
    baseline_shortfall_report_hash: str | None,
    candidate_evidence_hash: str | None,
    advanced_assessment_hash: str | None,
    pit_manifest_canonical_hash: str | None,
    artifact_attestation_hash: str | None,
    advanced_threshold_hash: str | None,
    derived_metric_bundle_hash: str | None,
    policy_hash: str | None,
    assessed_at: datetime,
    metric_results: tuple[ComparativeMetricResult, ...],
    blockers: tuple[StateModelQualificationBlockerCode, ...],
    may_request_promotion_review: bool,
) -> StateModelQualificationAssessment:
    """Mint one immutable outcome at the module-private qualification boundary."""

    instance = object.__new__(StateModelQualificationAssessment)
    values: tuple[tuple[str, object], ...] = (
        ("status", status),
        ("study_id", study_id),
        ("candidate_id", candidate_id),
        ("candidate_version", candidate_version),
        ("study_hash", study_hash),
        ("preregistration_hash", preregistration_hash),
        ("baseline_shortfall_report_hash", baseline_shortfall_report_hash),
        ("candidate_evidence_hash", candidate_evidence_hash),
        ("advanced_assessment_hash", advanced_assessment_hash),
        ("pit_manifest_canonical_hash", pit_manifest_canonical_hash),
        ("artifact_attestation_hash", artifact_attestation_hash),
        ("advanced_threshold_hash", advanced_threshold_hash),
        ("derived_metric_bundle_hash", derived_metric_bundle_hash),
        ("policy_hash", policy_hash),
        ("assessed_at", assessed_at),
        ("metric_results", metric_results),
        ("blockers", blockers),
        ("may_request_promotion_review", may_request_promotion_review),
        ("promotion_decision_present", False),
        ("research_only", True),
        ("must_not_use_for_decision", True),
        ("must_not_replace_regime", True),
    )
    for name, value in values:
        object.__setattr__(instance, name, value)
    object.__setattr__(instance, "content_hash", instance.calculated_content_hash)
    instance.__post_init__()
    return instance


def restore_state_model_qualification_assessment(
    *,
    status: StateModelQualificationStatus,
    study_id: str,
    candidate_id: str | None,
    candidate_version: str | None,
    study_hash: str | None,
    preregistration_hash: str | None,
    baseline_shortfall_report_hash: str | None,
    candidate_evidence_hash: str | None,
    advanced_assessment_hash: str | None,
    pit_manifest_canonical_hash: str | None,
    artifact_attestation_hash: str | None,
    advanced_threshold_hash: str | None,
    derived_metric_bundle_hash: str | None,
    policy_hash: str | None,
    assessed_at: datetime,
    metric_results: tuple[ComparativeMetricResult, ...],
    blockers: tuple[StateModelQualificationBlockerCode, ...],
    may_request_promotion_review: bool,
    promotion_decision_present: bool,
    research_only: bool,
    must_not_use_for_decision: bool,
    must_not_replace_regime: bool,
    content_hash: str,
) -> StateModelQualificationAssessment:
    """Restore one persisted assessment after its canonical payload is decoded.

    The normal public constructor intentionally cannot mint assessments.  Persistence
    needs a narrow, domain-owned restore boundary so it can replay the exact sealed
    value and run the same invariant checks before exposing it to Application code.
    """

    instance = object.__new__(StateModelQualificationAssessment)
    values: tuple[tuple[str, object], ...] = (
        ("status", status),
        ("study_id", study_id),
        ("candidate_id", candidate_id),
        ("candidate_version", candidate_version),
        ("study_hash", study_hash),
        ("preregistration_hash", preregistration_hash),
        ("baseline_shortfall_report_hash", baseline_shortfall_report_hash),
        ("candidate_evidence_hash", candidate_evidence_hash),
        ("advanced_assessment_hash", advanced_assessment_hash),
        ("pit_manifest_canonical_hash", pit_manifest_canonical_hash),
        ("artifact_attestation_hash", artifact_attestation_hash),
        ("advanced_threshold_hash", advanced_threshold_hash),
        ("derived_metric_bundle_hash", derived_metric_bundle_hash),
        ("policy_hash", policy_hash),
        ("assessed_at", assessed_at),
        ("metric_results", metric_results),
        ("blockers", blockers),
        ("may_request_promotion_review", may_request_promotion_review),
        ("promotion_decision_present", promotion_decision_present),
        ("research_only", research_only),
        ("must_not_use_for_decision", must_not_use_for_decision),
        ("must_not_replace_regime", must_not_replace_regime),
        ("content_hash", content_hash),
    )
    for name, value in values:
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _candidate_metric_values(
    candidate: AdvancedStateModelCandidateEvidence,
) -> dict[str, Decimal]:
    metrics = candidate.oos_metrics
    return {
        "transition_accuracy": metrics.transition_accuracy,
        "log_loss": metrics.log_loss,
        "calibration_error": metrics.calibration_error,
        "duration_mae_periods": metrics.duration_mae_periods,
    }


def _build_assessment(
    *,
    study_id: str,
    assessed_at: datetime,
    study: StateModelComparativeStudyEvidence | None,
    preregistration: StateModelStudyPreregistration | None,
    baseline_shortfall: BaselineShortfallReport | None,
    candidate: AdvancedStateModelCandidateEvidence | None,
    advanced_assessment: AdvancedStateModelAssessmentAttestation | None,
    derived_metric_bundle: StateModelDerivedMetricBundle | None,
    policy: StateModelQualificationPolicy | None,
    metric_results: tuple[ComparativeMetricResult, ...],
    blockers: list[StateModelQualificationBlockerCode],
) -> StateModelQualificationAssessment:
    unique_blockers = tuple(dict.fromkeys(blockers))
    status = (
        StateModelQualificationStatus.BLOCKED
        if unique_blockers
        else StateModelQualificationStatus.EVIDENCE_COMPLETE
    )
    return _mint_state_model_qualification_assessment(
        status=status,
        study_id=study_id,
        candidate_id=(
            study.candidate_id
            if study is not None
            else (candidate.candidate_id if candidate is not None else None)
        ),
        candidate_version=(
            study.candidate_version
            if study is not None
            else (candidate.candidate_version if candidate is not None else None)
        ),
        study_hash=(study.content_hash if study is not None else None),
        preregistration_hash=(
            preregistration.content_hash if preregistration is not None else None
        ),
        baseline_shortfall_report_hash=(
            baseline_shortfall.content_hash if baseline_shortfall is not None else None
        ),
        candidate_evidence_hash=(candidate.evidence_hash if candidate is not None else None),
        advanced_assessment_hash=(
            advanced_assessment.content_hash if advanced_assessment is not None else None
        ),
        pit_manifest_canonical_hash=(
            advanced_assessment.pit_manifest_canonical_hash
            if advanced_assessment is not None
            else None
        ),
        artifact_attestation_hash=(
            advanced_assessment.artifact_attestation_hash
            if advanced_assessment is not None
            else None
        ),
        advanced_threshold_hash=(
            advanced_assessment.threshold_hash if advanced_assessment is not None else None
        ),
        derived_metric_bundle_hash=(
            derived_metric_bundle.content_hash if derived_metric_bundle is not None else None
        ),
        policy_hash=(policy.content_hash if policy is not None else None),
        assessed_at=assessed_at,
        metric_results=metric_results,
        blockers=unique_blockers,
        may_request_promotion_review=not unique_blockers,
    )


def missing_state_model_qualification_assessment(
    *,
    study_id: str,
    assessed_at: datetime,
    blocker: StateModelQualificationBlockerCode,
) -> StateModelQualificationAssessment:
    """Build a sealed fail-closed result when ID-only collection cannot begin."""

    _require_token(study_id, "study_id")
    _require_aware(assessed_at, "assessed_at")
    return _build_assessment(
        study_id=study_id,
        assessed_at=assessed_at,
        study=None,
        preregistration=None,
        baseline_shortfall=None,
        candidate=None,
        advanced_assessment=None,
        derived_metric_bundle=None,
        policy=None,
        metric_results=(),
        blockers=[blocker],
    )


def evaluate_state_model_qualification(
    *,
    candidate: AdvancedStateModelCandidateEvidence | None,
    advanced_assessment: (
        AdvancedStateModelAssessmentAttestation | AdvancedStateModelAssessment | None
    ),
    derived_metric_bundle: StateModelDerivedMetricBundle | None,
    baseline_shortfall: BaselineShortfallReport | None,
    preregistration: StateModelStudyPreregistration | None,
    study: StateModelComparativeStudyEvidence,
    policy: StateModelQualificationPolicy | None,
    assessed_at: datetime,
) -> StateModelQualificationAssessment:
    """Recompute all exact bindings and permit only manual promotion review."""

    _require_aware(assessed_at, "assessed_at")
    blockers: list[StateModelQualificationBlockerCode] = []
    if (
        study.content_hash.lower() != study.calculated_content_hash
        or study.study_id != study.calculated_study_id
    ):
        blockers.append(StateModelQualificationBlockerCode.STUDY_HASH_MISMATCH)
    if study.evaluated_at > assessed_at:
        blockers.append(StateModelQualificationBlockerCode.STUDY_FROM_FUTURE)
    if study.valid_until <= assessed_at:
        blockers.append(StateModelQualificationBlockerCode.STUDY_STALE)

    if preregistration is None:
        blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_MISSING)
    else:
        if preregistration.content_hash.lower() != preregistration.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_HASH_MISMATCH)
        preregistration_binding = (
            preregistration.registration_id,
            preregistration.content_hash.lower(),
            preregistration.trial_family_id,
            preregistration.trial_family_hash.lower(),
            preregistration.split_policy_version,
            preregistration.embargo_periods,
            preregistration.candidate_id,
            preregistration.candidate_version,
            preregistration.baseline_shortfall_report_hash.lower(),
            preregistration.qualification_policy_version,
            preregistration.qualification_policy_hash.lower(),
            preregistration.oos_window_start,
            preregistration.oos_window_end,
        )
        study_binding = (
            study.preregistration_id,
            study.preregistration_hash.lower(),
            study.trial_family_id,
            study.trial_family_hash.lower(),
            study.split_policy_version,
            study.embargo_periods,
            study.candidate_id,
            study.candidate_version,
            study.baseline_shortfall_report_hash.lower(),
            study.qualification_policy_version,
            study.qualification_policy_hash.lower(),
            study.oos_window_start,
            study.oos_window_end,
        )
        if preregistration_binding != study_binding:
            blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH)

    if candidate is None:
        blockers.append(StateModelQualificationBlockerCode.CANDIDATE_MISSING)
    else:
        if candidate.evidence_hash.lower() != candidate.calculated_evidence_hash:
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_HASH_MISMATCH)
        if candidate.valid_until <= assessed_at:
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_EVIDENCE_STALE)
        if candidate.lifecycle_status is StateModelLifecycleStatus.RETIRED:
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_RETIRED)
        if (
            study.candidate_id != candidate.candidate_id
            or study.candidate_version != candidate.candidate_version
            or study.candidate_evidence_hash.lower() != candidate.evidence_hash.lower()
            or study.artifact_hash.lower() != candidate.artifact.artifact_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_BINDING_MISMATCH)
        if (
            study.pit_manifest_id != candidate.pit_manifest_id
            or study.pit_manifest_hash.lower() != candidate.pit_manifest_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.PIT_BINDING_MISMATCH)
        label = candidate.label_protocol
        if (
            study.label_protocol_version != label.protocol_version
            or study.label_stability_evidence_hash.lower() != label.stability_evidence_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.LABEL_BINDING_MISMATCH)
        if not label.is_stable or label.drift_detected:
            blockers.append(StateModelQualificationBlockerCode.LABEL_PROTOCOL_UNSTABLE)
        policy_reaction = candidate.policy_reaction
        if (
            policy_reaction is None
            or study.policy_reaction_specification_version != policy_reaction.specification_version
            or study.policy_reaction_evidence_hash.lower() != policy_reaction.evidence_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.POLICY_REACTION_BINDING_MISMATCH)
        if preregistration is not None and preregistration.methodology is not candidate.methodology:
            blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH)
        candidate_times = (
            candidate.artifact.produced_at,
            candidate.label_protocol.verified_at,
            candidate.state_distribution.observed_at,
            candidate.transition_matrix.observed_at,
            candidate.oos_metrics.evaluated_at,
            candidate.baseline_comparison.compared_at,
        )
        if any(value > study.evaluated_at for value in candidate_times):
            blockers.append(StateModelQualificationBlockerCode.EVIDENCE_TIMELINE_INVALID)

    if advanced_assessment is None:
        blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_MISSING)
    elif not isinstance(advanced_assessment, AdvancedStateModelAssessmentAttestation):
        blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
    else:
        if advanced_assessment.content_hash.lower() != advanced_assessment.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_HASH_MISMATCH)
        if (
            study.advanced_assessment_id != advanced_assessment.assessment_id
            or study.advanced_assessment_hash.lower() != advanced_assessment.content_hash.lower()
            or study.advanced_pit_manifest_canonical_hash.lower()
            != advanced_assessment.pit_manifest_canonical_hash.lower()
            or study.advanced_artifact_attestation_hash.lower()
            != advanced_assessment.artifact_attestation_hash.lower()
            or study.advanced_threshold_hash.lower() != advanced_assessment.threshold_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
        if (
            advanced_assessment.status is not AdvancedStateModelAssessmentStatus.ACCEPTED
            or advanced_assessment.blockers
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_GATE_NOT_ACCEPTED)
        if advanced_assessment.assessed_at > study.evaluated_at:
            blockers.append(StateModelQualificationBlockerCode.EVIDENCE_TIMELINE_INVALID)
        if candidate is not None and (
            advanced_assessment.candidate_id != candidate.candidate_id
            or advanced_assessment.candidate_version != candidate.candidate_version
            or advanced_assessment.candidate_evidence_hash.lower()
            != candidate.evidence_hash.lower()
            or advanced_assessment.methodology is not candidate.methodology
            or advanced_assessment.artifact_id != candidate.artifact.artifact_id
            or advanced_assessment.artifact_code_version != candidate.artifact.code_version
            or advanced_assessment.artifact_parameter_version
            != candidate.artifact.parameter_version
            or advanced_assessment.artifact_parameter_hash.lower()
            != candidate.artifact.parameter_hash.lower()
            or advanced_assessment.artifact_hash.lower() != candidate.artifact.artifact_hash.lower()
            or advanced_assessment.pit_manifest_id != candidate.pit_manifest_id
            or advanced_assessment.pit_manifest_hash.lower() != candidate.pit_manifest_hash.lower()
            or not advanced_assessment.pit_manifest_is_verified
            or not advanced_assessment.pit_manifest_is_complete
            or advanced_assessment.pit_manifest_coverage_ratio != Decimal("1")
            or advanced_assessment.pit_manifest_missing_count != 0
            or advanced_assessment.pit_manifest_estimated_count != 0
            or advanced_assessment.pit_manifest_unknown_count != 0
            or advanced_assessment.label_protocol_version
            != candidate.label_protocol.protocol_version
            or advanced_assessment.label_stability_evidence_hash.lower()
            != candidate.label_protocol.stability_evidence_hash.lower()
            or advanced_assessment.threshold_version != candidate.acceptance_threshold_version
            or not advanced_assessment.artifact_attestation_verified
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
        if (
            advanced_assessment.pit_manifest_as_of_time > advanced_assessment.assessed_at
            or advanced_assessment.pit_manifest_valid_until <= advanced_assessment.assessed_at
            or advanced_assessment.artifact_attestation_observed_at
            > advanced_assessment.assessed_at
            or advanced_assessment.artifact_attestation_valid_until
            <= advanced_assessment.assessed_at
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
        if baseline_shortfall is not None and (
            advanced_assessment.baseline_shortfall_specification_version
            != baseline_shortfall.specification_version
            or advanced_assessment.baseline_shortfall_evaluation_id
            != baseline_shortfall.evaluation_id
            or advanced_assessment.baseline_shortfall_report_hash.lower()
            != baseline_shortfall.content_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)

    if derived_metric_bundle is None:
        blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_MISSING)
    elif not isinstance(derived_metric_bundle, StateModelDerivedMetricBundle):
        blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH)
    else:
        if (
            derived_metric_bundle.content_hash.lower()
            != derived_metric_bundle.calculated_content_hash
        ):
            blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_HASH_MISMATCH)
        if (
            study.derived_metric_bundle_id != derived_metric_bundle.bundle_id
            or study.derived_metric_bundle_version != derived_metric_bundle.bundle_version
            or study.derived_metric_bundle_hash.lower()
            != derived_metric_bundle.content_hash.lower()
        ):
            blockers.append(
                StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH
            )
        if derived_metric_bundle.evaluated_at > study.evaluated_at:
            blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_FROM_FUTURE)
        if derived_metric_bundle.valid_until <= assessed_at:
            blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_STALE)
        if candidate is not None and (
            derived_metric_bundle.candidate_id != candidate.candidate_id
            or derived_metric_bundle.candidate_version != candidate.candidate_version
            or derived_metric_bundle.candidate_evidence_hash.lower()
            != candidate.evidence_hash.lower()
            or derived_metric_bundle.label_protocol_version
            != candidate.label_protocol.protocol_version
            or derived_metric_bundle.label_stability_evidence_hash.lower()
            != candidate.label_protocol.stability_evidence_hash.lower()
        ):
            blockers.append(
                StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH
            )

    if baseline_shortfall is None:
        blockers.append(StateModelQualificationBlockerCode.BASELINE_SHORTFALL_MISSING)
    else:
        if baseline_shortfall.content_hash.lower() != baseline_shortfall.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.BASELINE_REPORT_HASH_MISMATCH)
        if (
            baseline_shortfall.decision is not BaselineShortfallDecision.PROVEN
            or not baseline_shortfall.can_propose_advanced_model_research
            or baseline_shortfall.evidence_state is not BaselineEvidenceState.VERIFIED
        ):
            blockers.append(StateModelQualificationBlockerCode.BASELINE_SHORTFALL_NOT_PROVEN)
        if baseline_shortfall.evidence_evaluated_at > study.evaluated_at:
            blockers.append(StateModelQualificationBlockerCode.BASELINE_EVIDENCE_FROM_FUTURE)
        if (
            baseline_shortfall.evidence_valid_until is None
            or baseline_shortfall.evidence_valid_until <= assessed_at
        ):
            blockers.append(StateModelQualificationBlockerCode.BASELINE_EVIDENCE_STALE)
        if (
            study.baseline_shortfall_specification_version
            != baseline_shortfall.specification_version
            or study.baseline_shortfall_evaluation_id != baseline_shortfall.evaluation_id
            or study.baseline_shortfall_report_hash.lower()
            != baseline_shortfall.content_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.BASELINE_REPORT_HASH_MISMATCH)
        if candidate is not None:
            comparison = candidate.baseline_comparison
            if (
                comparison.shortfall_specification_version
                != baseline_shortfall.specification_version
                or comparison.shortfall_evaluation_id != baseline_shortfall.evaluation_id
                or comparison.shortfall_report_hash.lower()
                != baseline_shortfall.content_hash.lower()
                or comparison.baseline_key != baseline_shortfall.baseline_key
                or comparison.baseline_version != baseline_shortfall.baseline_version
                or candidate.pit_manifest_id != baseline_shortfall.pit_manifest_id
            ):
                blockers.append(StateModelQualificationBlockerCode.PIT_BINDING_MISMATCH)

    if policy is None:
        blockers.append(StateModelQualificationBlockerCode.POLICY_MISSING)
        metric_results: tuple[ComparativeMetricResult, ...] = ()
    else:
        if policy.content_hash.lower() != policy.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.POLICY_HASH_MISMATCH)
        if study.qualification_policy_version != policy.policy_version:
            blockers.append(StateModelQualificationBlockerCode.POLICY_BINDING_MISMATCH)
        if study.qualification_policy_hash.lower() != policy.content_hash.lower():
            blockers.append(StateModelQualificationBlockerCode.POLICY_BINDING_MISMATCH)
        if not policy.activated_at <= study.evaluated_at < policy.valid_until:
            blockers.append(StateModelQualificationBlockerCode.POLICY_INACTIVE)
        if not policy.activated_at <= assessed_at < policy.valid_until:
            blockers.append(StateModelQualificationBlockerCode.POLICY_INACTIVE)
        evidence_by_key = {item.metric_key: item for item in study.metrics}
        criteria_by_key = {item.metric_key: item for item in policy.metric_criteria}
        if (
            set(evidence_by_key) != set(criteria_by_key)
            or frozenset(criteria_by_key) != REQUIRED_QUALIFICATION_METRIC_KEYS
        ):
            blockers.append(StateModelQualificationBlockerCode.METRIC_SET_MISMATCH)
        results: list[ComparativeMetricResult] = []
        baseline_by_key = (
            {item.metric_key: item for item in baseline_shortfall.metrics}
            if baseline_shortfall is not None
            else {}
        )
        candidate_metrics = _candidate_metric_values(candidate) if candidate is not None else {}
        derived_metrics = (
            derived_metric_bundle.metric_values
            if isinstance(derived_metric_bundle, StateModelDerivedMetricBundle)
            else {}
        )
        for criterion in policy.metric_criteria:
            evidence = evidence_by_key.get(criterion.metric_key)
            if evidence is None:
                continue
            if evidence.unit != criterion.unit:
                blockers.append(StateModelQualificationBlockerCode.METRIC_UNIT_MISMATCH)
            baseline_metric = baseline_by_key.get(criterion.metric_key)
            if (
                baseline_metric is None
                or baseline_metric.unit != evidence.unit
                or baseline_metric.value != evidence.baseline_value
            ):
                blockers.append(StateModelQualificationBlockerCode.BASELINE_METRIC_BINDING_MISMATCH)
            authoritative_candidate_value = candidate_metrics.get(criterion.metric_key)
            if (
                authoritative_candidate_value is not None
                and authoritative_candidate_value != evidence.candidate_value
            ):
                blockers.append(
                    StateModelQualificationBlockerCode.CANDIDATE_METRIC_BINDING_MISMATCH
                )
            authoritative_derived_value = derived_metrics.get(criterion.metric_key)
            if (
                authoritative_derived_value is not None
                and authoritative_derived_value != evidence.candidate_value
            ):
                blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_VALUE_MISMATCH)
            delta = criterion.improvement_delta(
                baseline=evidence.baseline_value,
                candidate=evidence.candidate_value,
            )
            passed = delta >= criterion.minimum_improvement_delta
            if not passed:
                blockers.append(StateModelQualificationBlockerCode.METRIC_MINIMUM_DELTA_NOT_MET)
            results.append(
                ComparativeMetricResult(
                    metric_key=criterion.metric_key,
                    unit=criterion.unit,
                    direction=criterion.direction,
                    baseline_value=evidence.baseline_value,
                    candidate_value=evidence.candidate_value,
                    improvement_delta=delta,
                    minimum_improvement_delta=criterion.minimum_improvement_delta,
                    passed=passed,
                )
            )
        metric_results = tuple(results)

        criteria_by_coefficient = {
            item.coefficient_key: item for item in policy.coefficient_criteria
        }
        evidence_by_coefficient = {item.coefficient_key: item for item in study.policy_coefficients}
        expected_contract = {
            (item.coefficient_key, item.target_code, item.lag_periods)
            for item in policy.coefficient_criteria
        }
        actual_contract = {
            (item.coefficient_key, item.target_code, item.lag_periods)
            for item in study.policy_coefficients
        }
        candidate_targets = (
            {
                (target.target_code, candidate.policy_reaction.reaction_lag_periods)
                for target in candidate.policy_reaction.targets
            }
            if candidate is not None and candidate.policy_reaction is not None
            else set()
        )
        if (
            expected_contract != actual_contract
            or {
                (criterion.target_code, criterion.lag_periods)
                for criterion in policy.coefficient_criteria
            }
            != candidate_targets
        ):
            blockers.append(StateModelQualificationBlockerCode.POLICY_TARGET_SET_MISMATCH)
        for coefficient_key, coefficient_criterion in criteria_by_coefficient.items():
            coefficient_evidence = evidence_by_coefficient.get(coefficient_key)
            if coefficient_evidence is None:
                continue
            sign_matches = (
                coefficient_evidence.estimate > 0
                if coefficient_criterion.expected_sign is PolicyCoefficientSign.POSITIVE
                else coefficient_evidence.estimate < 0
            )
            interval_matches = (
                coefficient_evidence.confidence_interval_lower > 0
                if coefficient_criterion.expected_sign is PolicyCoefficientSign.POSITIVE
                else coefficient_evidence.confidence_interval_upper < 0
            )
            if not sign_matches:
                blockers.append(StateModelQualificationBlockerCode.POLICY_COEFFICIENT_SIGN_MISMATCH)
            if not interval_matches:
                blockers.append(
                    StateModelQualificationBlockerCode.POLICY_COEFFICIENT_INTERVAL_FAILED
                )
            if coefficient_evidence.p_value > coefficient_criterion.maximum_p_value:
                blockers.append(
                    StateModelQualificationBlockerCode.POLICY_COEFFICIENT_SIGNIFICANCE_FAILED
                )
            if abs(coefficient_evidence.estimate) < coefficient_criterion.minimum_absolute_estimate:
                blockers.append(
                    StateModelQualificationBlockerCode.POLICY_COEFFICIENT_MAGNITUDE_FAILED
                )

        diagnostics = study.policy_diagnostics
        if diagnostics.sample_count != study.sample_count:
            blockers.append(StateModelQualificationBlockerCode.SAMPLE_COUNT_MISMATCH)
        if diagnostics.sample_count < policy.minimum_policy_sample_count:
            blockers.append(StateModelQualificationBlockerCode.POLICY_SAMPLE_INSUFFICIENT)
        if diagnostics.adjusted_r_squared < policy.minimum_adjusted_r_squared:
            blockers.append(StateModelQualificationBlockerCode.POLICY_ADJUSTED_R_SQUARED_FAILED)
        if (
            diagnostics.residual_autocorrelation_p_value
            < policy.minimum_residual_autocorrelation_p_value
        ):
            blockers.append(StateModelQualificationBlockerCode.POLICY_RESIDUAL_DIAGNOSTIC_FAILED)
        if diagnostics.heteroskedasticity_p_value < policy.minimum_heteroskedasticity_p_value:
            blockers.append(
                StateModelQualificationBlockerCode.POLICY_HETEROSKEDASTICITY_DIAGNOSTIC_FAILED
            )
        if diagnostics.parameter_stability_p_value < policy.minimum_parameter_stability_p_value:
            blockers.append(StateModelQualificationBlockerCode.POLICY_PARAMETER_STABILITY_FAILED)
        if diagnostics.condition_number > policy.maximum_condition_number:
            blockers.append(StateModelQualificationBlockerCode.POLICY_CONDITION_NUMBER_FAILED)

    if candidate is not None and baseline_shortfall is not None:
        expected_window = (
            candidate.oos_metrics.window_start,
            candidate.oos_metrics.window_end,
            baseline_shortfall.window_start,
            baseline_shortfall.window_end,
            study.oos_window_start,
            study.oos_window_end,
        )
        if len(set(expected_window[::2])) != 1 or len(set(expected_window[1::2])) != 1:
            blockers.append(StateModelQualificationBlockerCode.OOS_WINDOW_MISMATCH)
        if (
            candidate.oos_metrics.sample_count != baseline_shortfall.observation_count
            or study.sample_count != candidate.oos_metrics.sample_count
        ):
            blockers.append(StateModelQualificationBlockerCode.SAMPLE_COUNT_MISMATCH)

    return _build_assessment(
        study_id=study.study_id,
        assessed_at=assessed_at,
        study=study,
        preregistration=preregistration,
        baseline_shortfall=baseline_shortfall,
        candidate=candidate,
        advanced_assessment=(
            advanced_assessment
            if isinstance(advanced_assessment, AdvancedStateModelAssessmentAttestation)
            else None
        ),
        derived_metric_bundle=(
            derived_metric_bundle
            if isinstance(derived_metric_bundle, StateModelDerivedMetricBundle)
            else None
        ),
        policy=policy,
        metric_results=metric_results,
        blockers=blockers,
    )


__all__ = [
    "StateModelQualificationAssessment",
    "evaluate_state_model_qualification",
    "missing_state_model_qualification_assessment",
]
