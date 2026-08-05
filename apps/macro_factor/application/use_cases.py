"""Fail-closed orchestration for externally calculated R3 results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.macro_factor.domain.entities import (
    ExternalMacroFactorResearchResult,
    ImmutableMacroFactorResearchRecord,
    MacroFactorAssessmentStatus,
    MacroFactorBlockerCode,
    MacroFactorResearchAssessment,
    PITManifestEvidence,
    validate_external_macro_factor_result,
)


class ExternalMacroFactorResultProvider(Protocol):
    """Read externally precomputed model evidence; no trainer is exposed."""

    def get_external_result(
        self,
        evidence_id: str,
    ) -> ExternalMacroFactorResearchResult | None:
        """Return one typed external result or ``None`` when unavailable."""


class MacroFactorPITManifestProvider(Protocol):
    """Application-facing boundary for canonical Data Center PIT evidence."""

    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        """Return a canonical manifest projection without exposing Data Center ORM."""


class MacroFactorResearchResultRepository(Protocol):
    """Append-only repository boundary for accepted R3 evidence."""

    def add(
        self,
        record: ImmutableMacroFactorResearchRecord,
    ) -> ImmutableMacroFactorResearchRecord:
        """Append one immutable research record."""

    def get(self, result_id: str) -> ImmutableMacroFactorResearchRecord | None:
        """Return one immutable research record by identity."""


@dataclass(frozen=True)
class AssessExternalMacroFactorResearchCommand:
    """References used to assess one external R3 research artifact."""

    external_evidence_id: str
    expected_manifest_id: str
    assessed_at: datetime

    def __post_init__(self) -> None:
        if not self.external_evidence_id.strip():
            raise ValueError("external_evidence_id cannot be blank")
        if not self.expected_manifest_id.strip():
            raise ValueError("expected_manifest_id cannot be blank")
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")


def _blocked(
    command: AssessExternalMacroFactorResearchCommand,
    *,
    reasons: tuple[MacroFactorBlockerCode, ...],
    factor_version: str | None,
) -> MacroFactorResearchAssessment:
    return MacroFactorResearchAssessment(
        status=MacroFactorAssessmentStatus.BLOCKED,
        external_evidence_id=command.external_evidence_id,
        factor_version=factor_version,
        assessed_at=command.assessed_at,
        blocked_reasons=reasons,
        record=None,
        research_only=True,
        must_not_use_for_decision=True,
    )


class AssessExternalMacroFactorResearch:
    """Validate and append external evidence without fitting or publishing a model."""

    def __init__(
        self,
        *,
        external_result_provider: ExternalMacroFactorResultProvider,
        pit_manifest_provider: MacroFactorPITManifestProvider,
        repository: MacroFactorResearchResultRepository,
    ) -> None:
        self._external_result_provider = external_result_provider
        self._pit_manifest_provider = pit_manifest_provider
        self._repository = repository

    def execute(
        self,
        command: AssessExternalMacroFactorResearchCommand,
    ) -> MacroFactorResearchAssessment:
        """Fail closed on missing or inconsistent evidence, otherwise append it."""

        external_result = self._external_result_provider.get_external_result(
            command.external_evidence_id
        )
        if external_result is None:
            return _blocked(
                command,
                reasons=(MacroFactorBlockerCode.EXTERNAL_RESULT_MISSING,),
                factor_version=None,
            )
        manifest = self._pit_manifest_provider.get_manifest(command.expected_manifest_id)
        if manifest is None:
            return _blocked(
                command,
                reasons=(MacroFactorBlockerCode.PIT_MANIFEST_MISSING,),
                factor_version=external_result.factor_version,
            )
        blockers = list(
            validate_external_macro_factor_result(
                external_result,
                manifest,
                assessed_at=command.assessed_at,
            )
        )
        if external_result.pit_manifest_id != command.expected_manifest_id:
            blockers.append(MacroFactorBlockerCode.PIT_MANIFEST_MISMATCH)
        unique_blockers = tuple(dict.fromkeys(blockers))
        if unique_blockers:
            return _blocked(
                command,
                reasons=unique_blockers,
                factor_version=external_result.factor_version,
            )
        record = self._repository.add(external_result.to_record())
        return MacroFactorResearchAssessment(
            status=MacroFactorAssessmentStatus.ACCEPTED,
            external_evidence_id=command.external_evidence_id,
            factor_version=record.factor_version,
            assessed_at=command.assessed_at,
            blocked_reasons=(),
            record=record,
            research_only=True,
            must_not_use_for_decision=True,
        )


__all__ = [
    "AssessExternalMacroFactorResearch",
    "AssessExternalMacroFactorResearchCommand",
    "ExternalMacroFactorResultProvider",
    "MacroFactorPITManifestProvider",
    "MacroFactorResearchResultRepository",
]
