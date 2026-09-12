"""Strict JSON codec for inactive Account owner-assignment Subject v5."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from apps.account.domain.validation_graph import validation_graph_operation
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_codec import (
    decode_account_owner_assignment_provenance_receipt_v5,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    decode_canonical_account_creation_binding_v2,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_codec import (
    decode_canonical_account_ownership_reobservation_v1,
)


class AccountOwnerAssignmentSubjectV5CodecError(ValueError):
    """A persisted SubjectV5 payload has an invalid shape or sealed graph."""


_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "subject_id",
    "subject_version",
    "receipt",
    "binding",
    "reobservation",
    "receipt_identity_hash",
    "receipt_content_hash",
    "policy_identity_hash",
    "policy_content_hash",
    "binding_identity_hash",
    "binding_content_hash",
    "allocation_identity_hash",
    "allocation_content_hash",
    "account_claim_hash",
    "underlying_claim_hash",
    "reobservation_identity_hash",
    "reobservation_content_hash",
    "current_physical_observation_content_hash",
    "current_physical_source_content_hash",
    "current_physical_raw_observation_content_hash",
    "requested_at",
    "valid_until",
    "identity_hash",
    "content_hash",
    "permission",
    "status",
    "blocker_codes",
    "activation_available",
    "must_not_execute",
}


def _mapping(value: object) -> dict[str, object]:
    """Require the exact JSON object shape used by SubjectV5."""

    if type(value) is not dict:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject must be an exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != _KEYS:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject payload has an invalid shape")
    return data


def _text(value: object) -> str:
    """Require one exact string payload field."""

    if type(value) is not str:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject field requires an exact string")
    return value


def _integer(value: object) -> int:
    """Require one exact integer payload field."""

    if type(value) is not int:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject field requires an exact integer")
    return value


def _boolean(value: object) -> bool:
    """Require one exact boolean payload field."""

    if type(value) is not bool:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject field requires an exact boolean")
    return value


def _seal(value: object) -> str:
    """Require one complete lowercase SHA-256 digest."""

    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AccountOwnerAssignmentSubjectV5CodecError("subject requires complete lowercase seals")
    return text


def _clock(value: object) -> datetime:
    """Decode one canonical UTC timestamp with microsecond precision."""

    text = _text(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentSubjectV5CodecError(
            "subject clock requires canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject clock is invalid") from error
    if parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject clock is not canonical UTC")
    return parsed


def _blockers(value: object) -> tuple[str, ...]:
    """Decode the JSON list representing the fixed blocker tuple."""

    if type(value) is not list:
        raise AccountOwnerAssignmentSubjectV5CodecError("blocker_codes requires an exact list")
    return tuple(_text(item) for item in value)


@validation_graph_operation
def encode_account_owner_assignment_subject_v5(
    subject: AccountOwnerAssignmentSubjectV5,
) -> dict[str, object]:
    """Encode the complete ReceiptV5, BindingV2, and ReobservationV1 graph."""

    if type(subject) is not AccountOwnerAssignmentSubjectV5:
        raise AccountOwnerAssignmentSubjectV5CodecError(
            "subject must have its exact V5 Domain type"
        )
    try:
        _seal(subject.identity_hash)
        _seal(subject.content_hash)
        return subject.to_payload()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject cannot be encoded") from error


@validation_graph_operation
def decode_account_owner_assignment_subject_v5(
    payload: object,
) -> AccountOwnerAssignmentSubjectV5:
    """Decode one exact SubjectV5 payload and verify canonical round-trip."""

    data = _mapping(payload)
    if data["activation_available"] is not False or data["must_not_execute"] is not True:
        raise AccountOwnerAssignmentSubjectV5CodecError("subject execution flags are fixed")
    try:
        subject = AccountOwnerAssignmentSubjectV5(
            subject_id=_text(data["subject_id"]),
            subject_version=_text(data["subject_version"]),
            receipt=decode_account_owner_assignment_provenance_receipt_v5(data["receipt"]),
            binding=decode_canonical_account_creation_binding_v2(data["binding"]),
            reobservation=decode_canonical_account_ownership_reobservation_v1(
                data["reobservation"]
            ),
            receipt_identity_hash=_seal(data["receipt_identity_hash"]),
            receipt_content_hash=_seal(data["receipt_content_hash"]),
            policy_identity_hash=_seal(data["policy_identity_hash"]),
            policy_content_hash=_seal(data["policy_content_hash"]),
            binding_identity_hash=_seal(data["binding_identity_hash"]),
            binding_content_hash=_seal(data["binding_content_hash"]),
            allocation_identity_hash=_seal(data["allocation_identity_hash"]),
            allocation_content_hash=_seal(data["allocation_content_hash"]),
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
            requested_at=_clock(data["requested_at"]),
            valid_until=_clock(data["valid_until"]),
            identity_hash=_seal(data["identity_hash"]),
            content_hash=_seal(data["content_hash"]),
            owner=_text(data["owner"]),
            artifact_type=_text(data["artifact_type"]),
            schema=_text(data["schema"]),
            permission=_text(data["permission"]),
            status=_text(data["status"]),
            blocker_codes=_blockers(data["blocker_codes"]),
        )
        if encode_account_owner_assignment_subject_v5(subject) != data:
            raise AccountOwnerAssignmentSubjectV5CodecError("subject payload is not canonical")
        return subject
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, AccountOwnerAssignmentSubjectV5CodecError):
            raise
        raise AccountOwnerAssignmentSubjectV5CodecError("invalid sealed V5 subject") from error


__all__ = [
    "AccountOwnerAssignmentSubjectV5CodecError",
    "decode_account_owner_assignment_subject_v5",
    "encode_account_owner_assignment_subject_v5",
]
