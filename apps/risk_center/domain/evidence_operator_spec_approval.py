"""Pure immutable contracts for Evidence operator specification approvals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER = "risk_center"
EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY = "evidence_operator_spec_activation"


class EvidenceOperatorSpecApprovalActorKind(str, Enum):
    """Trusted server-side actor classifications for this approval capability."""

    HUMAN = "human"
    AI = "ai"
    SERVICE = "service"


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


def _require_user_id(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evidence_operator_spec_subject_identity_hash(
    *,
    subject_id: str,
    subject_version: str,
) -> str:
    """Return the stable lookup anchor for one subject identity."""

    _require_token(subject_id, "subject_id")
    _require_token(subject_version, "subject_version")
    return _canonical_hash(
        {
            "identity_kind": "evidence_operator_spec_approval_subject",
            "subject_id": subject_id,
            "subject_version": subject_version,
        }
    )


def evidence_operator_spec_approval_identity_hash(
    *,
    approval_id: str,
    approval_version: str,
) -> str:
    """Return the stable lookup anchor for one approval identity."""

    _require_token(approval_id, "approval_id")
    _require_token(approval_version, "approval_version")
    return _canonical_hash(
        {
            "identity_kind": "evidence_operator_spec_approval",
            "approval_id": approval_id,
            "approval_version": approval_version,
        }
    )


@dataclass(frozen=True)
class EvidenceOperatorSpecApprovalActor:
    """Server-authenticated actor identity, never reconstructed from request payloads."""

    actor_id: str
    kind: EvidenceOperatorSpecApprovalActorKind
    is_staff: bool
    user_id: int | None = None

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.kind) is not EvidenceOperatorSpecApprovalActorKind:
            raise TypeError("kind must be EvidenceOperatorSpecApprovalActorKind")
        if type(self.is_staff) is not bool:
            raise TypeError("is_staff must be bool")
        if self.kind is EvidenceOperatorSpecApprovalActorKind.HUMAN:
            _require_user_id(self.user_id, "human actor user_id")
        elif self.user_id is not None or self.is_staff:
            raise ValueError("non-human actors cannot claim a staff user identity")

    @property
    def is_human_staff(self) -> bool:
        """Return whether this server-authenticated actor may approve."""

        return self.kind is EvidenceOperatorSpecApprovalActorKind.HUMAN and self.is_staff


def _actor_payload(actor: EvidenceOperatorSpecApprovalActor) -> dict[str, object]:
    return {
        "actor_id": actor.actor_id,
        "kind": actor.kind.value,
        "is_staff": actor.is_staff,
        "user_id": actor.user_id,
    }


def _subject_payload(
    *,
    subject_id: str,
    subject_version: str,
    operator_id: str,
    operator_version: str,
    definition_hash: str,
    supersedes_activation_hash: str | None,
    requested_by: EvidenceOperatorSpecApprovalActor,
    requested_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "subject_id": subject_id,
        "subject_version": subject_version,
        "operator_id": operator_id,
        "operator_version": operator_version,
        "definition_hash": definition_hash,
        "supersedes_activation_hash": supersedes_activation_hash,
        "requested_by": _actor_payload(requested_by),
        "requested_at": _utc_text(requested_at),
        "valid_until": _utc_text(valid_until),
    }


@dataclass(frozen=True)
class EvidenceOperatorSpecApprovalSubject:
    """Immutable request to approve one exact Research-owned definition hash."""

    subject_id: str
    subject_version: str
    operator_id: str
    operator_version: str
    definition_hash: str
    supersedes_activation_hash: str | None
    requested_by: EvidenceOperatorSpecApprovalActor
    requested_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        subject_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        requested_by: EvidenceOperatorSpecApprovalActor,
        requested_at: datetime,
        valid_until: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject:
        """Validate and seal one exact approval subject."""

        payload = _subject_payload(
            subject_id=subject_id,
            subject_version=subject_version,
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=definition_hash,
            supersedes_activation_hash=supersedes_activation_hash,
            requested_by=requested_by,
            requested_at=requested_at,
            valid_until=valid_until,
        )
        return cls(
            subject_id=subject_id,
            subject_version=subject_version,
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=definition_hash,
            supersedes_activation_hash=supersedes_activation_hash,
            requested_by=requested_by,
            requested_at=requested_at,
            valid_until=valid_until,
            content_hash=_canonical_hash(payload),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "operator_id",
            "operator_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.definition_hash, "definition_hash")
        _require_optional_hash(
            self.supersedes_activation_hash,
            "supersedes_activation_hash",
        )
        if type(self.requested_by) is not EvidenceOperatorSpecApprovalActor:
            raise TypeError("requested_by must be EvidenceOperatorSpecApprovalActor")
        EvidenceOperatorSpecApprovalActor.__post_init__(self.requested_by)
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.valid_until, "valid_until")
        _require_hash(self.content_hash, "content_hash")
        if self.requested_at >= self.valid_until:
            raise ValueError("approval subject validity window is invalid")
        expected = _canonical_hash(
            _subject_payload(
                subject_id=self.subject_id,
                subject_version=self.subject_version,
                operator_id=self.operator_id,
                operator_version=self.operator_version,
                definition_hash=self.definition_hash,
                supersedes_activation_hash=self.supersedes_activation_hash,
                requested_by=self.requested_by,
                requested_at=self.requested_at,
                valid_until=self.valid_until,
            )
        )
        if self.content_hash != expected:
            raise ValueError("approval subject content_hash is invalid")

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether the subject may be approved at an aware cutoff."""

        _require_aware(as_of, "as_of")
        return self.requested_at <= as_of < self.valid_until


def _approval_payload(
    *,
    owner: str,
    capability: str,
    approval_id: str,
    approval_version: str,
    subject_hash: str,
    approved_by: EvidenceOperatorSpecApprovalActor,
    issued_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "owner": owner,
        "capability": capability,
        "approval_id": approval_id,
        "approval_version": approval_version,
        "subject_hash": subject_hash,
        "approved_by": _actor_payload(approved_by),
        "issued_at": _utc_text(issued_at),
        "valid_until": _utc_text(valid_until),
    }


@dataclass(frozen=True)
class EvidenceOperatorSpecApprovalRecord:
    """Risk Center's immutable human approval of one exact subject."""

    owner: str
    capability: str
    approval_id: str
    approval_version: str
    subject: EvidenceOperatorSpecApprovalSubject
    approved_by: EvidenceOperatorSpecApprovalActor
    issued_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        approval_id: str,
        approval_version: str,
        subject: EvidenceOperatorSpecApprovalSubject,
        approved_by: EvidenceOperatorSpecApprovalActor,
        issued_at: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord:
        """Create a fixed-authority approval after human/non-self checks."""

        value = cls(
            owner=EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER,
            capability=EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY,
            approval_id=approval_id,
            approval_version=approval_version,
            subject=subject,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=subject.valid_until,
            content_hash=_canonical_hash(
                _approval_payload(
                    owner=EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER,
                    capability=EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY,
                    approval_id=approval_id,
                    approval_version=approval_version,
                    subject_hash=subject.content_hash,
                    approved_by=approved_by,
                    issued_at=issued_at,
                    valid_until=subject.valid_until,
                )
            ),
        )
        return value

    def __post_init__(self) -> None:
        for field_name in (
            "owner",
            "capability",
            "approval_id",
            "approval_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if (
            self.owner != EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER
            or self.capability != EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY
        ):
            raise ValueError("Evidence operator spec approval authority is invalid")
        if type(self.subject) is not EvidenceOperatorSpecApprovalSubject:
            raise TypeError("subject must be EvidenceOperatorSpecApprovalSubject")
        EvidenceOperatorSpecApprovalSubject.__post_init__(self.subject)
        if type(self.approved_by) is not EvidenceOperatorSpecApprovalActor:
            raise TypeError("approved_by must be EvidenceOperatorSpecApprovalActor")
        EvidenceOperatorSpecApprovalActor.__post_init__(self.approved_by)
        if not self.approved_by.is_human_staff:
            raise ValueError("approval requires a human staff actor")
        if self.approved_by.actor_id == self.subject.requested_by.actor_id:
            raise ValueError("self approval is forbidden")
        requester_user_id = self.subject.requested_by.user_id
        if requester_user_id is not None and self.approved_by.user_id == requester_user_id:
            raise ValueError("self approval is forbidden")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        _require_hash(self.content_hash, "content_hash")
        if self.valid_until != self.subject.valid_until:
            raise ValueError("approval validity must match its sealed subject")
        if not self.subject.requested_at <= self.issued_at < self.valid_until:
            raise ValueError("approval issued outside its subject validity window")
        expected = _canonical_hash(
            _approval_payload(
                owner=self.owner,
                capability=self.capability,
                approval_id=self.approval_id,
                approval_version=self.approval_version,
                subject_hash=self.subject.content_hash,
                approved_by=self.approved_by,
                issued_at=self.issued_at,
                valid_until=self.valid_until,
            )
        )
        if self.content_hash != expected:
            raise ValueError("Evidence operator spec approval content_hash is invalid")

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether this approval is effective at an aware PIT cutoff."""

        _require_aware(as_of, "as_of")
        return self.issued_at <= as_of < self.valid_until


__all__ = [
    "EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY",
    "EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER",
    "EvidenceOperatorSpecApprovalActor",
    "EvidenceOperatorSpecApprovalActorKind",
    "EvidenceOperatorSpecApprovalRecord",
    "EvidenceOperatorSpecApprovalSubject",
    "evidence_operator_spec_approval_identity_hash",
    "evidence_operator_spec_subject_identity_hash",
]
