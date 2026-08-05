"""Application-facing evidence collection for R6 advanced-state research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.advanced_state_model import (
    AdvancedStateModelAcceptanceThresholds,
    AdvancedStateModelAssessment,
    AdvancedStateModelAssessmentStatus,
    AdvancedStateModelBlockerCode,
    AdvancedStateModelCandidateEvidence,
    ExternalArtifactAttestation,
    StateModelPITManifestEvidence,
    evaluate_advanced_state_model_evidence,
)
from apps.research.domain.state_model_baseline import BaselineShortfallReport


class AdvancedStateModelCandidateProvider(Protocol):
    """Read one immutable externally precomputed candidate."""

    def get_candidate(
        self,
        candidate_id: str,
        *,
        evaluated_at: datetime,
    ) -> AdvancedStateModelCandidateEvidence | None:
        """Return the candidate or ``None`` without running a model."""


class BaselineShortfallReportProvider(Protocol):
    """Read the exact simple-baseline shortfall report bound by the candidate."""

    def get_report(
        self,
        *,
        specification_version: str,
        evaluation_id: str,
    ) -> BaselineShortfallReport | None:
        """Return frozen baseline evidence or ``None``."""


class StateModelPITManifestProvider(Protocol):
    """Application-facing Data Center PIT boundary; no ORM is exposed."""

    def get_manifest(self, manifest_id: str) -> StateModelPITManifestEvidence | None:
        """Return canonical manifest evidence or ``None``."""


class ExternalArtifactAttestationProvider(Protocol):
    """Read independent external-artifact hash attestation."""

    def get_attestation(self, artifact_id: str) -> ExternalArtifactAttestation | None:
        """Return current artifact attestation or ``None``."""


class AdvancedStateModelThresholdProvider(Protocol):
    """Read versioned acceptance thresholds without defaults."""

    def get_thresholds(
        self,
        threshold_version: str,
        *,
        evaluated_at: datetime,
    ) -> AdvancedStateModelAcceptanceThresholds | None:
        """Return exact threshold evidence or ``None``."""


@dataclass(frozen=True)
class AssessAdvancedStateModelResearchCommand:
    """Request to assess one external candidate at an aware timestamp."""

    candidate_id: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id cannot be blank")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")


def _missing_assessment(
    command: AssessAdvancedStateModelResearchCommand,
    blocker: AdvancedStateModelBlockerCode,
    *,
    candidate: AdvancedStateModelCandidateEvidence | None = None,
) -> AdvancedStateModelAssessment:
    return AdvancedStateModelAssessment(
        status=AdvancedStateModelAssessmentStatus.BLOCKED,
        candidate_id=command.candidate_id,
        candidate_version=(candidate.candidate_version if candidate is not None else None),
        methodology=(candidate.methodology if candidate is not None else None),
        artifact_hash=(candidate.artifact.artifact_hash if candidate is not None else None),
        pit_manifest_id=(candidate.pit_manifest_id if candidate is not None else None),
        pit_manifest_hash=(candidate.pit_manifest_hash if candidate is not None else None),
        label_protocol_version=(
            candidate.label_protocol.protocol_version if candidate is not None else None
        ),
        assessed_at=command.evaluated_at,
        blockers=(blocker,),
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
    )


class AssessAdvancedStateModelResearchUseCase:
    """Collect independent evidence and run the pure fail-closed gate."""

    def __init__(
        self,
        *,
        candidate_provider: AdvancedStateModelCandidateProvider,
        baseline_shortfall_provider: BaselineShortfallReportProvider,
        pit_manifest_provider: StateModelPITManifestProvider,
        artifact_attestation_provider: ExternalArtifactAttestationProvider,
        threshold_provider: AdvancedStateModelThresholdProvider,
    ) -> None:
        self._candidate_provider = candidate_provider
        self._baseline_shortfall_provider = baseline_shortfall_provider
        self._pit_manifest_provider = pit_manifest_provider
        self._artifact_attestation_provider = artifact_attestation_provider
        self._threshold_provider = threshold_provider

    def execute(
        self,
        command: AssessAdvancedStateModelResearchCommand,
    ) -> AdvancedStateModelAssessment:
        """Return accepted research evidence or stable blockers; never train."""

        candidate = self._candidate_provider.get_candidate(
            command.candidate_id,
            evaluated_at=command.evaluated_at,
        )
        if candidate is None:
            return _missing_assessment(
                command,
                AdvancedStateModelBlockerCode.CANDIDATE_EVIDENCE_MISSING,
            )
        comparison = candidate.baseline_comparison
        shortfall = self._baseline_shortfall_provider.get_report(
            specification_version=comparison.shortfall_specification_version,
            evaluation_id=comparison.shortfall_evaluation_id,
        )
        manifest = self._pit_manifest_provider.get_manifest(candidate.pit_manifest_id)
        attestation = self._artifact_attestation_provider.get_attestation(
            candidate.artifact.artifact_id
        )
        thresholds = self._threshold_provider.get_thresholds(
            candidate.acceptance_threshold_version,
            evaluated_at=command.evaluated_at,
        )
        if thresholds is None:
            return _missing_assessment(
                command,
                AdvancedStateModelBlockerCode.ACCEPTANCE_THRESHOLDS_MISSING,
                candidate=candidate,
            )
        return evaluate_advanced_state_model_evidence(
            candidate=candidate,
            baseline_shortfall=shortfall,
            pit_manifest=manifest,
            artifact_attestation=attestation,
            thresholds=thresholds,
            evaluated_at=command.evaluated_at,
        )


__all__ = [
    "AdvancedStateModelCandidateProvider",
    "AdvancedStateModelThresholdProvider",
    "AssessAdvancedStateModelResearchCommand",
    "AssessAdvancedStateModelResearchUseCase",
    "BaselineShortfallReportProvider",
    "ExternalArtifactAttestationProvider",
    "StateModelPITManifestProvider",
]
