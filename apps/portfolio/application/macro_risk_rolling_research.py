"""Application orchestration for the research-only R4 rolling study."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4RollingResearchArtifact,
    R4RollingStudyInput,
)
from apps.portfolio.domain.macro_risk_rolling_service import evaluate_r4_rolling_study
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


class R4RollingRunStatus(str, Enum):
    """Outcome of one ID-only rolling study request."""

    COMPLETED_RESEARCH_ONLY = "completed_research_only"
    BLOCKED = "blocked"


class R4RollingRunBlockerCode(str, Enum):
    """Stable application-boundary blockers."""

    STUDY_UNAVAILABLE = "study_unavailable"
    STUDY_IDENTITY_MISMATCH = "study_identity_mismatch"
    STUDY_INVALID = "study_invalid"
    R3_PROMOTION_PROVIDER_MISSING = "r3_promotion_provider_missing"
    R3_PROMOTION_UNAVAILABLE = "r3_promotion_unavailable"
    R3_PROMOTION_INVALID = "r3_promotion_invalid"


class R4RollingStudyProvider(Protocol):
    """Read one exact study assembled from canonical owner projections."""

    def get_exact(
        self,
        *,
        study_id: str,
        study_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R4RollingStudyInput | None:
        """Return only the exact immutable study requested by identity and cutoff."""


class ExactR3PromotionProvider(Protocol):
    """Read authoritative Research approval for one exact R3 artifact."""

    def get_exact(
        self,
        *,
        capability_key: str,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        as_of: datetime,
    ) -> ExactR3PromotionAttestation | None:
        """Return the exact active attestation or ``None``."""


@dataclass(frozen=True)
class RunR4RollingStudyCommand:
    """Caller-safe command containing identity only, never research payloads."""

    study_id: str
    study_version: str
    expected_content_hash: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.study_id, "study_id")
        _require_text(self.study_version, "study_version")
        _require_sha256(self.expected_content_hash, "expected_content_hash")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")


@dataclass(frozen=True)
class R4RollingRunAssessment:
    """Bounded application result with no publication or execution authority."""

    status: R4RollingRunStatus
    artifact: R4RollingResearchArtifact | None
    blocker: R4RollingRunBlockerCode | None

    def __post_init__(self) -> None:
        completed = self.status is R4RollingRunStatus.COMPLETED_RESEARCH_ONLY
        if completed != (self.artifact is not None):
            raise ValueError("completed rolling assessment requires exactly one artifact")
        if completed == (self.blocker is not None):
            raise ValueError("blocked rolling assessment requires exactly one blocker")


class RunR4RollingStudy:
    """Load and evaluate one exact study while keeping capability readiness blocked."""

    def __init__(
        self,
        provider: R4RollingStudyProvider,
        promotion_provider: ExactR3PromotionProvider | None = None,
    ) -> None:
        self._provider = provider
        self._promotion_provider = promotion_provider

    def execute(self, command: RunR4RollingStudyCommand) -> R4RollingRunAssessment:
        """Return a sealed exploratory artifact or a stable fail-closed blocker."""

        study = self._provider.get_exact(
            study_id=command.study_id,
            study_version=command.study_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.evaluated_at,
        )
        if study is None:
            return _blocked(R4RollingRunBlockerCode.STUDY_UNAVAILABLE)
        if (
            study.study_id != command.study_id
            or study.study_version != command.study_version
            or study.content_hash.lower() != command.expected_content_hash.lower()
        ):
            return _blocked(R4RollingRunBlockerCode.STUDY_IDENTITY_MISMATCH)
        if self._promotion_provider is None:
            return _blocked(R4RollingRunBlockerCode.R3_PROMOTION_PROVIDER_MISSING)
        projection = study.windows[0].macro_projection
        attestation = self._promotion_provider.get_exact(
            capability_key="macro_factor_r3",
            artifact_id=projection.factor_artifact_id,
            artifact_version=projection.factor_artifact_version,
            artifact_content_hash=projection.factor_artifact_content_hash,
            decision_id=projection.promotion_decision_id,
            decision_version=projection.promotion_decision_version,
            decision_content_hash=projection.promotion_decision_content_hash,
            as_of=command.evaluated_at,
        )
        if attestation is None:
            return _blocked(R4RollingRunBlockerCode.R3_PROMOTION_UNAVAILABLE)
        if not _attestation_matches(study, attestation, command.evaluated_at):
            return _blocked(R4RollingRunBlockerCode.R3_PROMOTION_INVALID)
        try:
            artifact = evaluate_r4_rolling_study(
                study,
                promotion_attestation=attestation,
                evaluated_at=command.evaluated_at,
            )
        except ValueError:
            return _blocked(R4RollingRunBlockerCode.STUDY_INVALID)
        return R4RollingRunAssessment(
            status=R4RollingRunStatus.COMPLETED_RESEARCH_ONLY,
            artifact=artifact,
            blocker=None,
        )


def _blocked(code: R4RollingRunBlockerCode) -> R4RollingRunAssessment:
    return R4RollingRunAssessment(
        status=R4RollingRunStatus.BLOCKED,
        artifact=None,
        blocker=code,
    )


def _attestation_matches(
    study: R4RollingStudyInput,
    attestation: ExactR3PromotionAttestation,
    evaluated_at: datetime,
) -> bool:
    projection = study.windows[0].macro_projection
    return (
        attestation.artifact_id == projection.factor_artifact_id
        and attestation.artifact_version == projection.factor_artifact_version
        and attestation.artifact_content_hash == projection.factor_artifact_content_hash
        and attestation.decision_id == projection.promotion_decision_id
        and attestation.decision_version == projection.promotion_decision_version
        and attestation.decision_content_hash == projection.promotion_decision_content_hash
        and attestation.is_active_at(evaluated_at)
        and all(attestation.approved_at <= item.selection_as_of for item in study.windows)
    )


__all__ = [
    "ExactR3PromotionProvider",
    "R4RollingRunAssessment",
    "R4RollingRunBlockerCode",
    "R4RollingRunStatus",
    "R4RollingStudyProvider",
    "RunR4RollingStudy",
    "RunR4RollingStudyCommand",
]
