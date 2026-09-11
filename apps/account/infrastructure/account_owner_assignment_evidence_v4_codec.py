"""Strict canonical codecs for Account owner-assignment evidence v4."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
    AccountOwnerAssignmentSubjectV4,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_codec import (
    AccountOwnerAssignmentProvenanceReceiptV4CodecError,
    decode_account_owner_assignment_provenance_receipt_v4,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    CanonicalAccountCreationBindingV2CodecError,
    decode_canonical_account_creation_binding_v2,
)


class AccountOwnerAssignmentEvidenceV4CodecError(ValueError):
    """A stored v4 subject or evidence value is malformed or non-canonical."""


_SUBJECT_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "subject_id",
    "subject_version",
    "receipt",
    "binding",
    "physical_root",
    "receipt_identity_hash",
    "receipt_content_hash",
    "policy_identity_hash",
    "policy_content_hash",
    "binding_identity_hash",
    "binding_content_hash",
    "allocation_identity_hash",
    "allocation_content_hash",
    "creation_root_identity_hash",
    "creation_root_content_hash",
    "account_claim_hash",
    "underlying_claim_hash",
    "physical_observation_content_hash",
    "physical_source_content_hash",
    "physical_raw_observation_content_hash",
    "requested_at",
    "valid_until",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
    "activation_available",
    "must_not_execute",
}
_EVIDENCE_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "evidence_id",
    "evidence_version",
    "subject",
    "policy_identity_hash",
    "policy_content_hash",
    "assignment_state",
    "assigned_owner_user_id",
    "approved_by",
    "approved_at",
    "recorded_at",
    "approval_valid_until",
    "valid_until",
    "account_claim_hash",
    "underlying_claim_hash",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
    "activation_available",
    "must_not_execute",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def encode_account_owner_assignment_subject_v4(
    value: AccountOwnerAssignmentSubjectV4,
) -> dict[str, object]:
    """Encode one complete Subject v4 without compressing its source graph."""

    if type(value) is not AccountOwnerAssignmentSubjectV4:
        raise AccountOwnerAssignmentEvidenceV4CodecError(
            "expected exact AccountOwnerAssignmentSubjectV4"
        )
    try:
        value.__post_init__()
        _seal(value.identity_hash)
        _seal(value.content_hash)
        return value.to_payload()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV4CodecError("subject v4 cannot be encoded") from error


def encode_account_owner_assignment_evidence_v4(
    value: AccountOwnerAssignmentEvidenceV4,
) -> dict[str, object]:
    """Encode one complete Evidence v4 without dropping the nested Subject."""

    if type(value) is not AccountOwnerAssignmentEvidenceV4:
        raise AccountOwnerAssignmentEvidenceV4CodecError(
            "expected exact AccountOwnerAssignmentEvidenceV4"
        )
    try:
        value.__post_init__()
        _seal(value.identity_hash)
        _seal(value.content_hash)
        return value.to_payload()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV4CodecError("evidence v4 cannot be encoded") from error


def decode_account_owner_assignment_subject_v4(
    payload: object,
) -> AccountOwnerAssignmentSubjectV4:
    """Decode one exact Subject v4 payload and require canonical roundtrip."""

    data = _mapping(payload, "subject")
    _keys(data, _SUBJECT_KEYS, "subject")
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    try:
        receipt = decode_account_owner_assignment_provenance_receipt_v4(data["receipt"])
        binding = decode_canonical_account_creation_binding_v2(data["binding"])
        physical_payload = _mapping(data["physical_root"], "physical_root")
        if physical_payload != binding.creation_root.to_payload():
            raise AccountOwnerAssignmentEvidenceV4CodecError(
                "physical_root does not equal the strict Binding-v2 creation root"
            )
        subject = AccountOwnerAssignmentSubjectV4(
            subject_id=_text(data["subject_id"]),
            subject_version=_text(data["subject_version"]),
            receipt=receipt,
            binding=binding,
            physical_root=binding.creation_root,
            receipt_identity_hash=_seal(data["receipt_identity_hash"]),
            receipt_content_hash=_seal(data["receipt_content_hash"]),
            policy_identity_hash=_seal(data["policy_identity_hash"]),
            policy_content_hash=_seal(data["policy_content_hash"]),
            binding_identity_hash=_seal(data["binding_identity_hash"]),
            binding_content_hash=_seal(data["binding_content_hash"]),
            allocation_identity_hash=_seal(data["allocation_identity_hash"]),
            allocation_content_hash=_seal(data["allocation_content_hash"]),
            creation_root_identity_hash=_seal(data["creation_root_identity_hash"]),
            creation_root_content_hash=_seal(data["creation_root_content_hash"]),
            account_claim_hash=_seal(data["account_claim_hash"]),
            underlying_claim_hash=_seal(data["underlying_claim_hash"]),
            physical_observation_content_hash=_seal(data["physical_observation_content_hash"]),
            physical_source_content_hash=_seal(data["physical_source_content_hash"]),
            physical_raw_observation_content_hash=_seal(
                data["physical_raw_observation_content_hash"]
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
    except (
        AccountOwnerAssignmentEvidenceV4CodecError,
        AccountOwnerAssignmentProvenanceReceiptV4CodecError,
        CanonicalAccountCreationBindingV2CodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AccountOwnerAssignmentEvidenceV4CodecError):
            raise
        raise AccountOwnerAssignmentEvidenceV4CodecError("subject-v4 payload is invalid") from error
    if encode_account_owner_assignment_subject_v4(subject) != payload:
        raise AccountOwnerAssignmentEvidenceV4CodecError("subject-v4 payload is non-canonical")
    return subject


def decode_account_owner_assignment_evidence_v4(
    payload: object,
) -> AccountOwnerAssignmentEvidenceV4:
    """Decode one exact Evidence v4 payload and require canonical roundtrip."""

    data = _mapping(payload, "evidence")
    _keys(data, _EVIDENCE_KEYS, "evidence")
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    try:
        subject = decode_account_owner_assignment_subject_v4(data["subject"])
        evidence = AccountOwnerAssignmentEvidenceV4(
            evidence_id=_text(data["evidence_id"]),
            evidence_version=_text(data["evidence_version"]),
            subject=subject,
            policy_identity_hash=_seal(data["policy_identity_hash"]),
            policy_content_hash=_seal(data["policy_content_hash"]),
            assigned_owner_user_id=_integer(data["assigned_owner_user_id"]),
            approved_by=_actor(data["approved_by"], "approved_by"),
            approved_at=_clock(data["approved_at"]),
            recorded_at=_clock(data["recorded_at"]),
            approval_valid_until=_clock(data["approval_valid_until"]),
            valid_until=_clock(data["valid_until"]),
            account_claim_hash=_seal(data["account_claim_hash"]),
            underlying_claim_hash=_seal(data["underlying_claim_hash"]),
            identity_hash=_seal(data["identity_hash"]),
            content_hash=_seal(data["content_hash"]),
            owner=_text(data["owner"]),
            artifact_type=_text(data["artifact_type"]),
            schema=_text(data["schema"]),
            assignment_state=_text(data["assignment_state"]),
            permission=_text(data["permission"]),
            status=_text(data["status"]),
            blocker_codes=_blockers(data["blocker_codes"]),
        )
    except (
        AccountOwnerAssignmentEvidenceV4CodecError,
        AccountOwnerAssignmentProvenanceReceiptV4CodecError,
        CanonicalAccountCreationBindingV2CodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AccountOwnerAssignmentEvidenceV4CodecError):
            raise
        raise AccountOwnerAssignmentEvidenceV4CodecError(
            "evidence-v4 payload is invalid"
        ) from error
    if encode_account_owner_assignment_evidence_v4(evidence) != payload:
        raise AccountOwnerAssignmentEvidenceV4CodecError("evidence-v4 payload is non-canonical")
    return evidence


def _mapping(value: object, name: str) -> dict[str, object]:
    """Require an exact string-keyed mapping container."""

    if type(value) is not dict:
        raise AccountOwnerAssignmentEvidenceV4CodecError(f"{name} must be an exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data):
        raise AccountOwnerAssignmentEvidenceV4CodecError(f"{name} keys must be exact strings")
    return data


def _keys(value: dict[str, object], expected: set[str], name: str) -> None:
    """Require the closed-world key set for one payload level."""

    if set(value) != expected:
        raise AccountOwnerAssignmentEvidenceV4CodecError(f"{name} has an invalid canonical shape")


def _text(value: object) -> str:
    """Require one exact string value."""

    if type(value) is not str:
        raise AccountOwnerAssignmentEvidenceV4CodecError("expected exact string")
    return value


def _integer(value: object) -> int:
    """Require one exact integer value and reject bool."""

    if type(value) is not int:
        raise AccountOwnerAssignmentEvidenceV4CodecError("expected exact integer")
    return value


def _boolean(value: object) -> bool:
    """Require one exact boolean value."""

    if type(value) is not bool:
        raise AccountOwnerAssignmentEvidenceV4CodecError("expected exact bool")
    return value


def _fixed_boolean(value: object, expected: bool, name: str) -> None:
    """Require one execution flag to retain its fixed value."""

    if _boolean(value) is not expected:
        raise AccountOwnerAssignmentEvidenceV4CodecError(f"{name} is fixed")


def _seal(value: object) -> str:
    """Require one complete lowercase SHA-256 seal, including non-blankness."""

    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AccountOwnerAssignmentEvidenceV4CodecError(
            "stored v4 value requires full lowercase seal"
        )
    return text


def _clock(value: object) -> datetime:
    """Require canonical UTC ``Z`` text with explicit microseconds."""

    text = _text(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentEvidenceV4CodecError("clock requires canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentEvidenceV4CodecError("clock is invalid") from error
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != text:
        raise AccountOwnerAssignmentEvidenceV4CodecError("clock is non-canonical")
    return parsed


def _blockers(value: object) -> tuple[str, ...]:
    """Decode the canonical JSON list used for blocker codes."""

    if type(value) is not list:
        raise AccountOwnerAssignmentEvidenceV4CodecError("blocker_codes requires exact list")
    return tuple(_text(item) for item in cast(list[object], value))


def _actor(value: object, name: str) -> AccountOwnerAssignmentActor:
    """Decode and Domain-validate one exact actor mapping."""

    data = _mapping(value, name)
    _keys(data, _ACTOR_KEYS, name)
    return AccountOwnerAssignmentActor(
        actor_id=_text(data["actor_id"]),
        user_id=_integer(data["user_id"]),
        role=_text(data["role"]),
        kind=_text(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )


__all__ = [
    "AccountOwnerAssignmentEvidenceV4CodecError",
    "decode_account_owner_assignment_evidence_v4",
    "decode_account_owner_assignment_subject_v4",
    "encode_account_owner_assignment_evidence_v4",
    "encode_account_owner_assignment_subject_v4",
]
