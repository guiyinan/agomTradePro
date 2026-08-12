"""Strict canonical codecs for approved Evidence operator spec activations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.research.domain.evidence_operator_spec_lifecycle import (
    ActivatedEvidenceOperatorSpec,
    EvidenceOperatorSpecApprovalReceipt,
    EvidenceOperatorSpecDefinition,
)
from apps.research.infrastructure.evidence_codec import (
    EvidenceCodecError,
    decode_evidence_operator_spec,
    encode_evidence_operator_spec,
)


class EvidenceOperatorSpecLifecycleCodecError(ValueError):
    """Persisted lifecycle payload is malformed, non-canonical, or forged."""


def encode_operator_spec_definition(
    value: EvidenceOperatorSpecDefinition,
) -> dict[str, object]:
    """Encode one trusted definition graph to canonical JSON primitives."""

    return {
        "operator_spec": encode_evidence_operator_spec(value.operator_spec),
        "supersedes_activation_hash": value.supersedes_activation_hash,
        "content_hash": value.content_hash,
    }


def decode_operator_spec_definition(payload: object) -> EvidenceOperatorSpecDefinition:
    """Restore one definition and recompute every nested hash."""

    data = _mapping(
        payload,
        {"operator_spec", "supersedes_activation_hash", "content_hash"},
    )
    try:
        value = EvidenceOperatorSpecDefinition(
            operator_spec=decode_evidence_operator_spec(data["operator_spec"]),
            supersedes_activation_hash=_optional_string(data["supersedes_activation_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (EvidenceCodecError, TypeError, ValueError) as error:
        raise EvidenceOperatorSpecLifecycleCodecError(
            "operator specification definition payload is invalid"
        ) from error
    _require_canonical(payload, encode_operator_spec_definition(value))
    return value


def encode_operator_spec_approval(
    value: EvidenceOperatorSpecApprovalReceipt,
) -> dict[str, object]:
    """Encode one exact external-owner approval receipt."""

    return {
        "owner": value.owner,
        "capability": value.capability,
        "approval_id": value.approval_id,
        "approval_version": value.approval_version,
        "owner_record_id": value.owner_record_id,
        "owner_record_version": value.owner_record_version,
        "owner_record_hash": value.owner_record_hash,
        "operator_id": value.operator_id,
        "operator_version": value.operator_version,
        "definition_hash": value.definition_hash,
        "supersedes_activation_hash": value.supersedes_activation_hash,
        "approved_by": value.approved_by,
        "issued_at": _datetime_text(value.issued_at),
        "valid_until": _datetime_text(value.valid_until),
        "content_hash": value.content_hash,
    }


def decode_operator_spec_approval(payload: object) -> EvidenceOperatorSpecApprovalReceipt:
    """Restore an approval and reject any authority or hash substitution."""

    data = _mapping(
        payload,
        {
            "owner",
            "capability",
            "approval_id",
            "approval_version",
            "owner_record_id",
            "owner_record_version",
            "owner_record_hash",
            "operator_id",
            "operator_version",
            "definition_hash",
            "supersedes_activation_hash",
            "approved_by",
            "issued_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        value = EvidenceOperatorSpecApprovalReceipt(
            owner=_string(data["owner"]),
            capability=_string(data["capability"]),
            approval_id=_string(data["approval_id"]),
            approval_version=_string(data["approval_version"]),
            owner_record_id=_string(data["owner_record_id"]),
            owner_record_version=_string(data["owner_record_version"]),
            owner_record_hash=_string(data["owner_record_hash"]),
            operator_id=_string(data["operator_id"]),
            operator_version=_string(data["operator_version"]),
            definition_hash=_string(data["definition_hash"]),
            supersedes_activation_hash=_optional_string(data["supersedes_activation_hash"]),
            approved_by=_string(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise EvidenceOperatorSpecLifecycleCodecError(
            "operator specification approval payload is invalid"
        ) from error
    _require_canonical(payload, encode_operator_spec_approval(value))
    return value


def encode_activated_operator_spec(
    value: ActivatedEvidenceOperatorSpec,
) -> dict[str, object]:
    """Encode the complete immutable approval and activation graph."""

    return {
        "definition": encode_operator_spec_definition(value.definition),
        "approval": encode_operator_spec_approval(value.approval),
        "recorded_at": _datetime_text(value.recorded_at),
        "content_hash": value.content_hash,
    }


def decode_activated_operator_spec(payload: object) -> ActivatedEvidenceOperatorSpec:
    """Restore and revalidate an exact activated operator spec graph."""

    data = _mapping(payload, {"definition", "approval", "recorded_at", "content_hash"})
    try:
        value = ActivatedEvidenceOperatorSpec(
            definition=decode_operator_spec_definition(data["definition"]),
            approval=decode_operator_spec_approval(data["approval"]),
            recorded_at=_datetime(data["recorded_at"]),
            content_hash=_string(data["content_hash"]),
        )
    except (EvidenceOperatorSpecLifecycleCodecError, TypeError, ValueError) as error:
        raise EvidenceOperatorSpecLifecycleCodecError(
            "activated operator specification payload is invalid"
        ) from error
    _require_canonical(payload, encode_activated_operator_spec(value))
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise EvidenceOperatorSpecLifecycleCodecError(
            "operator specification lifecycle payload shape is invalid"
        )
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


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
        raise EvidenceOperatorSpecLifecycleCodecError(
            "operator specification lifecycle payload is not canonical"
        )


__all__ = [
    "EvidenceOperatorSpecLifecycleCodecError",
    "decode_activated_operator_spec",
    "decode_operator_spec_approval",
    "decode_operator_spec_definition",
    "encode_activated_operator_spec",
    "encode_operator_spec_approval",
    "encode_operator_spec_definition",
]
