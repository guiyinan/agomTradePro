"""Strict canonical codec for Account owner-assignment provenance receipts."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt import (
    PersistedAccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceipt,
)


class AccountOwnerAssignmentProvenanceReceiptCodecError(ValueError):
    """A persisted provenance receipt is malformed or non-canonical."""


def encode_account_owner_assignment_provenance_receipt_record(
    value: PersistedAccountOwnerAssignmentProvenanceReceipt,
) -> dict[str, object]:
    """Encode one complete receipt and authenticated issuer."""

    PersistedAccountOwnerAssignmentProvenanceReceipt.__post_init__(value)
    payload = value.receipt.to_payload()
    receipt = {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }
    return {"receipt": receipt, "issued_by": value.issued_by.to_payload()}


def decode_account_owner_assignment_provenance_receipt_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
    """Decode and canonical-roundtrip-check one persisted receipt."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"receipt", "issued_by"}, "record")
    receipt_data = _mapping(envelope["receipt"], "receipt")
    actor_data = _mapping(envelope["issued_by"], "issued_by")
    _exact_keys(receipt_data, _RECEIPT_KEYS, "receipt")
    _exact_keys(actor_data, _ACTOR_KEYS, "issued_by")
    try:
        claimant_data = _mapping(receipt_data["claimant"], "claimant")
        _exact_keys(claimant_data, _ACTOR_KEYS, "claimant")
        claimant = AccountOwnerAssignmentActor(
            actor_id=_string(claimant_data["actor_id"]),
            user_id=_integer(claimant_data["user_id"]),
            role=_string(claimant_data["role"]),
            kind=_string(claimant_data["kind"]),
            is_staff=_boolean(claimant_data["is_staff"]),
        )
        receipt = AccountOwnerAssignmentProvenanceReceipt(
            receipt_id=_string(receipt_data["receipt_id"]),
            receipt_version=_string(receipt_data["receipt_version"]),
            provenance_kind=_string(receipt_data["provenance_kind"]),
            artifact_type=_string(receipt_data["artifact_type"]),
            assignment_state=_string(receipt_data["assignment_state"]),
            assigned_owner_user_id=_optional_integer(receipt_data["assigned_owner_user_id"]),
            account_namespace=_string(receipt_data["account_namespace"]),
            account_id=_string(receipt_data["account_id"]),
            underlying_unified_account_namespace=_string(
                receipt_data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(receipt_data["underlying_unified_account_id"]),
            row_observation_owner=_string(receipt_data["row_observation_owner"]),
            row_observation_artifact_type=_string(receipt_data["row_observation_artifact_type"]),
            row_observation_id=_string(receipt_data["row_observation_id"]),
            row_observation_version=_string(receipt_data["row_observation_version"]),
            row_observation_identity_hash=_string(receipt_data["row_observation_identity_hash"]),
            row_observation_content_hash=_string(receipt_data["row_observation_content_hash"]),
            row_observation_valid_until=_datetime(receipt_data["row_observation_valid_until"]),
            claimant=claimant,
            issued_at=_datetime(receipt_data["issued_at"]),
            recorded_at=_datetime(receipt_data["recorded_at"]),
            valid_until=_datetime(receipt_data["valid_until"]),
            supersedes_content_hash=_optional_string(receipt_data["supersedes_content_hash"]),
            identity_hash=_string(receipt_data["identity_hash"]),
            content_hash=_string(receipt_data["content_hash"]),
            owner=_string(receipt_data["owner"]),
            schema=_string(receipt_data["schema"]),
            permission=_string(receipt_data["permission"]),
            status=_string(receipt_data["status"]),
            blocker_codes=_string_tuple(receipt_data["blocker_codes"]),
        )
        issued_by = AccountOwnerAssignmentServerActor(
            actor_id=_string(actor_data["actor_id"]),
            user_id=_integer(actor_data["user_id"]),
            role=_string(actor_data["role"]),
            kind=_string(actor_data["kind"]),
            is_staff=_boolean(actor_data["is_staff"]),
        )
        record = PersistedAccountOwnerAssignmentProvenanceReceipt(receipt, issued_by)
    except (KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError(
            "account provenance receipt payload is invalid"
        ) from error
    if encode_account_owner_assignment_provenance_receipt_record(record) != payload:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError(
            "account provenance receipt payload is non-canonical"
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
    "row_observation_id",
    "row_observation_version",
    "row_observation_identity_hash",
    "row_observation_content_hash",
    "row_observation_valid_until",
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


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError(
            f"{field_name} must be an exact mapping"
        )
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError(
            f"{field_name} has an invalid shape"
        )


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentProvenanceReceiptCodecError(
            "datetime must use canonical UTC Z form"
        )
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError("datetime is non-canonical")
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountOwnerAssignmentProvenanceReceiptCodecError(
            "blocker_codes must be an exact list"
        )
    return tuple(_string(item) for item in cast(list[object], value))


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptCodecError",
    "decode_account_owner_assignment_provenance_receipt_record",
    "encode_account_owner_assignment_provenance_receipt_record",
]
