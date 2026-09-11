"""Canonical receipt-v4 envelope retaining its authenticated issuer and source."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_codec import (
    decode_account_owner_assignment_provenance_receipt_v4,
    encode_account_owner_assignment_provenance_receipt_v4,
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
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


class AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError(ValueError):
    """A persisted record does not match the exact v4 authenticated envelope."""


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("expected exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != keys:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("unexpected record shape")
    return data


def _text(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("expected exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("expected exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("expected exact boolean")
    return value


def _utc_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("expected aware clock")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clock(value: object) -> datetime:
    text = _text(value)
    parsed = datetime.fromisoformat(text)
    if _utc_text(parsed) != text:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("noncanonical UTC clock")
    return parsed


def encode_account_owner_assignment_provenance_receipt_v4_record(
    value: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
) -> dict[str, object]:
    """Encode complete nested evidence and non-secret authenticated source facts."""
    if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV4:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError("expected exact v4 record")
    try:
        value.__post_init__()
        authority = value.authority
        return {
            "receipt": encode_account_owner_assignment_provenance_receipt_v4(value.receipt),
            "issued_by": value.issued_by.to_payload(),
            "authority": {
                "principal_id": authority.principal_id,
                "user_id": authority.user_id,
                "authentication_context_hash": authority.authentication_context_hash,
                "actor_id": authority.actor_id,
                "is_authenticated": authority.is_authenticated,
                "is_active": authority.is_active,
                "is_staff": authority.is_staff,
                "is_superuser": authority.is_superuser,
                "rbac_role": authority.rbac_role,
                "source_id": authority.source_id,
                "source_version": authority.source_version,
                "source_content_hash": authority.source_content_hash,
                "recorded_at": _utc_text(authority.recorded_at),
                "valid_until": _utc_text(authority.valid_until),
            },
        }
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError(
            "record cannot be encoded"
        ) from error


def decode_account_owner_assignment_provenance_receipt_v4_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    """Reject shape/type substitutions before validating the cross-bound issuer."""
    try:
        data = _mapping(payload, {"receipt", "issued_by", "authority"})
        actor = _mapping(data["issued_by"], _ACTOR_KEYS)
        source = _mapping(data["authority"], _AUTHORITY_KEYS)
        result = PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            receipt=decode_account_owner_assignment_provenance_receipt_v4(data["receipt"]),
            issued_by=AccountOwnerAssignmentServerActor(
                actor_id=_text(actor["actor_id"]),
                user_id=_integer(actor["user_id"]),
                role=_text(actor["role"]),
                kind=_text(actor["kind"]),
                is_staff=_boolean(actor["is_staff"]),
            ),
            authority=CurrentAccountActorAuthorityV3(
                principal_id=_text(source["principal_id"]),
                user_id=_integer(source["user_id"]),
                authentication_context_hash=_text(source["authentication_context_hash"]),
                actor_id=_text(source["actor_id"]),
                is_authenticated=_boolean(source["is_authenticated"]),
                is_active=_boolean(source["is_active"]),
                is_staff=_boolean(source["is_staff"]),
                is_superuser=_boolean(source["is_superuser"]),
                rbac_role=_text(source["rbac_role"]),
                source_id=_text(source["source_id"]),
                source_version=_text(source["source_version"]),
                source_content_hash=_text(source["source_content_hash"]),
                recorded_at=_clock(source["recorded_at"]),
                valid_until=_clock(source["valid_until"]),
            ),
        )
        if encode_account_owner_assignment_provenance_receipt_v4_record(result) != data:
            raise ValueError("record roundtrip differs")
        return result
    except (TypeError, ValueError, KeyError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError(
            "invalid v4 authenticated record"
        ) from error
