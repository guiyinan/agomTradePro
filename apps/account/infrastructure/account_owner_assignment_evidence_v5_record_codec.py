"""Canonical authenticated record codec for Account owner evidence v5."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    PersistedAccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.validation_graph import (
    reuse_validated_decode,
    validation_graph_operation,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_codec import (
    decode_account_owner_assignment_evidence_v5,
    encode_account_owner_assignment_evidence_v5,
)

_AUTHORITY_KEYS = {
    "principal_id",
    "user_id",
    "authentication_context_hash",
    "actor_id",
    "is_authenticated",
    "is_active",
    "is_staff",
    "is_superuser",
    "rbac_role",
    "source_id",
    "source_version",
    "source_content_hash",
    "recorded_at",
    "valid_until",
}


class AccountOwnerAssignmentEvidenceV5RecordCodecError(ValueError):
    """A persisted evidence record is malformed or not canonical v5."""


def _mapping(value: object, expected: set[str], name: str) -> dict[str, object]:
    """Require one exact string-keyed mapping with a closed-world shape."""

    if type(value) is not dict:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(f"{name} must be an exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != expected:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            f"{name} has an invalid canonical shape"
        )
    return data


def _text(value: object, name: str) -> str:
    """Require one exact string before semantic construction."""

    if type(value) is not str:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(f"{name} must be an exact string")
    return value


def _integer(value: object, name: str) -> int:
    """Require one exact integer and therefore reject boolean substitutions."""

    if type(value) is not int:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(f"{name} must be an exact integer")
    return value


def _boolean(value: object, name: str) -> bool:
    """Require one exact boolean and reject integer truthiness."""

    if type(value) is not bool:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(f"{name} must be an exact boolean")
    return value


def _seal(value: object, name: str) -> str:
    """Require a non-empty lowercase SHA-256 content seal."""

    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            f"{name} must be a full lowercase SHA-256 seal"
        )
    return text


def _utc_text(value: datetime, name: str) -> str:
    """Encode an aware datetime as canonical UTC text with microseconds."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            f"{name} must be an exact aware datetime"
        )
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clock(value: object, name: str) -> datetime:
    """Decode only canonical UTC ``Z`` text with explicit microseconds."""

    text = _text(value, name)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            f"{name} must use canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(f"{name} is invalid") from error
    if _utc_text(parsed, name) != text:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            f"{name} must include canonical microseconds"
        )
    return parsed


def _authority_payload(value: CurrentAccountActorAuthorityV3) -> dict[str, object]:
    """Encode all authenticated authority facts without dropping source fields."""

    if type(value) is not CurrentAccountActorAuthorityV3:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            "authority must be an exact CurrentAccountActorAuthorityV3"
        )
    value.__post_init__()
    return {
        "principal_id": value.principal_id,
        "user_id": value.user_id,
        "authentication_context_hash": value.authentication_context_hash,
        "actor_id": value.actor_id,
        "is_authenticated": value.is_authenticated,
        "is_active": value.is_active,
        "is_staff": value.is_staff,
        "is_superuser": value.is_superuser,
        "rbac_role": value.rbac_role,
        "source_id": value.source_id,
        "source_version": value.source_version,
        "source_content_hash": value.source_content_hash,
        "recorded_at": _utc_text(value.recorded_at, "recorded_at"),
        "valid_until": _utc_text(value.valid_until, "valid_until"),
    }


def _decode_authority(payload: object) -> CurrentAccountActorAuthorityV3:
    """Decode and validate all fourteen authority fields exactly."""

    data = _mapping(payload, _AUTHORITY_KEYS, "authority")
    return CurrentAccountActorAuthorityV3(
        principal_id=_text(data["principal_id"], "principal_id"),
        user_id=_integer(data["user_id"], "user_id"),
        authentication_context_hash=_seal(
            data["authentication_context_hash"], "authentication_context_hash"
        ),
        actor_id=_text(data["actor_id"], "actor_id"),
        is_authenticated=_boolean(data["is_authenticated"], "is_authenticated"),
        is_active=_boolean(data["is_active"], "is_active"),
        is_staff=_boolean(data["is_staff"], "is_staff"),
        is_superuser=_boolean(data["is_superuser"], "is_superuser"),
        rbac_role=_text(data["rbac_role"], "rbac_role"),
        source_id=_text(data["source_id"], "source_id"),
        source_version=_text(data["source_version"], "source_version"),
        source_content_hash=_seal(data["source_content_hash"], "source_content_hash"),
        recorded_at=_clock(data["recorded_at"], "recorded_at"),
        valid_until=_clock(data["valid_until"], "valid_until"),
    )


@validation_graph_operation
def encode_account_owner_assignment_evidence_v5_record(
    value: PersistedAccountOwnerAssignmentEvidenceV5,
) -> dict[str, object]:
    """Encode a complete evidence graph and its authenticated source envelope."""

    if type(value) is not PersistedAccountOwnerAssignmentEvidenceV5:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            "expected exact PersistedAccountOwnerAssignmentEvidenceV5"
        )
    try:
        value.__post_init__()
        return {
            "evidence": encode_account_owner_assignment_evidence_v5(value.evidence),
            "authority": _authority_payload(value.authority),
        }
    except (AttributeError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            "evidence v5 record cannot be encoded"
        ) from error


@validation_graph_operation
@reuse_validated_decode("account-owner-assignment-evidence-v5-record")
def decode_account_owner_assignment_evidence_v5_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentEvidenceV5:
    """Decode a closed-world v5 record and require exact canonical roundtrip."""

    try:
        data = _mapping(payload, {"evidence", "authority"}, "record")
        result = PersistedAccountOwnerAssignmentEvidenceV5(
            evidence=decode_account_owner_assignment_evidence_v5(data["evidence"]),
            authority=_decode_authority(data["authority"]),
        )
        if encode_account_owner_assignment_evidence_v5_record(result) != data:
            raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
                "evidence v5 record is not canonical"
            )
        return result
    except AccountOwnerAssignmentEvidenceV5RecordCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5RecordCodecError(
            "invalid authenticated evidence v5 record"
        ) from error


__all__ = [
    "AccountOwnerAssignmentEvidenceV5RecordCodecError",
    "decode_account_owner_assignment_evidence_v5_record",
    "encode_account_owner_assignment_evidence_v5_record",
]
