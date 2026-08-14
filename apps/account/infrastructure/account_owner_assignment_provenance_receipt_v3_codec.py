"""Strict canonical codec for Account creation-claim provenance receipts v3."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    CanonicalAccountCreationBindingV2CodecError,
    decode_canonical_account_creation_binding_v2,
)


class AccountOwnerAssignmentProvenanceReceiptV3CodecError(ValueError):
    """A stored receipt-v3 record is malformed or non-canonical."""


def encode_account_owner_assignment_provenance_receipt_v3_record(
    value: PersistedAccountOwnerAssignmentProvenanceReceiptV3,
) -> dict[str, object]:
    """Encode the complete nested Binding-v2 receipt and authenticated issuer."""

    if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV3:
        raise TypeError("value must be an exact persisted receipt-v3 record")
    value.__post_init__()
    return {"receipt": value.receipt.to_payload(), "issued_by": value.issued_by.to_payload()}


def decode_account_owner_assignment_provenance_receipt_v3_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3:
    """Decode exact shapes/types, revalidate Domain, and require byte-shape roundtrip."""

    envelope = _mapping(payload, "record")
    _keys(envelope, {"receipt", "issued_by"}, "record")
    data = _mapping(envelope["receipt"], "receipt")
    issuer_data = _mapping(envelope["issued_by"], "issued_by")
    _keys(data, _RECEIPT_KEYS, "receipt")
    _keys(issuer_data, _ACTOR_KEYS, "issued_by")
    try:
        claimant_data = _mapping(data["claimant"], "claimant")
        _keys(claimant_data, _ACTOR_KEYS, "claimant")
        claimant = AccountOwnerAssignmentActor(
            actor_id=_string(claimant_data["actor_id"]),
            user_id=_integer(claimant_data["user_id"]),
            role=_string(claimant_data["role"]),
            kind=_string(claimant_data["kind"]),
            is_staff=_boolean(claimant_data["is_staff"]),
        )
        _fixed_boolean(data["activation_available"], False, "activation_available")
        _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
        receipt = AccountOwnerAssignmentProvenanceReceiptV3(
            receipt_id=_string(data["receipt_id"]),
            receipt_version=_string(data["receipt_version"]),
            binding=decode_canonical_account_creation_binding_v2(data["binding"]),
            account_namespace=_string(data["account_namespace"]),
            account_id=_string(data["account_id"]),
            underlying_unified_account_namespace=_string(
                data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(data["underlying_unified_account_id"]),
            allocation_identity_hash=_string(data["allocation_identity_hash"]),
            allocation_content_hash=_string(data["allocation_content_hash"]),
            creation_root_identity_hash=_string(data["creation_root_identity_hash"]),
            creation_root_content_hash=_string(data["creation_root_content_hash"]),
            binding_identity_hash=_string(data["binding_identity_hash"]),
            binding_content_hash=_string(data["binding_content_hash"]),
            account_claim_hash=_string(data["account_claim_hash"]),
            underlying_claim_hash=_string(data["underlying_claim_hash"]),
            physical_observation_content_hash=_string(data["physical_observation_content_hash"]),
            physical_source_content_hash=_string(data["physical_source_content_hash"]),
            physical_raw_observation_content_hash=_string(
                data["physical_raw_observation_content_hash"]
            ),
            assigned_owner_user_id=_integer(data["assigned_owner_user_id"]),
            claimant=claimant,
            issued_at=_datetime(data["issued_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            provenance_kind=_string(data["provenance_kind"]),
            assignment_state=_string(data["assignment_state"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
        )
        issuer = AccountOwnerAssignmentServerActor(
            actor_id=_string(issuer_data["actor_id"]),
            user_id=_integer(issuer_data["user_id"]),
            role=_string(issuer_data["role"]),
            kind=_string(issuer_data["kind"]),
            is_staff=_boolean(issuer_data["is_staff"]),
        )
        record = PersistedAccountOwnerAssignmentProvenanceReceiptV3(receipt, issuer)
    except (
        AccountOwnerAssignmentProvenanceReceiptV3CodecError,
        CanonicalAccountCreationBindingV2CodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AccountOwnerAssignmentProvenanceReceiptV3CodecError):
            raise
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError(
            "receipt-v3 record is invalid"
        ) from error
    if encode_account_owner_assignment_provenance_receipt_v3_record(record) != payload:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError(
            "receipt-v3 record is non-canonical"
        )
    return record


_RECEIPT_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "receipt_id",
    "receipt_version",
    "binding",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "allocation_identity_hash",
    "allocation_content_hash",
    "creation_root_identity_hash",
    "creation_root_content_hash",
    "binding_identity_hash",
    "binding_content_hash",
    "account_claim_hash",
    "underlying_claim_hash",
    "physical_observation_content_hash",
    "physical_source_content_hash",
    "physical_raw_observation_content_hash",
    "assigned_owner_user_id",
    "claimant",
    "issued_at",
    "recorded_at",
    "valid_until",
    "supersedes_content_hash",
    "provenance_kind",
    "assignment_state",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
    "activation_available",
    "must_not_execute",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError(
            f"{field_name} must be an exact mapping"
        )
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError(
            f"{field_name} has an invalid shape"
        )


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError("expected exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError("expected exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError("expected exact boolean")
    return value


def _fixed_boolean(value: object, expected: bool, field_name: str) -> None:
    if _boolean(value) is not expected:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError(f"{field_name} is fixed")


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError(
            "datetime must use canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError("datetime is invalid") from error
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError("datetime is non-canonical")
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountOwnerAssignmentProvenanceReceiptV3CodecError("expected exact list")
    return tuple(_string(item) for item in cast(list[object], value))


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV3CodecError",
    "decode_account_owner_assignment_provenance_receipt_v3_record",
    "encode_account_owner_assignment_provenance_receipt_v3_record",
]
