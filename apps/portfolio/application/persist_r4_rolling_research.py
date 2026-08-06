"""ID-only application boundary for persisting exact R4 rolling research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
    R4RollingStudyProvider,
)
from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchDraft,
    R4RollingResearchRecord,
)
from apps.portfolio.domain.macro_risk_rolling_contracts import R4RollingStudyInput
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class R4RollingResearchWriter(Protocol):
    """Append one application-authorized draft using repository clock authority."""

    def append(self, draft: R4RollingResearchDraft) -> R4RollingResearchRecord:
        """Persist and return the stable exact winner."""


class PersistR4RollingStatus(str, Enum):
    """Outcome of one ID-only persist request."""

    RECORDED_RESEARCH_ONLY = "recorded_research_only"
    BLOCKED = "blocked"


class PersistR4RollingBlockerCode(str, Enum):
    """Stable fail-closed reasons at the persistence application boundary."""

    STUDY_UNAVAILABLE = "study_unavailable"
    STUDY_IDENTITY_MISMATCH = "study_identity_mismatch"
    R3_PROMOTION_UNAVAILABLE = "r3_promotion_unavailable"
    R3_PROMOTION_INVALID = "r3_promotion_invalid"
    RECORD_REJECTED = "record_rejected"


@dataclass(frozen=True)
class PersistR4RollingResearchCommand:
    """Caller-safe identity and reproducibility metadata, never evidence payloads."""

    study_id: str
    study_version: str
    expected_study_content_hash: str
    evaluated_at: datetime
    producer_code_version: str
    dependency_lock_hash: str
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("study_id", self.study_id),
            ("study_version", self.study_version),
            ("producer_code_version", self.producer_code_version),
        ):
            _require_text(value, field_name)
        _require_sha256(self.expected_study_content_hash, "expected_study_content_hash")
        _require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        _require_aware(self.evaluated_at, "evaluated_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("valid_until must follow evaluated_at")


@dataclass(frozen=True)
class PersistR4RollingResearchAssessment:
    """Persist outcome without publication, decision, or execution authority."""

    status: PersistR4RollingStatus
    record: R4RollingResearchRecord | None
    blocker: PersistR4RollingBlockerCode | None

    def __post_init__(self) -> None:
        recorded = self.status is PersistR4RollingStatus.RECORDED_RESEARCH_ONLY
        if recorded != (self.record is not None):
            raise ValueError("recorded assessment requires exactly one record")
        if recorded == (self.blocker is not None):
            raise ValueError("blocked assessment requires exactly one blocker")


class PersistR4RollingResearch:
    """Re-read exact owner evidence before authorizing a repository draft."""

    def __init__(
        self,
        study_provider: R4RollingStudyProvider,
        promotion_provider: ExactR3PromotionProvider,
        writer: R4RollingResearchWriter,
    ) -> None:
        self._study_provider = study_provider
        self._promotion_provider = promotion_provider
        self._writer = writer

    def execute(
        self,
        command: PersistR4RollingResearchCommand,
    ) -> PersistR4RollingResearchAssessment:
        """Resolve exact inputs and persist only an authoritative sealed draft."""

        study = self._study_provider.get_exact(
            study_id=command.study_id,
            study_version=command.study_version,
            expected_content_hash=command.expected_study_content_hash,
            as_of=command.evaluated_at,
        )
        if study is None:
            return _blocked(PersistR4RollingBlockerCode.STUDY_UNAVAILABLE)
        if not _study_matches(command, study):
            return _blocked(PersistR4RollingBlockerCode.STUDY_IDENTITY_MISMATCH)
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
            return _blocked(PersistR4RollingBlockerCode.R3_PROMOTION_UNAVAILABLE)
        if not _attestation_matches(study, attestation, command.evaluated_at):
            return _blocked(PersistR4RollingBlockerCode.R3_PROMOTION_INVALID)
        try:
            draft = R4RollingResearchDraft(
                study=study,
                promotion_attestation=attestation,
                evaluated_at=command.evaluated_at,
                producer_code_version=command.producer_code_version,
                dependency_lock_hash=command.dependency_lock_hash,
                valid_until=command.valid_until,
            )
            record = self._writer.append(draft)
        except ValueError:
            return _blocked(PersistR4RollingBlockerCode.RECORD_REJECTED)
        return PersistR4RollingResearchAssessment(
            status=PersistR4RollingStatus.RECORDED_RESEARCH_ONLY,
            record=record,
            blocker=None,
        )


def _study_matches(
    command: PersistR4RollingResearchCommand,
    study: R4RollingStudyInput,
) -> bool:
    return (
        study.study_id == command.study_id
        and study.study_version == command.study_version
        and study.content_hash.lower() == command.expected_study_content_hash.lower()
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


def _blocked(code: PersistR4RollingBlockerCode) -> PersistR4RollingResearchAssessment:
    return PersistR4RollingResearchAssessment(
        status=PersistR4RollingStatus.BLOCKED,
        record=None,
        blocker=code,
    )


__all__ = [
    "PersistR4RollingBlockerCode",
    "PersistR4RollingResearch",
    "PersistR4RollingResearchAssessment",
    "PersistR4RollingResearchCommand",
    "PersistR4RollingStatus",
    "R4RollingResearchWriter",
]
