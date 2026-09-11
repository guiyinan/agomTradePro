"""Strict storage codec for policy-bound Account creation receipts v4."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    decode_canonical_account_creation_binding_v2,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_codec import (
    decode_single_owner_authority_policy_v1,
)


class AccountOwnerAssignmentProvenanceReceiptV4CodecError(ValueError):
    """A stored v4 receipt violates its exact canonical shape or sealed graph."""


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


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("expected exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != keys:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("invalid canonical shape")
    return data


def _text(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("expected exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("expected exact integer")
    return value


def _seal(value: object) -> str:
    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError(
            "stored receipt requires full seal"
        )
    return text


def _clock(value: object) -> datetime:
    text = _text(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("clock requires UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("noncanonical receipt clock")
    return parsed


def _claimant(value: object) -> AccountOwnerAssignmentActor:
    data = _mapping(value, {"actor_id", "user_id", "role", "kind", "is_staff"})
    staff = data["is_staff"]
    if type(staff) is not bool:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("staff fact requires exact bool")
    return AccountOwnerAssignmentActor(
        actor_id=_text(data["actor_id"]),
        user_id=_integer(data["user_id"]),
        role=_text(data["role"]),
        kind=_text(data["kind"]),
        is_staff=staff,
    )


def _blockers(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError(
            "blocker_codes requires exact list"
        )
    return tuple(_text(item) for item in value)


def encode_account_owner_assignment_provenance_receipt_v4(
    receipt: AccountOwnerAssignmentProvenanceReceiptV4,
) -> dict[str, object]:
    """Encode the complete policy, canonical creation graph and original staff fact."""

    if type(receipt) is not AccountOwnerAssignmentProvenanceReceiptV4:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("expected exact v4 receipt")
    try:
        _seal(receipt.identity_hash)
        _seal(receipt.content_hash)
        return receipt.to_payload()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError(
            "receipt cannot be encoded"
        ) from error


def decode_account_owner_assignment_provenance_receipt_v4(
    payload: object,
) -> AccountOwnerAssignmentProvenanceReceiptV4:
    """Decode only an exact v4 payload with independently validated nested seals."""

    data = _mapping(payload, _KEYS)
    if data["activation_available"] is not False or data["must_not_execute"] is not True:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError("execution flags are fixed")
    try:
        predecessor = data["supersedes_content_hash"]
        receipt = AccountOwnerAssignmentProvenanceReceiptV4(
            receipt_id=_text(data["receipt_id"]),
            receipt_version=_text(data["receipt_version"]),
            policy=decode_single_owner_authority_policy_v1(data["policy"]),
            policy_identity_hash=_seal(data["policy_identity_hash"]),
            policy_content_hash=_seal(data["policy_content_hash"]),
            binding=decode_canonical_account_creation_binding_v2(data["binding"]),
            account_namespace=_text(data["account_namespace"]),
            account_id=_text(data["account_id"]),
            underlying_unified_account_namespace=_text(
                data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(data["underlying_unified_account_id"]),
            allocation_identity_hash=_seal(data["allocation_identity_hash"]),
            allocation_content_hash=_seal(data["allocation_content_hash"]),
            creation_root_identity_hash=_seal(data["creation_root_identity_hash"]),
            creation_root_content_hash=_seal(data["creation_root_content_hash"]),
            binding_identity_hash=_seal(data["binding_identity_hash"]),
            binding_content_hash=_seal(data["binding_content_hash"]),
            account_claim_hash=_seal(data["account_claim_hash"]),
            underlying_claim_hash=_seal(data["underlying_claim_hash"]),
            physical_observation_content_hash=_seal(data["physical_observation_content_hash"]),
            physical_source_content_hash=_seal(data["physical_source_content_hash"]),
            physical_raw_observation_content_hash=_seal(
                data["physical_raw_observation_content_hash"]
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
        if receipt.to_payload() != data:
            raise AccountOwnerAssignmentProvenanceReceiptV4CodecError(
                "noncanonical receipt payload"
            )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV4CodecError(
            "invalid sealed v4 receipt"
        ) from error
    return receipt
