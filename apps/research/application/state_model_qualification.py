"""ID-only orchestration for R6 state-model qualification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.advanced_state_model import (
    AdvancedStateModelCandidateEvidence,
)
from apps.research.domain.state_model_baseline import BaselineShortfallReport
from apps.research.domain.state_model_qualification import (
    AdvancedStateModelAssessmentAttestation,
    StateModelComparativeStudyEvidence,
    StateModelDerivedMetricBundle,
    StateModelQualificationAssessment,
    StateModelQualificationBlockerCode,
    StateModelQualificationPolicy,
    StateModelStudyPreregistration,
    evaluate_state_model_qualification,
    missing_state_model_qualification_assessment,
)


class StateModelComparativeStudyProvider(Protocol):
    """Read one immutable comparative study by owner-issued identity."""

    def get_study(
        self,
        study_id: str,
        *,
        as_of: datetime,
    ) -> StateModelComparativeStudyEvidence | None:
        """Return the exact study visible at ``as_of`` without recomputation."""


class StateModelStudyPreregistrationProvider(Protocol):
    """Read the exact Research-owned preregistration bound by a study."""

    def get_preregistration(
        self,
        registration_id: str,
        *,
        as_of: datetime,
    ) -> StateModelStudyPreregistration | None:
        """Return the frozen experiment family, split, and embargo contract."""


class QualificationCandidateProvider(Protocol):
    """Read an exact advanced candidate version; callers cannot supply metrics."""

    def get_candidate(
        self,
        candidate_id: str,
        candidate_version: str,
        *,
        as_of: datetime,
    ) -> AdvancedStateModelCandidateEvidence | None:
        """Return an immutable candidate or ``None``."""


class QualificationAdvancedAssessmentProvider(Protocol):
    """Read the exact earlier S2 acceptance evidence for a candidate version."""

    def get_assessment(
        self,
        assessment_id: str,
        *,
        as_of: datetime,
    ) -> AdvancedStateModelAssessmentAttestation | None:
        """Return the exact sealed S2 attestation by Research-owned identity."""


class StateModelDerivedMetricBundleProvider(Protocol):
    """Read the exact owner bundle for non-candidate qualification metrics."""

    def get_bundle(
        self,
        bundle_id: str,
        bundle_version: str,
        *,
        as_of: datetime,
    ) -> StateModelDerivedMetricBundle | None:
        """Return an immutable sealed metric bundle or ``None``."""


class QualificationBaselineShortfallProvider(Protocol):
    """Read the exact sealed simple-baseline shortfall report."""

    def get_report(
        self,
        *,
        specification_version: str,
        evaluation_id: str,
        as_of: datetime,
    ) -> BaselineShortfallReport | None:
        """Return the owner report bound by both stable identities."""


class StateModelQualificationPolicyProvider(Protocol):
    """Read all metric, coefficient, and diagnostic thresholds by version."""

    def get_policy(
        self,
        policy_version: str,
        *,
        as_of: datetime,
    ) -> StateModelQualificationPolicy | None:
        """Return the exact policy; no code default may be substituted."""


@dataclass(frozen=True)
class AssessStateModelQualificationCommand:
    """ID-only request that cannot carry caller-derived evidence or thresholds."""

    study_id: str
    assessed_at: datetime

    def __post_init__(self) -> None:
        if (
            not self.study_id.strip()
            or len(self.study_id) > 160
            or any(character.isspace() for character in self.study_id)
        ):
            raise ValueError("study_id must be a bounded non-blank token")
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")


class AssessStateModelQualificationUseCase:
    """Authoritatively reread every seal and run the pure qualification gate."""

    def __init__(
        self,
        *,
        study_provider: StateModelComparativeStudyProvider,
        preregistration_provider: StateModelStudyPreregistrationProvider,
        candidate_provider: QualificationCandidateProvider,
        advanced_assessment_provider: QualificationAdvancedAssessmentProvider,
        derived_metric_bundle_provider: StateModelDerivedMetricBundleProvider,
        baseline_shortfall_provider: QualificationBaselineShortfallProvider,
        policy_provider: StateModelQualificationPolicyProvider,
    ) -> None:
        self._study_provider = study_provider
        self._preregistration_provider = preregistration_provider
        self._candidate_provider = candidate_provider
        self._advanced_assessment_provider = advanced_assessment_provider
        self._derived_metric_bundle_provider = derived_metric_bundle_provider
        self._baseline_shortfall_provider = baseline_shortfall_provider
        self._policy_provider = policy_provider

    def execute(
        self,
        command: AssessStateModelQualificationCommand,
    ) -> StateModelQualificationAssessment:
        """Return sealed evidence or blockers without training or promotion."""

        study = self._study_provider.get_study(
            command.study_id,
            as_of=command.assessed_at,
        )
        if study is None:
            return missing_state_model_qualification_assessment(
                study_id=command.study_id,
                assessed_at=command.assessed_at,
                blocker=StateModelQualificationBlockerCode.STUDY_MISSING,
            )
        if (
            study.study_id != command.study_id
            or study.study_id != study.calculated_study_id
            or study.content_hash.lower() != study.calculated_content_hash
        ):
            return missing_state_model_qualification_assessment(
                study_id=command.study_id,
                assessed_at=command.assessed_at,
                blocker=StateModelQualificationBlockerCode.STUDY_BINDING_MISMATCH,
            )
        candidate = self._candidate_provider.get_candidate(
            study.candidate_id,
            study.candidate_version,
            as_of=command.assessed_at,
        )
        advanced_assessment = self._advanced_assessment_provider.get_assessment(
            study.advanced_assessment_id,
            as_of=study.evaluated_at,
        )
        derived_metric_bundle = self._derived_metric_bundle_provider.get_bundle(
            study.derived_metric_bundle_id,
            study.derived_metric_bundle_version,
            as_of=study.evaluated_at,
        )
        baseline_shortfall = self._baseline_shortfall_provider.get_report(
            specification_version=study.baseline_shortfall_specification_version,
            evaluation_id=study.baseline_shortfall_evaluation_id,
            as_of=study.evaluated_at,
        )
        preregistration = self._preregistration_provider.get_preregistration(
            study.preregistration_id,
            as_of=study.evaluated_at,
        )
        policy = self._policy_provider.get_policy(
            study.qualification_policy_version,
            as_of=study.evaluated_at,
        )
        return evaluate_state_model_qualification(
            candidate=candidate,
            advanced_assessment=advanced_assessment,
            derived_metric_bundle=derived_metric_bundle,
            baseline_shortfall=baseline_shortfall,
            preregistration=preregistration,
            study=study,
            policy=policy,
            assessed_at=command.assessed_at,
        )


__all__ = [
    "AssessStateModelQualificationCommand",
    "AssessStateModelQualificationUseCase",
    "QualificationAdvancedAssessmentProvider",
    "QualificationBaselineShortfallProvider",
    "QualificationCandidateProvider",
    "StateModelComparativeStudyProvider",
    "StateModelDerivedMetricBundleProvider",
    "StateModelQualificationPolicyProvider",
    "StateModelStudyPreregistrationProvider",
]
