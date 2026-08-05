"""Component tests for R6 Application-facing evidence providers."""

from __future__ import annotations

from apps.research.application.advanced_state_model import (
    AssessAdvancedStateModelResearchCommand,
    AssessAdvancedStateModelResearchUseCase,
)
from apps.research.domain.advanced_state_model import (
    AdvancedStateModelAssessmentStatus,
    AdvancedStateModelBlockerCode,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    acceptance_thresholds,
    artifact_attestation,
    complete_candidate,
    complete_pit_manifest,
    proven_shortfall_report,
)


class _CandidateProvider:
    def __init__(self, candidate=complete_candidate()):  # type: ignore[no-untyped-def]
        self.candidate = candidate

    def get_candidate(self, candidate_id: str, *, evaluated_at):  # type: ignore[no-untyped-def]
        assert candidate_id == "advanced-state-candidate-v1"
        assert evaluated_at == NOW
        return self.candidate


class _ShortfallProvider:
    def __init__(self, report=proven_shortfall_report()):  # type: ignore[no-untyped-def]
        self.report = report

    def get_report(
        self,
        *,
        specification_version: str,
        evaluation_id: str,
    ):  # type: ignore[no-untyped-def]
        assert specification_version == "regime-simple-shortfall.v1"
        assert evaluation_id == "baseline-evaluation-v1"
        return self.report


class _PITProvider:
    def get_manifest(self, manifest_id: str):  # type: ignore[no-untyped-def]
        assert manifest_id == "pit-r6-state-model-v1"
        return complete_pit_manifest()


class _ArtifactProvider:
    def get_attestation(self, artifact_id: str):  # type: ignore[no-untyped-def]
        assert artifact_id == "external-hmm-artifact-v1"
        return artifact_attestation()


class _ThresholdProvider:
    def get_thresholds(
        self,
        threshold_version: str,
        *,
        evaluated_at,
    ):  # type: ignore[no-untyped-def]
        assert threshold_version == "advanced-state-acceptance-v1"
        assert evaluated_at == NOW
        return acceptance_thresholds()


def _use_case(*, shortfall_provider=None):  # type: ignore[no-untyped-def]
    return AssessAdvancedStateModelResearchUseCase(
        candidate_provider=_CandidateProvider(),
        baseline_shortfall_provider=shortfall_provider or _ShortfallProvider(),
        pit_manifest_provider=_PITProvider(),
        artifact_attestation_provider=_ArtifactProvider(),
        threshold_provider=_ThresholdProvider(),
    )


def test_application_accepts_only_external_research_evidence() -> None:
    assessment = _use_case().execute(
        AssessAdvancedStateModelResearchCommand(
            candidate_id="advanced-state-candidate-v1",
            evaluated_at=NOW,
        )
    )

    assert assessment.status is AdvancedStateModelAssessmentStatus.ACCEPTED
    assert assessment.artifact_hash == "d" * 64
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True


def test_application_missing_baseline_shortfall_fails_closed() -> None:
    assessment = _use_case(shortfall_provider=_ShortfallProvider(report=None)).execute(
        AssessAdvancedStateModelResearchCommand(
            candidate_id="advanced-state-candidate-v1",
            evaluated_at=NOW,
        )
    )

    assert assessment.status is AdvancedStateModelAssessmentStatus.BLOCKED
    assert AdvancedStateModelBlockerCode.BASELINE_SHORTFALL_MISSING in assessment.blockers
    assert assessment.must_not_replace_regime is True
