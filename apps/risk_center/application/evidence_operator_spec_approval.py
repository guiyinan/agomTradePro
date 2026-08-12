"""ID-only approval command and exact/PIT read facades for operator specs."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if type(value) is not str or len(value) != 64 or value != value.lower():
        raise ValueError(f"{field_name} must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a sha256 hex digest") from error


def _require_optional_hash(value: object, field_name: str) -> None:
    if value is not None:
        _require_hash(value, field_name)


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


class EvidenceOperatorSpecApprovalUnavailable(ValueError):
    """An exact approval subject or record is unavailable at the PIT cutoff."""


class EvidenceOperatorSpecApprovalConflict(ValueError):
    """One stable identity already has a different immutable first winner."""


class EvidenceOperatorSpecApprovalCorruption(ValueError):
    """Trusted provider or persisted approval bytes fail integrity checks."""


@dataclass(frozen=True)
class ApproveEvidenceOperatorSpecCommand:
    """Caller-controlled input is limited to immutable IDs/versions and cutoff."""

    subject_id: str
    subject_version: str
    approval_id: str
    approval_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "approval_id",
            "approval_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetExactEvidenceOperatorSpecApprovalCommand:
    """Exact approval query with expected immutable content hash."""

    approval_id: str
    approval_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.approval_id, "approval_id")
        _require_token(self.approval_version, "approval_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetEvidenceOperatorSpecApprovalForDefinitionCommand:
    """PIT lookup matching the exact selector required by Research activation."""

    approval_id: str
    approval_version: str
    operator_id: str
    operator_version: str
    definition_hash: str
    supersedes_activation_hash: str | None
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "approval_id",
            "approval_version",
            "operator_id",
            "operator_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.definition_hash, "definition_hash")
        _require_optional_hash(
            self.supersedes_activation_hash,
            "supersedes_activation_hash",
        )
        _require_aware(self.as_of, "as_of")


class ExactEvidenceOperatorSpecApprovalSubjectProvider(Protocol):
    """Trusted Risk Center subject registry, not a caller payload projection."""

    def get_exact(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        """Return one exact immutable subject knowable at the cutoff."""


class EvidenceOperatorSpecApprovalRepository(Protocol):
    """Append-only approval store and strict exact/PIT reads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the first-winner transaction and private insert authority."""

    def now(self) -> datetime:
        """Return the authoritative Risk Center server clock."""

    def get_subject_winner(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        """Return a persisted subject identity winner without caller hash input."""

    def get_approval_winner(
        self,
        *,
        approval_id: str,
        approval_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return a persisted approval identity winner without caller hash input."""

    def append(
        self,
        approval: EvidenceOperatorSpecApprovalRecord,
        *,
        recorded_at: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord:
        """Append the subject and approval, or return the exact first winner."""

    def get_exact_by_hash(
        self,
        *,
        approval_id: str,
        approval_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return one exact approval identity/hash knowable at the cutoff."""

    def get_for_definition(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return one valid exact approval for a Research activation selector."""


class ApproveEvidenceOperatorSpec:
    """Approve a provider-owned immutable subject with server actor and clock."""

    def __init__(
        self,
        *,
        subject_provider: ExactEvidenceOperatorSpecApprovalSubjectProvider,
        repository: EvidenceOperatorSpecApprovalRepository,
        actor: EvidenceOperatorSpecApprovalActor,
    ) -> None:
        self._subject_provider = subject_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self,
        command: ApproveEvidenceOperatorSpecCommand,
    ) -> EvidenceOperatorSpecApprovalRecord:
        """Seal one first-winner approval after final trusted-subject reread."""

        if not self._actor.is_human_staff:
            raise EvidenceOperatorSpecApprovalUnavailable(
                "operator specification approval requires a human staff actor"
            )
        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Risk Center server clock")
            if command.as_of > recorded_at:
                raise EvidenceOperatorSpecApprovalUnavailable(
                    "future approval as_of is not permitted"
                )
            first_subject = self._read_subject(command)
            subject_winner = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=recorded_at,
            )
            approval_winner = self._repository.get_approval_winner(
                approval_id=command.approval_id,
                approval_version=command.approval_version,
                as_of=recorded_at,
            )
            final_subject = self._read_subject(command)
            if first_subject != final_subject:
                raise EvidenceOperatorSpecApprovalCorruption(
                    "operator specification approval subject changed during approval"
                )
            if subject_winner is not None and subject_winner != final_subject:
                raise EvidenceOperatorSpecApprovalConflict(
                    "approval subject identity already has a different first winner"
                )
            if subject_winner is not None and approval_winner is None:
                raise EvidenceOperatorSpecApprovalCorruption(
                    "approval subject winner exists without its approval record"
                )
            if approval_winner is not None:
                if (
                    approval_winner.subject != final_subject
                    or approval_winner.approved_by != self._actor
                ):
                    raise EvidenceOperatorSpecApprovalConflict(
                        "approval identity already has a different first winner"
                    )
                return approval_winner
            if not final_subject.is_valid_at(recorded_at):
                raise EvidenceOperatorSpecApprovalUnavailable(
                    "operator specification approval subject expired before approval"
                )
            candidate = EvidenceOperatorSpecApprovalRecord.create(
                approval_id=command.approval_id,
                approval_version=command.approval_version,
                subject=final_subject,
                approved_by=self._actor,
                issued_at=recorded_at,
            )
            persisted = self._repository.append(candidate, recorded_at=recorded_at)
            if persisted != candidate:
                raise EvidenceOperatorSpecApprovalConflict(
                    "concurrent approval first winner differs from requested record"
                )
            return persisted

    def _read_subject(
        self,
        command: ApproveEvidenceOperatorSpecCommand,
    ) -> EvidenceOperatorSpecApprovalSubject:
        subject = self._subject_provider.get_exact(
            subject_id=command.subject_id,
            subject_version=command.subject_version,
            as_of=command.as_of,
        )
        if subject is None:
            raise EvidenceOperatorSpecApprovalUnavailable(
                "exact operator specification approval subject is unavailable"
            )
        if (
            subject.subject_id != command.subject_id
            or subject.subject_version != command.subject_version
        ):
            raise EvidenceOperatorSpecApprovalCorruption(
                "operator specification approval subject identity substitution"
            )
        if not subject.is_valid_at(command.as_of):
            raise EvidenceOperatorSpecApprovalUnavailable(
                "operator specification approval subject is not valid at as_of"
            )
        return subject


class GetExactEvidenceOperatorSpecApproval:
    """Expose an exact identity/hash/PIT approval read."""

    def __init__(self, repository: EvidenceOperatorSpecApprovalRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactEvidenceOperatorSpecApprovalCommand,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return only the exact approval knowable at the cutoff."""

        return self._repository.get_exact_by_hash(
            approval_id=command.approval_id,
            approval_version=command.approval_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )


class GetEvidenceOperatorSpecApprovalForDefinition:
    """Expose the exact external-owner selector consumed by Research."""

    def __init__(self, repository: EvidenceOperatorSpecApprovalRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetEvidenceOperatorSpecApprovalForDefinitionCommand,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return a valid exact approval for one definition and predecessor."""

        return self._repository.get_for_definition(
            approval_id=command.approval_id,
            approval_version=command.approval_version,
            operator_id=command.operator_id,
            operator_version=command.operator_version,
            definition_hash=command.definition_hash,
            supersedes_activation_hash=command.supersedes_activation_hash,
            as_of=command.as_of,
        )


__all__ = [
    "ApproveEvidenceOperatorSpec",
    "ApproveEvidenceOperatorSpecCommand",
    "EvidenceOperatorSpecApprovalConflict",
    "EvidenceOperatorSpecApprovalCorruption",
    "EvidenceOperatorSpecApprovalRepository",
    "EvidenceOperatorSpecApprovalUnavailable",
    "ExactEvidenceOperatorSpecApprovalSubjectProvider",
    "GetEvidenceOperatorSpecApprovalForDefinition",
    "GetEvidenceOperatorSpecApprovalForDefinitionCommand",
    "GetExactEvidenceOperatorSpecApproval",
    "GetExactEvidenceOperatorSpecApprovalCommand",
]
