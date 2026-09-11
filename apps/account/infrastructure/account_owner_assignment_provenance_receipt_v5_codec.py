"""Strict JSON codec for inactive Account owner provenance receipt v5."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    decode_canonical_account_creation_binding_v2,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_codec import (
    decode_canonical_account_ownership_reobservation_v1,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_codec import (
    decode_single_owner_authority_policy_v1,
)


class AccountOwnerAssignmentProvenanceReceiptV5CodecError(ValueError):
    """A persisted ReceiptV5 payload has an invalid shape or sealed graph."""


_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "receipt_id",
    "receipt_version",
    "policy",
    "policy_identity_hash",
    "policy_content_hash",
    "binding",
    "reobservation",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "allocation_identity_hash",
    "allocation_content_hash",
    "binding_identity_hash",
    "binding_content_hash",
    "account_claim_hash",
    "underlying_claim_hash",
    "reobservation_identity_hash",
    "reobservation_content_hash",
    "current_physical_observation_content_hash",
    "current_physical_source_content_hash",
    "current_physical_raw_observation_content_hash",
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


def _mapping(value: object) -> dict[str, object]:
    """Require the exact JSON object shape used by the receipt payload."""

    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt must be an exact mapping"
        )
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != _KEYS:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt payload has an invalid shape"
        )
    return data


def _text(value: object) -> str:
    """Require one exact string field."""

    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt field requires an exact string"
        )
    return value


def _integer(value: object) -> int:
    """Require one exact integer field, excluding booleans."""

    if type(value) is not int:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt field requires an exact integer"
        )
    return value


def _boolean(value: object) -> bool:
    """Require one exact boolean field."""

    if type(value) is not bool:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt field requires an exact boolean"
        )
    return value


def _seal(value: object) -> str:
    """Require one complete lowercase SHA-256 digest."""

    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt requires complete lowercase seals"
        )
    return text


def _clock(value: object) -> datetime:
    """Decode one canonical UTC microsecond timestamp."""

    text = _text(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt clock requires canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt clock is invalid"
        ) from error
    if parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt clock is not canonical UTC"
        )
    return parsed


def _claimant(value: object) -> AccountOwnerAssignmentActor:
    """Decode the exact claimant actor projection."""

    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "claimant must be an exact mapping"
        )
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != {
        "actor_id",
        "user_id",
        "role",
        "kind",
        "is_staff",
    }:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError("claimant has an invalid shape")
    return AccountOwnerAssignmentActor(
        actor_id=_text(data["actor_id"]),
        user_id=_integer(data["user_id"]),
        role=_text(data["role"]),
        kind=_text(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )


def _blockers(value: object) -> tuple[str, ...]:
    """Decode the JSON list that represents the immutable blocker tuple."""

    if type(value) is not list:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "blocker_codes requires an exact list"
        )
    return tuple(_text(item) for item in value)


def encode_account_owner_assignment_provenance_receipt_v5(
    receipt: AccountOwnerAssignmentProvenanceReceiptV5,
) -> dict[str, object]:
    """Encode the complete policy, Binding, re-observation, and claimant graph."""

    if type(receipt) is not AccountOwnerAssignmentProvenanceReceiptV5:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt must have its exact V5 Domain type"
        )
    try:
        _seal(receipt.identity_hash)
        _seal(receipt.content_hash)
        return receipt.to_payload()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt cannot be encoded"
        ) from error


def decode_account_owner_assignment_provenance_receipt_v5(
    payload: object,
) -> AccountOwnerAssignmentProvenanceReceiptV5:
    """Decode one exact V5 payload and verify its canonical round trip."""

    data = _mapping(payload)
    if data["activation_available"] is not False or data["must_not_execute"] is not True:
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "receipt execution flags are fixed"
        )
    try:
        predecessor = data["supersedes_content_hash"]
        receipt = AccountOwnerAssignmentProvenanceReceiptV5(
            receipt_id=_text(data["receipt_id"]),
            receipt_version=_text(data["receipt_version"]),
            policy=decode_single_owner_authority_policy_v1(data["policy"]),
            policy_identity_hash=_seal(data["policy_identity_hash"]),
            policy_content_hash=_seal(data["policy_content_hash"]),
            binding=decode_canonical_account_creation_binding_v2(data["binding"]),
            reobservation=decode_canonical_account_ownership_reobservation_v1(
                data["reobservation"]
            ),
            account_namespace=_text(data["account_namespace"]),
            account_id=_text(data["account_id"]),
            underlying_unified_account_namespace=_text(
                data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(data["underlying_unified_account_id"]),
            allocation_identity_hash=_seal(data["allocation_identity_hash"]),
            allocation_content_hash=_seal(data["allocation_content_hash"]),
            binding_identity_hash=_seal(data["binding_identity_hash"]),
            binding_content_hash=_seal(data["binding_content_hash"]),
            account_claim_hash=_seal(data["account_claim_hash"]),
            underlying_claim_hash=_seal(data["underlying_claim_hash"]),
            reobservation_identity_hash=_seal(data["reobservation_identity_hash"]),
            reobservation_content_hash=_seal(data["reobservation_content_hash"]),
            current_physical_observation_content_hash=_seal(
                data["current_physical_observation_content_hash"]
            ),
            current_physical_source_content_hash=_seal(
                data["current_physical_source_content_hash"]
            ),
            current_physical_raw_observation_content_hash=_seal(
                data["current_physical_raw_observation_content_hash"]
            ),
            assigned_owner_user_id=_integer(data["assigned_owner_user_id"]),
            claimant=_claimant(data["claimant"]),
            issued_at=_clock(data["issued_at"]),
            recorded_at=_clock(data["recorded_at"]),
            valid_until=_clock(data["valid_until"]),
            supersedes_content_hash=None if predecessor is None else _seal(predecessor),
            identity_hash=_seal(data["identity_hash"]),
            content_hash=_seal(data["content_hash"]),
            owner=_text(data["owner"]),
            artifact_type=_text(data["artifact_type"]),
            schema=_text(data["schema"]),
            provenance_kind=_text(data["provenance_kind"]),
            assignment_state=_text(data["assignment_state"]),
            permission=_text(data["permission"]),
            status=_text(data["status"]),
            blocker_codes=_blockers(data["blocker_codes"]),
        )
        if encode_account_owner_assignment_provenance_receipt_v5(receipt) != data:
            raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
                "receipt payload is not canonical"
            )
        return receipt
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, AccountOwnerAssignmentProvenanceReceiptV5CodecError):
            raise
        raise AccountOwnerAssignmentProvenanceReceiptV5CodecError(
            "invalid sealed V5 receipt"
        ) from error


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV5CodecError",
    "decode_account_owner_assignment_provenance_receipt_v5",
    "encode_account_owner_assignment_provenance_receipt_v5",
]
