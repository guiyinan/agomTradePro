"""Strict canonical codec for Account claimant provenance receipts v2."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v2 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
)


class AccountOwnerAssignmentProvenanceReceiptV2CodecError(ValueError):
    """Stored provenance v2 bytes are malformed or non-canonical."""


def encode_account_owner_assignment_provenance_receipt_v2_record(
    value: PersistedAccountOwnerAssignmentProvenanceReceiptV2,
) -> dict[str, object]:
    """Encode the complete sealed receipt and authenticated issuer."""
    PersistedAccountOwnerAssignmentProvenanceReceiptV2.__post_init__(value)
    receipt = {
        k: v
        for k, v in value.receipt.to_payload().items()
        if k not in {"activation_available", "must_not_execute"}
    }
    return {"receipt": receipt, "issued_by": value.issued_by.to_payload()}


def decode_account_owner_assignment_provenance_receipt_v2_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
    """Decode with exact shape, type, and canonical round-trip checks."""
    envelope = _mapping(payload)
    _keys(envelope, {"receipt", "issued_by"})
    data = _mapping(envelope["receipt"])
    issuer_data = _mapping(envelope["issued_by"])
    _keys(data, _RECEIPT_KEYS)
    _keys(issuer_data, _ACTOR_KEYS)
    try:
        claimant_data = _mapping(data["claimant"])
        _keys(claimant_data, _ACTOR_KEYS)
        claimant = AccountOwnerAssignmentActor(
            actor_id=_str(claimant_data["actor_id"]),
            user_id=_int(claimant_data["user_id"]),
            role=_str(claimant_data["role"]),
            kind=_str(claimant_data["kind"]),
            is_staff=_bool(claimant_data["is_staff"]),
        )
        receipt = AccountOwnerAssignmentProvenanceReceiptV2(
            receipt_id=_str(data["receipt_id"]),
            receipt_version=_str(data["receipt_version"]),
            provenance_kind=_str(data["provenance_kind"]),
            assignment_state=_str(data["assignment_state"]),
            assigned_owner_user_id=_opt_int(data["assigned_owner_user_id"]),
            account_namespace=_str(data["account_namespace"]),
            account_id=_str(data["account_id"]),
            underlying_unified_account_namespace=_str(data["underlying_unified_account_namespace"]),
            underlying_unified_account_id=_int(data["underlying_unified_account_id"]),
            row_observation_owner=_str(data["row_observation_owner"]),
            row_observation_artifact_type=_str(data["row_observation_artifact_type"]),
            row_observation_schema=_str(data["row_observation_schema"]),
            row_observation_id=_str(data["row_observation_id"]),
            row_observation_version=_str(data["row_observation_version"]),
            row_observation_identity_hash=_str(data["row_observation_identity_hash"]),
            row_observation_content_hash=_str(data["row_observation_content_hash"]),
            row_observation_supersedes_content_hash=_opt_str(
                data["row_observation_supersedes_content_hash"]
            ),
            row_observation_recorded_at=_dt(data["row_observation_recorded_at"]),
            row_observation_valid_until=_dt(data["row_observation_valid_until"]),
            source_content_hash=_str(data["source_content_hash"]),
            raw_observation_content_hash=_str(data["raw_observation_content_hash"]),
            row_is_active=_bool(data["row_is_active"]),
            row_is_present=_bool(data["row_is_present"]),
            row_is_tombstone=_bool(data["row_is_tombstone"]),
            row_user_id=_opt_int(data["row_user_id"]),
            claimant=claimant,
            issued_at=_dt(data["issued_at"]),
            recorded_at=_dt(data["recorded_at"]),
            valid_until=_dt(data["valid_until"]),
            supersedes_content_hash=_opt_str(data["supersedes_content_hash"]),
            identity_hash=_str(data["identity_hash"]),
            content_hash=_str(data["content_hash"]),
            owner=_str(data["owner"]),
            artifact_type=_str(data["artifact_type"]),
            schema=_str(data["schema"]),
            permission=_str(data["permission"]),
            status=_str(data["status"]),
            blocker_codes=_str_tuple(data["blocker_codes"]),
        )
        issuer = AccountOwnerAssignmentServerActor(
            actor_id=_str(issuer_data["actor_id"]),
            user_id=_int(issuer_data["user_id"]),
            role=_str(issuer_data["role"]),
            kind=_str(issuer_data["kind"]),
            is_staff=_bool(issuer_data["is_staff"]),
        )
        record = PersistedAccountOwnerAssignmentProvenanceReceiptV2(receipt, issuer)
    except (KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError(
            "invalid provenance v2 record"
        ) from error
    if encode_account_owner_assignment_provenance_receipt_v2_record(record) != payload:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError(
            "non-canonical provenance v2 record"
        )
    return record


_RECEIPT_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "receipt_id",
    "receipt_version",
    "provenance_kind",
    "assignment_state",
    "assigned_owner_user_id",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "row_observation_owner",
    "row_observation_artifact_type",
    "row_observation_schema",
    "row_observation_id",
    "row_observation_version",
    "row_observation_identity_hash",
    "row_observation_content_hash",
    "row_observation_supersedes_content_hash",
    "row_observation_recorded_at",
    "row_observation_valid_until",
    "source_content_hash",
    "raw_observation_content_hash",
    "row_is_active",
    "row_is_present",
    "row_is_tombstone",
    "row_user_id",
    "claimant",
    "issued_at",
    "recorded_at",
    "valid_until",
    "supersedes_content_hash",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("expected exact mapping")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("invalid payload shape")


def _str(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("expected exact string")
    return value


def _opt_str(value: object) -> str | None:
    return None if value is None else _str(value)


def _int(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("expected exact integer")
    return value


def _opt_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("expected exact boolean")
    return value


def _dt(value: object) -> datetime:
    text = _str(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("expected UTC Z time")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.isoformat().replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("non-canonical time")
    return result


def _str_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountOwnerAssignmentProvenanceReceiptV2CodecError("expected exact list")
    return tuple(_str(item) for item in cast(list[object], value))


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV2CodecError",
    "decode_account_owner_assignment_provenance_receipt_v2_record",
    "encode_account_owner_assignment_provenance_receipt_v2_record",
]
