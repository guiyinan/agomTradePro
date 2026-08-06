"""R6 ID-only qualification orchestration tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

import pytest

from apps.research.application.state_model_qualification import (
    AssessStateModelQualificationCommand,
    AssessStateModelQualificationUseCase,
)
from apps.research.domain.advanced_state_model import AdvancedStateModelCandidateEvidence
from apps.research.domain.state_model_baseline import BaselineShortfallReport
from apps.research.domain.state_model_qualification import (
    AdvancedStateModelAssessmentAttestation,
    StateModelComparativeStudyEvidence,
    StateModelDerivedMetricBundle,
    StateModelQualificationBlockerCode,
    StateModelQualificationPolicy,
    StateModelQualificationStatus,
    StateModelStudyPreregistration,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    complete_candidate,
    proven_shortfall_report,
)
from tests.unit.research.state_model_qualification_factories import (
    accepted_advanced_assessment,
    complete_derived_metric_bundle,
    complete_qualification_study,
    qualification_policy,
    study_preregistration,
)


@dataclass
class QualificationProviders:
    """Exact in-memory providers with an observable ID-only call ledger."""

    study: StateModelComparativeStudyEvidence | None
    preregistration: StateModelStudyPreregistration | None
    candidate: AdvancedStateModelCandidateEvidence | None
    advanced_assessment: AdvancedStateModelAssessmentAttestation | None
    derived_metric_bundle: StateModelDerivedMetricBundle | None
    baseline: BaselineShortfallReport | None
    policy: StateModelQualificationPolicy | None
    calls: list[tuple[str, tuple[object, ...]]]

    def get_study(
        self,
        study_id: str,
        *,
        as_of: datetime,
    ) -> StateModelComparativeStudyEvidence | None:
        self.calls.append(("study", (study_id, as_of)))
        return self.study

    def get_preregistration(
        self,
        registration_id: str,
        *,
        as_of: datetime,
    ) -> StateModelStudyPreregistration | None:
        self.calls.append(("preregistration", (registration_id, as_of)))
        return self.preregistration

    def get_candidate(
        self,
        candidate_id: str,
        candidate_version: str,
        *,
        as_of: datetime,
    ) -> AdvancedStateModelCandidateEvidence | None:
        self.calls.append(("candidate", (candidate_id, candidate_version, as_of)))
        return self.candidate

    def get_assessment(
        self,
        assessment_id: str,
        *,
        as_of: datetime,
    ) -> AdvancedStateModelAssessmentAttestation | None:
        self.calls.append(("assessment", (assessment_id, as_of)))
        return self.advanced_assessment

    def get_bundle(
        self,
        bundle_id: str,
        bundle_version: str,
        *,
        as_of: datetime,
    ) -> StateModelDerivedMetricBundle | None:
        self.calls.append(("derived_metrics", (bundle_id, bundle_version, as_of)))
        return self.derived_metric_bundle

    def get_report(
        self,
        *,
        specification_version: str,
        evaluation_id: str,
        as_of: datetime,
    ) -> BaselineShortfallReport | None:
        self.calls.append(("baseline", (specification_version, evaluation_id, as_of)))
        return self.baseline

    def get_policy(
        self,
        policy_version: str,
        *,
        as_of: datetime,
    ) -> StateModelQualificationPolicy | None:
        self.calls.append(("policy", (policy_version, as_of)))
        return self.policy


def _providers(
    *,
    study: StateModelComparativeStudyEvidence | None = None,
) -> QualificationProviders:
    return QualificationProviders(
        study=complete_qualification_study() if study is None else study,
        preregistration=study_preregistration(),
        candidate=complete_candidate(),
        advanced_assessment=accepted_advanced_assessment(),
        derived_metric_bundle=complete_derived_metric_bundle(),
        baseline=proven_shortfall_report(),
        policy=qualification_policy(),
        calls=[],
    )


def _use_case(providers: QualificationProviders) -> AssessStateModelQualificationUseCase:
    return AssessStateModelQualificationUseCase(
        study_provider=providers,
        preregistration_provider=providers,
        candidate_provider=providers,
        advanced_assessment_provider=providers,
        derived_metric_bundle_provider=providers,
        baseline_shortfall_provider=providers,
        policy_provider=providers,
    )


def test_id_only_use_case_rereads_every_exact_owner_locator() -> None:
    providers = _providers()
    assert providers.study is not None

    result = _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id=providers.study.study_id,
            assessed_at=NOW,
        )
    )

    study = providers.study
    assert result.status is StateModelQualificationStatus.EVIDENCE_COMPLETE
    assert result.content_hash == result.calculated_content_hash
    assert providers.calls == [
        ("study", (study.study_id, NOW)),
        (
            "candidate",
            (study.candidate_id, study.candidate_version, NOW),
        ),
        (
            "assessment",
            (study.advanced_assessment_id, study.evaluated_at),
        ),
        (
            "derived_metrics",
            (
                study.derived_metric_bundle_id,
                study.derived_metric_bundle_version,
                study.evaluated_at,
            ),
        ),
        (
            "baseline",
            (
                study.baseline_shortfall_specification_version,
                study.baseline_shortfall_evaluation_id,
                study.evaluated_at,
            ),
        ),
        ("preregistration", (study.preregistration_id, study.evaluated_at)),
        ("policy", (study.qualification_policy_version, study.evaluated_at)),
    ]


def test_command_cannot_carry_caller_derived_metrics_or_thresholds() -> None:
    with pytest.raises(TypeError):
        AssessStateModelQualificationCommand(
            study_id="r6-comparative-study-v1",
            assessed_at=NOW,
            candidate_value="0.99",  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        AssessStateModelQualificationCommand(
            study_id=complete_qualification_study().study_id,
            assessed_at=NOW,
            expected_study_hash="f" * 64,  # type: ignore[call-arg]
        )


def test_missing_study_stops_before_any_dependent_read() -> None:
    providers = _providers()
    providers.study = None

    result = _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id="missing-r6-study",
            assessed_at=NOW,
        )
    )

    assert result.status is StateModelQualificationStatus.BLOCKED
    assert result.blockers == (StateModelQualificationBlockerCode.STUDY_MISSING,)
    assert result.may_request_promotion_review is False
    assert result.content_hash == result.calculated_content_hash
    assert providers.calls == [("study", ("missing-r6-study", NOW))]


def test_substituted_study_id_stops_before_any_dependent_read() -> None:
    providers = _providers()
    assert providers.study is not None
    requested_id = "requested-r6-study"

    result = _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id=requested_id,
            assessed_at=NOW,
        )
    )

    assert result.study_id == requested_id
    assert result.blockers == (StateModelQualificationBlockerCode.STUDY_BINDING_MISMATCH,)
    assert result.may_request_promotion_review is False
    assert providers.calls == [("study", (requested_id, NOW))]


def test_provider_substitution_and_policy_payload_tamper_fail_closed() -> None:
    providers = _providers()
    assert providers.study is not None
    candidate = complete_candidate()
    substituted = replace(
        candidate,
        candidate_version="advanced-state-hmm-substituted",
        evidence_hash="0" * 64,
    )
    providers.candidate = replace(
        substituted,
        evidence_hash=substituted.calculated_evidence_hash,
    )
    policy = qualification_policy()
    providers.policy = replace(policy, maximum_condition_number=policy.maximum_condition_number + 1)

    result = _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id=providers.study.study_id,
            assessed_at=NOW,
        )
    )

    assert StateModelQualificationBlockerCode.CANDIDATE_BINDING_MISMATCH in result.blockers
    assert StateModelQualificationBlockerCode.POLICY_HASH_MISMATCH in result.blockers
    assert result.may_request_promotion_review is False


def test_missing_authoritative_dependency_never_degrades_to_caller_values() -> None:
    providers = _providers()
    assert providers.study is not None
    providers.baseline = None
    providers.policy = None

    result = _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id=providers.study.study_id,
            assessed_at=NOW,
        )
    )

    assert StateModelQualificationBlockerCode.BASELINE_SHORTFALL_MISSING in result.blockers
    assert StateModelQualificationBlockerCode.POLICY_MISSING in result.blockers
    assert result.research_only is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_replace_regime is True


def test_provider_cannot_replace_content_under_the_requested_study_id() -> None:
    providers = _providers()
    assert providers.study is not None
    original = providers.study
    replacement = replace(original, evidence_ref="research://r6/provider-substitution")
    assert replacement.study_id != original.study_id
    object.__setattr__(replacement, "study_id", original.study_id)
    object.__setattr__(replacement, "content_hash", replacement.calculated_content_hash)
    providers.study = replacement

    result = _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id=original.study_id,
            assessed_at=NOW,
        )
    )

    assert result.blockers == (StateModelQualificationBlockerCode.STUDY_BINDING_MISMATCH,)
    assert providers.calls == [("study", (original.study_id, NOW))]
