"""PIT historical analogy, path-study, and review-intent contracts for R7."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from apps.research.domain.scenario_probability_contracts import (
    ResearchEvidenceStatus,
    ScenarioInvalidationEvidence,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_text,
    require_token,
)


@dataclass(frozen=True)
class PointInTimeManifestReference:
    """Versioned PIT manifest reference with an explicit historical as-of."""

    manifest_id: str
    manifest_version: str
    as_of: datetime
    manifest_hash: str
    reference_hash: str

    @classmethod
    def create(
        cls,
        *,
        manifest_id: str,
        manifest_version: str,
        as_of: datetime,
        manifest_hash: str,
    ) -> PointInTimeManifestReference:
        """Freeze a canonical reference without resolving current data."""

        return cls(
            manifest_id=manifest_id,
            manifest_version=manifest_version,
            as_of=as_of,
            manifest_hash=manifest_hash,
            reference_hash=hash_components(
                manifest_id,
                manifest_version,
                as_of.isoformat(),
                manifest_hash,
            ),
        )

    def __post_init__(self) -> None:
        """Reject unversioned manifests, naive as-of times, and forged hashes."""

        require_token(self.manifest_id, "manifest_id")
        require_token(self.manifest_version, "manifest_version")
        _require_aware(self.as_of, "manifest as_of")
        require_sha256(self.manifest_hash, "manifest_hash")
        require_sha256(self.reference_hash, "manifest reference_hash")
        expected = hash_components(
            self.manifest_id,
            self.manifest_version,
            self.as_of.isoformat(),
            self.manifest_hash,
        )
        if self.reference_hash != expected:
            raise ValueError("PIT manifest reference_hash mismatch")


@dataclass(frozen=True)
class PointInTimeFeatureValue:
    """Feature value that was available no later than its manifest as-of."""

    feature_key: str
    value: Decimal
    unit: str
    source_version: str
    available_at: datetime

    def __post_init__(self) -> None:
        """Validate one finite, versioned, time-aware historical feature."""

        require_token(self.feature_key, "feature_key")
        require_text(self.unit, "unit", maximum=64)
        require_token(self.source_version, "source_version")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("historical feature value must be a finite Decimal")
        _require_aware(self.available_at, "feature available_at")


@dataclass(frozen=True)
class HistoricalAnalogyCandidateEvidence:
    """One historical candidate reconstructed only from its own PIT manifest."""

    candidate_id: str
    candidate_version: str
    window_start: datetime
    window_end: datetime
    pit_manifest: PointInTimeManifestReference
    feature_definition_version: str
    features: tuple[PointInTimeFeatureValue, ...]
    similarity_score: Decimal
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        candidate_version: str,
        window_start: datetime,
        window_end: datetime,
        pit_manifest: PointInTimeManifestReference,
        feature_definition_version: str,
        features: tuple[PointInTimeFeatureValue, ...],
        similarity_score: Decimal,
        evidence_refs: tuple[str, ...],
    ) -> HistoricalAnalogyCandidateEvidence:
        """Build a historical candidate and hash only frozen PIT inputs."""

        digest = _analogy_candidate_hash(
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            window_start=window_start,
            window_end=window_end,
            pit_manifest=pit_manifest,
            feature_definition_version=feature_definition_version,
            features=features,
            similarity_score=similarity_score,
            evidence_refs=evidence_refs,
        )
        return cls(
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            window_start=window_start,
            window_end=window_end,
            pit_manifest=pit_manifest,
            feature_definition_version=feature_definition_version,
            features=features,
            similarity_score=similarity_score,
            evidence_refs=evidence_refs,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Fail if any feature became available after the historical as-of."""

        for field_name, value in (
            ("candidate_id", self.candidate_id),
            ("candidate_version", self.candidate_version),
            ("feature_definition_version", self.feature_definition_version),
        ):
            require_token(value, field_name)
        _require_aware(self.window_start, "candidate window_start")
        _require_aware(self.window_end, "candidate window_end")
        if self.window_end <= self.window_start:
            raise ValueError("historical analogy window_end must follow window_start")
        if self.pit_manifest.as_of < self.window_end:
            raise ValueError("historical analogy manifest as_of cannot precede its window")
        if not self.features:
            raise ValueError("historical analogy candidate requires PIT features")
        feature_keys = [feature.feature_key for feature in self.features]
        if len(feature_keys) != len(set(feature_keys)):
            raise ValueError("historical analogy candidate contains duplicate features")
        if any(feature.available_at > self.pit_manifest.as_of for feature in self.features):
            raise ValueError("historical analogy feature uses look-ahead or current-value backfill")
        _require_probability(self.similarity_score, "similarity_score")
        _require_evidence_refs(self.evidence_refs)
        expected = _analogy_candidate_hash(
            candidate_id=self.candidate_id,
            candidate_version=self.candidate_version,
            window_start=self.window_start,
            window_end=self.window_end,
            pit_manifest=self.pit_manifest,
            feature_definition_version=self.feature_definition_version,
            features=self.features,
            similarity_score=self.similarity_score,
            evidence_refs=self.evidence_refs,
        )
        require_sha256(self.content_hash, "analogy candidate content_hash")
        if self.content_hash != expected:
            raise ValueError("historical analogy candidate content_hash mismatch")


@dataclass(frozen=True)
class HistoricalAnalogyStudyEvidence:
    """Immutable research-only analogy search result; never a probability model."""

    study_version: str
    scope_hash: str
    query_manifest: PointInTimeManifestReference
    feature_definition_version: str
    candidates: tuple[HistoricalAnalogyCandidateEvidence, ...]
    generated_at: datetime
    valid_until: datetime
    evidence_refs: tuple[str, ...]
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        study_version: str,
        scope: ScenarioResearchScope,
        query_manifest: PointInTimeManifestReference,
        feature_definition_version: str,
        candidates: tuple[HistoricalAnalogyCandidateEvidence, ...],
        generated_at: datetime,
        valid_until: datetime,
        evidence_refs: tuple[str, ...],
    ) -> HistoricalAnalogyStudyEvidence:
        """Freeze a PIT-only analogy study with mandatory research restrictions."""

        digest = _analogy_study_hash(
            study_version=study_version,
            scope_hash=scope.content_hash,
            query_manifest=query_manifest,
            feature_definition_version=feature_definition_version,
            candidates=candidates,
            generated_at=generated_at,
            valid_until=valid_until,
            evidence_refs=evidence_refs,
        )
        return cls(
            study_version=study_version,
            scope_hash=scope.content_hash,
            query_manifest=query_manifest,
            feature_definition_version=feature_definition_version,
            candidates=candidates,
            generated_at=generated_at,
            valid_until=valid_until,
            evidence_refs=evidence_refs,
            research_only=True,
            must_not_use_for_decision=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Enforce historical manifests and immutable research-only semantics."""

        require_token(self.study_version, "study_version")
        require_token(self.feature_definition_version, "feature_definition_version")
        require_sha256(self.scope_hash, "scope_hash")
        _require_aware(self.generated_at, "analogy generated_at")
        _require_aware(self.valid_until, "analogy valid_until")
        if self.valid_until <= self.generated_at:
            raise ValueError("analogy evidence valid_until must follow generated_at")
        if self.query_manifest.as_of > self.generated_at:
            raise ValueError("analogy query manifest cannot be future-dated")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("historical analogy study contains duplicate candidates")
        for candidate in self.candidates:
            if candidate.pit_manifest.as_of >= self.query_manifest.as_of:
                raise ValueError("historical analogy candidate must predate query as_of")
            if candidate.feature_definition_version != self.feature_definition_version:
                raise ValueError("historical analogy feature version mismatch")
        _require_evidence_refs(self.evidence_refs)
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValueError("historical analogy evidence must remain research-only")
        expected = _analogy_study_hash(
            study_version=self.study_version,
            scope_hash=self.scope_hash,
            query_manifest=self.query_manifest,
            feature_definition_version=self.feature_definition_version,
            candidates=self.candidates,
            generated_at=self.generated_at,
            valid_until=self.valid_until,
            evidence_refs=self.evidence_refs,
        )
        require_sha256(self.content_hash, "analogy study content_hash")
        if self.content_hash != expected:
            raise ValueError("historical analogy study content_hash mismatch")


@dataclass(frozen=True)
class MultiPeriodShockEvidence:
    """One explicit shock on one period of a path-dependent study."""

    period_index: int
    scenario_revision_id: UUID
    period_start: datetime
    period_end: datetime
    shock_key: str
    magnitude: Decimal
    unit: str
    source_version: str

    def __post_init__(self) -> None:
        """Validate one finite, ordered, versioned period shock."""

        if isinstance(self.period_index, bool) or self.period_index < 1:
            raise ValueError("period_index must be a positive integer")
        _require_aware(self.period_start, "shock period_start")
        _require_aware(self.period_end, "shock period_end")
        if self.period_end <= self.period_start:
            raise ValueError("shock period_end must follow period_start")
        require_token(self.shock_key, "shock_key")
        require_text(self.unit, "shock unit", maximum=64)
        require_token(self.source_version, "shock source_version")
        _require_finite(self.magnitude, "shock magnitude")


@dataclass(frozen=True)
class ConditionalProbabilityEvidence:
    """Research-only conditional frequency estimate with declared support."""

    condition_key: str
    target_scenario_revision_id: UUID
    probability: Decimal
    observation_count: int
    source_version: str

    def __post_init__(self) -> None:
        """Validate an explicitly sourced conditional estimate."""

        require_token(self.condition_key, "condition_key")
        require_token(self.source_version, "conditional source_version")
        _require_probability(self.probability, "conditional probability")
        _require_positive_count(self.observation_count, "conditional observation_count")


@dataclass(frozen=True)
class TransitionProbabilityEvidence:
    """Research-only scenario transition estimate with declared sample support."""

    from_scenario_revision_id: UUID
    to_scenario_revision_id: UUID
    horizon_periods: int
    probability: Decimal
    observation_count: int
    source_version: str

    def __post_init__(self) -> None:
        """Validate an explicitly sourced transition estimate."""

        if isinstance(self.horizon_periods, bool) or self.horizon_periods < 1:
            raise ValueError("transition horizon_periods must be positive")
        _require_probability(self.probability, "transition probability")
        _require_positive_count(self.observation_count, "transition observation_count")
        require_token(self.source_version, "transition source_version")


@dataclass(frozen=True)
class ScenarioPathStudyEvidence:
    """Versioned path/shock/probability evidence restricted to research use."""

    study_version: str
    scope_hash: str
    scenario_revision_ids: tuple[UUID, ...]
    pit_manifest: PointInTimeManifestReference
    shocks: tuple[MultiPeriodShockEvidence, ...]
    conditional_probabilities: tuple[ConditionalProbabilityEvidence, ...]
    transition_probabilities: tuple[TransitionProbabilityEvidence, ...]
    generated_at: datetime
    valid_until: datetime
    evidence_refs: tuple[str, ...]
    probability_sum_tolerance: Decimal
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        study_version: str,
        scope: ScenarioResearchScope,
        pit_manifest: PointInTimeManifestReference,
        shocks: tuple[MultiPeriodShockEvidence, ...],
        conditional_probabilities: tuple[ConditionalProbabilityEvidence, ...],
        transition_probabilities: tuple[TransitionProbabilityEvidence, ...],
        generated_at: datetime,
        valid_until: datetime,
        evidence_refs: tuple[str, ...],
        probability_sum_tolerance: Decimal,
    ) -> ScenarioPathStudyEvidence:
        """Freeze validated research evidence without turning it into a decision signal."""

        _validate_path_distributions(
            scenario_revision_ids=scope.scenario_revision_ids,
            conditional_probabilities=conditional_probabilities,
            transition_probabilities=transition_probabilities,
            tolerance=probability_sum_tolerance,
        )
        digest = _path_study_hash(
            study_version=study_version,
            scope_hash=scope.content_hash,
            scenario_revision_ids=scope.scenario_revision_ids,
            pit_manifest=pit_manifest,
            shocks=shocks,
            conditional_probabilities=conditional_probabilities,
            transition_probabilities=transition_probabilities,
            generated_at=generated_at,
            valid_until=valid_until,
            evidence_refs=evidence_refs,
            probability_sum_tolerance=probability_sum_tolerance,
        )
        return cls(
            study_version=study_version,
            scope_hash=scope.content_hash,
            scenario_revision_ids=scope.scenario_revision_ids,
            pit_manifest=pit_manifest,
            shocks=shocks,
            conditional_probabilities=conditional_probabilities,
            transition_probabilities=transition_probabilities,
            generated_at=generated_at,
            valid_until=valid_until,
            evidence_refs=evidence_refs,
            probability_sum_tolerance=probability_sum_tolerance,
            research_only=True,
            must_not_use_for_decision=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate chronology, restrictions, and the immutable evidence hash."""

        require_token(self.study_version, "path study_version")
        require_sha256(self.scope_hash, "scope_hash")
        if not self.scenario_revision_ids or len(self.scenario_revision_ids) != len(
            set(self.scenario_revision_ids)
        ):
            raise ValueError("path study requires unique scenario revisions")
        _require_probability(
            self.probability_sum_tolerance,
            "probability_sum_tolerance",
        )
        _require_aware(self.generated_at, "path generated_at")
        _require_aware(self.valid_until, "path valid_until")
        if self.pit_manifest.as_of > self.generated_at:
            raise ValueError("path PIT manifest cannot be future-dated")
        if self.valid_until <= self.generated_at:
            raise ValueError("path evidence valid_until must follow generated_at")
        if not self.shocks:
            raise ValueError("path study requires at least one period shock")
        indices = tuple(shock.period_index for shock in self.shocks)
        if indices != tuple(range(1, len(indices) + 1)):
            raise ValueError("path shocks must have contiguous period indices")
        for previous, current in zip(self.shocks, self.shocks[1:], strict=False):
            if current.period_start < previous.period_end:
                raise ValueError("path shock periods cannot overlap")
        _require_evidence_refs(self.evidence_refs)
        _validate_path_distributions(
            scenario_revision_ids=self.scenario_revision_ids,
            conditional_probabilities=self.conditional_probabilities,
            transition_probabilities=self.transition_probabilities,
            tolerance=self.probability_sum_tolerance,
        )
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValueError("path evidence must remain research-only")
        expected = _path_study_hash(
            study_version=self.study_version,
            scope_hash=self.scope_hash,
            scenario_revision_ids=self.scenario_revision_ids,
            pit_manifest=self.pit_manifest,
            shocks=self.shocks,
            conditional_probabilities=self.conditional_probabilities,
            transition_probabilities=self.transition_probabilities,
            generated_at=self.generated_at,
            valid_until=self.valid_until,
            evidence_refs=self.evidence_refs,
            probability_sum_tolerance=self.probability_sum_tolerance,
        )
        require_sha256(self.content_hash, "path study content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario path study content_hash mismatch")


@dataclass(frozen=True)
class ResearchEvidenceBlocker:
    """Stable blocker for an analogy or path evidence assessment."""

    reason_code: str
    detail: str


@dataclass(frozen=True)
class HistoricalAnalogyAssessment:
    """Fail-closed assessment that never derives a scenario probability."""

    assessment_version: str
    policy_version: str
    scope_hash: str
    evaluated_at: datetime
    status: ResearchEvidenceStatus
    candidate_count: int
    evidence_hash: str | None
    blockers: tuple[ResearchEvidenceBlocker, ...]
    probability_estimate: None
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Validate fail-closed status, research restrictions, and assessment hash."""

        require_token(self.assessment_version, "analogy assessment_version")
        require_token(self.policy_version, "analogy policy_version")
        require_sha256(self.scope_hash, "analogy scope_hash")
        _require_aware(self.evaluated_at, "analogy evaluated_at")
        if isinstance(self.candidate_count, bool) or self.candidate_count < 0:
            raise ValueError("analogy candidate_count cannot be negative")
        if self.evidence_hash is not None:
            require_sha256(self.evidence_hash, "analogy evidence_hash")
        if self.probability_estimate is not None:
            raise ValueError("historical analogy cannot publish a probability estimate")
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValueError("historical analogy assessment must remain research-only")
        if self.status is ResearchEvidenceStatus.AVAILABLE:
            if self.evidence_hash is None or self.blockers:
                raise ValueError("available analogy assessment requires unblocked evidence")
        elif not self.blockers:
            raise ValueError("unavailable analogy assessment requires blockers")
        expected = hash_components(
            self.assessment_version,
            self.policy_version,
            self.scope_hash,
            self.evaluated_at.isoformat(),
            self.status.value,
            str(self.candidate_count),
            self.evidence_hash or "",
            *(f"{item.reason_code}:{item.detail}" for item in self.blockers),
        )
        require_sha256(self.content_hash, "analogy assessment content_hash")
        if self.content_hash != expected:
            raise ValueError("historical analogy assessment content_hash mismatch")


@dataclass(frozen=True)
class ScenarioPathAssessment:
    """Fail-closed assessment exposing path evidence only for research."""

    assessment_version: str
    policy_version: str
    scope_hash: str
    evaluated_at: datetime
    status: ResearchEvidenceStatus
    evidence_hash: str | None
    blockers: tuple[ResearchEvidenceBlocker, ...]
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Validate fail-closed path status, restrictions, and assessment hash."""

        require_token(self.assessment_version, "path assessment_version")
        require_token(self.policy_version, "path policy_version")
        require_sha256(self.scope_hash, "path scope_hash")
        _require_aware(self.evaluated_at, "path evaluated_at")
        if self.evidence_hash is not None:
            require_sha256(self.evidence_hash, "path evidence_hash")
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValueError("scenario path assessment must remain research-only")
        if self.status is ResearchEvidenceStatus.AVAILABLE:
            if self.evidence_hash is None or self.blockers:
                raise ValueError("available path assessment requires unblocked evidence")
        elif not self.blockers:
            raise ValueError("unavailable path assessment requires blockers")
        expected = hash_components(
            self.assessment_version,
            self.policy_version,
            self.scope_hash,
            self.evaluated_at.isoformat(),
            self.status.value,
            self.evidence_hash or "",
            *(f"{item.reason_code}:{item.detail}" for item in self.blockers),
        )
        require_sha256(self.content_hash, "path assessment content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario path assessment content_hash mismatch")


@dataclass(frozen=True)
class ReviewReminderIntent:
    """Internal intent for human review; it performs no delivery or task mutation."""

    intent_version: str
    intent_id: str
    policy_version: str
    scenario_revision_id: UUID
    scenario_set_revision_id: UUID | None
    invalidation_evidence_hash: str
    created_at: datetime
    review_due_at: datetime
    reason_code: str
    dispatch_requested: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Reject forged or side-effecting review reminder intents."""

        require_token(self.intent_version, "intent_version")
        require_token(self.policy_version, "policy_version")
        require_sha256(self.intent_id, "intent_id")
        require_sha256(
            self.invalidation_evidence_hash,
            "invalidation_evidence_hash",
        )
        _require_aware(self.created_at, "intent created_at")
        _require_aware(self.review_due_at, "intent review_due_at")
        if self.review_due_at < self.created_at:
            raise ValueError("review_due_at cannot precede created_at")
        require_token(self.reason_code, "reason_code")
        if self.dispatch_requested:
            raise ValueError("review reminder intent cannot request direct dispatch")
        require_sha256(self.content_hash, "intent content_hash")
        expected = hash_components(
            self.intent_version,
            self.intent_id,
            self.policy_version,
            str(self.scenario_revision_id),
            str(self.scenario_set_revision_id or ""),
            self.invalidation_evidence_hash,
            self.created_at.isoformat(),
            self.review_due_at.isoformat(),
            self.reason_code,
            "False",
        )
        if self.content_hash != expected:
            raise ValueError("review reminder intent content_hash mismatch")


def assess_historical_analogy(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
    evidence: HistoricalAnalogyStudyEvidence | None,
    evaluated_at: datetime,
) -> HistoricalAnalogyAssessment:
    """Assess PIT analogy evidence without inferring or calibrating a probability."""

    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[ResearchEvidenceBlocker] = []
    status = ResearchEvidenceStatus.AVAILABLE
    if not policy.is_active(evaluated_at):
        status = ResearchEvidenceStatus.BLOCKED
        blockers.append(
            ResearchEvidenceBlocker(
                "scenario_research.policy.inactive",
                "scenario probability research policy is not active",
            )
        )
    if evidence is None:
        if status is not ResearchEvidenceStatus.BLOCKED:
            status = ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
        blockers.append(
            ResearchEvidenceBlocker(
                "historical_analogy.evidence.missing",
                "no PIT historical analogy evidence was supplied",
            )
        )
        candidate_count = 0
        evidence_hash = None
    else:
        if evidence.scope_hash != scope.content_hash:
            raise ValueError("historical analogy evidence scope mismatch")
        if evidence.generated_at > evaluated_at:
            raise ValueError("historical analogy evidence cannot be future-dated")
        candidate_count = len(evidence.candidates)
        evidence_hash = evidence.content_hash
        if candidate_count < policy.minimum_historical_analogies:
            if status is not ResearchEvidenceStatus.BLOCKED:
                status = ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
            blockers.append(
                ResearchEvidenceBlocker(
                    "historical_analogy.sample.insufficient",
                    "historical analogy count is below the versioned policy minimum",
                )
            )
        if (
            evidence.valid_until <= evaluated_at
            or evidence.generated_at + policy.maximum_research_evidence_age <= evaluated_at
        ):
            status = ResearchEvidenceStatus.BLOCKED
            blockers.append(
                ResearchEvidenceBlocker(
                    "historical_analogy.evidence.expired",
                    "historical analogy evidence has expired under the active policy",
                )
            )
    content_hash = hash_components(
        "historical-analogy-assessment.v1",
        policy.policy_version,
        scope.content_hash,
        evaluated_at.isoformat(),
        status.value,
        str(candidate_count),
        evidence_hash or "",
        *(f"{item.reason_code}:{item.detail}" for item in blockers),
    )
    return HistoricalAnalogyAssessment(
        assessment_version="historical-analogy-assessment.v1",
        policy_version=policy.policy_version,
        scope_hash=scope.content_hash,
        evaluated_at=evaluated_at,
        status=status,
        candidate_count=candidate_count,
        evidence_hash=evidence_hash,
        blockers=tuple(blockers),
        probability_estimate=None,
        research_only=True,
        must_not_use_for_decision=True,
        content_hash=content_hash,
    )


def assess_scenario_path_evidence(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
    evidence: ScenarioPathStudyEvidence | None,
    evaluated_at: datetime,
) -> ScenarioPathAssessment:
    """Assess path evidence while preserving its research-only boundary."""

    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[ResearchEvidenceBlocker] = []
    status = ResearchEvidenceStatus.AVAILABLE
    evidence_hash: str | None = None
    if not policy.is_active(evaluated_at):
        status = ResearchEvidenceStatus.BLOCKED
        blockers.append(
            ResearchEvidenceBlocker(
                "scenario_research.policy.inactive",
                "scenario probability research policy is not active",
            )
        )
    if evidence is None:
        if status is not ResearchEvidenceStatus.BLOCKED:
            status = ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
        blockers.append(
            ResearchEvidenceBlocker(
                "scenario_path.evidence.missing",
                "no PIT path study evidence was supplied",
            )
        )
    else:
        if (
            evidence.scope_hash != scope.content_hash
            or evidence.scenario_revision_ids != scope.scenario_revision_ids
        ):
            raise ValueError("scenario path evidence scope mismatch")
        if evidence.generated_at > evaluated_at:
            raise ValueError("scenario path evidence cannot be future-dated")
        evidence_hash = evidence.content_hash
        _validate_path_distributions(
            scenario_revision_ids=scope.scenario_revision_ids,
            conditional_probabilities=evidence.conditional_probabilities,
            transition_probabilities=evidence.transition_probabilities,
            tolerance=policy.probability_sum_tolerance,
        )
        has_estimates = bool(
            evidence.conditional_probabilities or evidence.transition_probabilities
        )
        has_low_support = any(
            estimate.observation_count < policy.minimum_path_probability_observations
            for estimate in evidence.conditional_probabilities
        ) or any(
            estimate.observation_count < policy.minimum_path_probability_observations
            for estimate in evidence.transition_probabilities
        )
        if not has_estimates or has_low_support:
            if status is not ResearchEvidenceStatus.BLOCKED:
                status = ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
            blockers.append(
                ResearchEvidenceBlocker(
                    "scenario_path.sample.insufficient",
                    "path probability support is below the versioned policy minimum",
                )
            )
        if (
            evidence.valid_until <= evaluated_at
            or evidence.generated_at + policy.maximum_research_evidence_age <= evaluated_at
        ):
            status = ResearchEvidenceStatus.BLOCKED
            blockers.append(
                ResearchEvidenceBlocker(
                    "scenario_path.evidence.expired",
                    "path study evidence has expired under the active policy",
                )
            )
    content_hash = hash_components(
        "scenario-path-assessment.v1",
        policy.policy_version,
        scope.content_hash,
        evaluated_at.isoformat(),
        status.value,
        evidence_hash or "",
        *(f"{item.reason_code}:{item.detail}" for item in blockers),
    )
    return ScenarioPathAssessment(
        assessment_version="scenario-path-assessment.v1",
        policy_version=policy.policy_version,
        scope_hash=scope.content_hash,
        evaluated_at=evaluated_at,
        status=status,
        evidence_hash=evidence_hash,
        blockers=tuple(blockers),
        research_only=True,
        must_not_use_for_decision=True,
        content_hash=content_hash,
    )


def build_review_reminder_intent(
    *,
    invalidation: ScenarioInvalidationEvidence,
    policy: ScenarioProbabilityResearchPolicy,
    created_at: datetime,
) -> ReviewReminderIntent:
    """Create a deterministic internal reminder intent without dispatching it."""

    _require_aware(created_at, "created_at")
    if invalidation.invalidated_at > created_at:
        raise ValueError("invalidation cannot be future-dated")
    intent_version = "scenario-review-reminder-intent.v1"
    review_due_at = created_at + policy.invalidation_review_delay
    identity_hash = hash_components(
        intent_version,
        invalidation.content_hash,
        policy.policy_version,
    )
    content_hash = hash_components(
        intent_version,
        identity_hash,
        policy.policy_version,
        str(invalidation.scenario_revision_id),
        str(invalidation.scenario_set_revision_id or ""),
        invalidation.content_hash,
        created_at.isoformat(),
        review_due_at.isoformat(),
        "scenario_invalidation.requires_human_review",
        "False",
    )
    return ReviewReminderIntent(
        intent_version=intent_version,
        intent_id=identity_hash,
        policy_version=policy.policy_version,
        scenario_revision_id=invalidation.scenario_revision_id,
        scenario_set_revision_id=invalidation.scenario_set_revision_id,
        invalidation_evidence_hash=invalidation.content_hash,
        created_at=created_at,
        review_due_at=review_due_at,
        reason_code="scenario_invalidation.requires_human_review",
        dispatch_requested=False,
        content_hash=content_hash,
    )


def _validate_path_distributions(
    *,
    scenario_revision_ids: tuple[UUID, ...],
    conditional_probabilities: tuple[ConditionalProbabilityEvidence, ...],
    transition_probabilities: tuple[TransitionProbabilityEvidence, ...],
    tolerance: Decimal,
) -> None:
    _require_probability(tolerance, "probability_sum_tolerance")
    members = set(scenario_revision_ids)
    conditional_groups: dict[str, list[ConditionalProbabilityEvidence]] = {}
    for conditional in conditional_probabilities:
        if conditional.target_scenario_revision_id not in members:
            raise ValueError("conditional probability target is outside scenario scope")
        conditional_groups.setdefault(conditional.condition_key, []).append(conditional)
    for condition_key, conditionals in conditional_groups.items():
        targets = {conditional.target_scenario_revision_id for conditional in conditionals}
        if targets != members or len(targets) != len(conditionals):
            raise ValueError(f"conditional distribution {condition_key} is incomplete")
        _require_distribution_sum(
            (conditional.probability for conditional in conditionals),
            tolerance=tolerance,
            label=f"conditional distribution {condition_key}",
        )

    transition_groups: dict[tuple[UUID, int], list[TransitionProbabilityEvidence]] = {}
    for transition in transition_probabilities:
        if (
            transition.from_scenario_revision_id not in members
            or transition.to_scenario_revision_id not in members
        ):
            raise ValueError("transition probability is outside scenario scope")
        key = (transition.from_scenario_revision_id, transition.horizon_periods)
        transition_groups.setdefault(key, []).append(transition)
    for key, transitions in transition_groups.items():
        targets = {transition.to_scenario_revision_id for transition in transitions}
        if targets != members or len(targets) != len(transitions):
            raise ValueError(f"transition distribution {key} is incomplete")
        _require_distribution_sum(
            (transition.probability for transition in transitions),
            tolerance=tolerance,
            label=f"transition distribution {key}",
        )


def _require_distribution_sum(
    probabilities: Iterable[Decimal],
    *,
    tolerance: Decimal,
    label: str,
) -> None:
    total = sum(probabilities, start=Decimal("0"))
    if abs(total - Decimal("1")) > tolerance:
        raise ValueError(f"{label} probabilities must sum to one")


def _analogy_candidate_hash(
    *,
    candidate_id: str,
    candidate_version: str,
    window_start: datetime,
    window_end: datetime,
    pit_manifest: PointInTimeManifestReference,
    feature_definition_version: str,
    features: tuple[PointInTimeFeatureValue, ...],
    similarity_score: Decimal,
    evidence_refs: tuple[str, ...],
) -> str:
    feature_parts = tuple(
        f"{item.feature_key}|{item.value}|{item.unit}|{item.source_version}|{item.available_at.isoformat()}"
        for item in features
    )
    return hash_components(
        candidate_id,
        candidate_version,
        window_start.isoformat(),
        window_end.isoformat(),
        pit_manifest.reference_hash,
        feature_definition_version,
        *feature_parts,
        str(similarity_score),
        *evidence_refs,
    )


def _analogy_study_hash(
    *,
    study_version: str,
    scope_hash: str,
    query_manifest: PointInTimeManifestReference,
    feature_definition_version: str,
    candidates: tuple[HistoricalAnalogyCandidateEvidence, ...],
    generated_at: datetime,
    valid_until: datetime,
    evidence_refs: tuple[str, ...],
) -> str:
    return hash_components(
        study_version,
        scope_hash,
        query_manifest.reference_hash,
        feature_definition_version,
        *(candidate.content_hash for candidate in candidates),
        generated_at.isoformat(),
        valid_until.isoformat(),
        *evidence_refs,
        "research_only",
        "must_not_use_for_decision",
    )


def _path_study_hash(
    *,
    study_version: str,
    scope_hash: str,
    scenario_revision_ids: tuple[UUID, ...],
    pit_manifest: PointInTimeManifestReference,
    shocks: tuple[MultiPeriodShockEvidence, ...],
    conditional_probabilities: tuple[ConditionalProbabilityEvidence, ...],
    transition_probabilities: tuple[TransitionProbabilityEvidence, ...],
    generated_at: datetime,
    valid_until: datetime,
    evidence_refs: tuple[str, ...],
    probability_sum_tolerance: Decimal,
) -> str:
    shock_parts = tuple(
        f"{item.period_index}|{item.scenario_revision_id}|{item.period_start.isoformat()}|"
        f"{item.period_end.isoformat()}|{item.shock_key}|{item.magnitude}|{item.unit}|"
        f"{item.source_version}"
        for item in shocks
    )
    conditional_parts = tuple(
        f"{item.condition_key}|{item.target_scenario_revision_id}|{item.probability}|"
        f"{item.observation_count}|{item.source_version}"
        for item in conditional_probabilities
    )
    transition_parts = tuple(
        f"{item.from_scenario_revision_id}|{item.to_scenario_revision_id}|"
        f"{item.horizon_periods}|{item.probability}|{item.observation_count}|"
        f"{item.source_version}"
        for item in transition_probabilities
    )
    return hash_components(
        study_version,
        scope_hash,
        *(str(revision_id) for revision_id in scenario_revision_ids),
        pit_manifest.reference_hash,
        *shock_parts,
        *conditional_parts,
        *transition_parts,
        generated_at.isoformat(),
        valid_until.isoformat(),
        *evidence_refs,
        str(probability_sum_tolerance),
        "research_only",
        "must_not_use_for_decision",
    )


def _require_evidence_refs(evidence_refs: tuple[str, ...]) -> None:
    if not evidence_refs:
        raise ValueError("research evidence requires at least one reference")
    for evidence_ref in evidence_refs:
        require_text(evidence_ref, "evidence_ref")


def _require_positive_count(value: int, field_name: str) -> None:
    if isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be positive")


def _require_probability(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value <= 1:
        raise ValueError(f"{field_name} must be a finite Decimal within [0, 1]")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
