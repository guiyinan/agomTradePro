"""Strict canonical codecs for Evidence operator specification approvals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)


class EvidenceOperatorSpecApprovalCodecError(ValueError):
    """A stored approval payload is malformed, non-canonical, or forged."""


def encode_evidence_operator_spec_approval_actor(
    value: EvidenceOperatorSpecApprovalActor,
) -> dict[str, object]:
    """Encode one trusted server-side actor projection."""

    return {
        "actor_id": value.actor_id,
        "kind": value.kind.value,
        "is_staff": value.is_staff,
        "user_id": value.user_id,
    }


def decode_evidence_operator_spec_approval_actor(
    payload: object,
) -> EvidenceOperatorSpecApprovalActor:
    """Restore one exact actor projection."""

    data = _mapping(payload, {"actor_id", "kind", "is_staff", "user_id"})
    try:
        value = EvidenceOperatorSpecApprovalActor(
            actor_id=_string(data["actor_id"]),
            kind=EvidenceOperatorSpecApprovalActorKind(_string(data["kind"])),
            is_staff=_boolean(data["is_staff"]),
            user_id=_optional_positive_integer(data["user_id"]),
        )
    except (TypeError, ValueError) as error:
        raise EvidenceOperatorSpecApprovalCodecError("approval actor is invalid") from error
    _require_canonical(payload, encode_evidence_operator_spec_approval_actor(value))
    return value


def encode_evidence_operator_spec_approval_subject(
    value: EvidenceOperatorSpecApprovalSubject,
) -> dict[str, object]:
    """Encode one complete immutable approval subject."""

    return {
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "operator_id": value.operator_id,
        "operator_version": value.operator_version,
        "definition_hash": value.definition_hash,
        "supersedes_activation_hash": value.supersedes_activation_hash,
        "requested_by": encode_evidence_operator_spec_approval_actor(value.requested_by),
        "requested_at": _datetime_text(value.requested_at),
        "valid_until": _datetime_text(value.valid_until),
        "content_hash": value.content_hash,
    }


def decode_evidence_operator_spec_approval_subject(
    payload: object,
) -> EvidenceOperatorSpecApprovalSubject:
    """Restore and revalidate one complete approval subject."""

    data = _mapping(
        payload,
        {
            "subject_id",
            "subject_version",
            "operator_id",
            "operator_version",
            "definition_hash",
            "supersedes_activation_hash",
            "requested_by",
            "requested_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        value = EvidenceOperatorSpecApprovalSubject(
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            operator_id=_string(data["operator_id"]),
            operator_version=_string(data["operator_version"]),
            definition_hash=_string(data["definition_hash"]),
            supersedes_activation_hash=_optional_string(data["supersedes_activation_hash"]),
            requested_by=decode_evidence_operator_spec_approval_actor(data["requested_by"]),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (EvidenceOperatorSpecApprovalCodecError, TypeError, ValueError) as error:
        raise EvidenceOperatorSpecApprovalCodecError("approval subject is invalid") from error
    _require_canonical(payload, encode_evidence_operator_spec_approval_subject(value))
    return value


def encode_evidence_operator_spec_approval_record(
    value: EvidenceOperatorSpecApprovalRecord,
) -> dict[str, object]:
    """Encode one complete immutable Risk Center approval graph."""

    return {
        "owner": value.owner,
        "capability": value.capability,
        "approval_id": value.approval_id,
        "approval_version": value.approval_version,
        "subject": encode_evidence_operator_spec_approval_subject(value.subject),
        "approved_by": encode_evidence_operator_spec_approval_actor(value.approved_by),
        "issued_at": _datetime_text(value.issued_at),
        "valid_until": _datetime_text(value.valid_until),
        "content_hash": value.content_hash,
    }


def decode_evidence_operator_spec_approval_record(
    payload: object,
) -> EvidenceOperatorSpecApprovalRecord:
    """Restore one approval graph and reject authority/hash substitution."""

    data = _mapping(
        payload,
        {
            "owner",
            "capability",
            "approval_id",
            "approval_version",
            "subject",
            "approved_by",
            "issued_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        value = EvidenceOperatorSpecApprovalRecord(
            owner=_string(data["owner"]),
            capability=_string(data["capability"]),
            approval_id=_string(data["approval_id"]),
            approval_version=_string(data["approval_version"]),
            subject=decode_evidence_operator_spec_approval_subject(data["subject"]),
            approved_by=decode_evidence_operator_spec_approval_actor(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (EvidenceOperatorSpecApprovalCodecError, TypeError, ValueError) as error:
        raise EvidenceOperatorSpecApprovalCodecError("approval record is invalid") from error
    _require_canonical(payload, encode_evidence_operator_spec_approval_record(value))
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise EvidenceOperatorSpecApprovalCodecError("approval payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected bool")
    return value


def _optional_positive_integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_canonical(original: object, canonical: dict[str, object]) -> None:
    if original != canonical:
        raise EvidenceOperatorSpecApprovalCodecError("approval payload is not canonical")


__all__ = [
    "EvidenceOperatorSpecApprovalCodecError",
    "decode_evidence_operator_spec_approval_actor",
    "decode_evidence_operator_spec_approval_record",
    "decode_evidence_operator_spec_approval_subject",
    "encode_evidence_operator_spec_approval_actor",
    "encode_evidence_operator_spec_approval_record",
    "encode_evidence_operator_spec_approval_subject",
]
