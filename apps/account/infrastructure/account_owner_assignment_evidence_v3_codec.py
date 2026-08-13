"""Strict canonical codec for complete Account owner-assignment evidence v3."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
    AccountOwnerAssignmentSubjectV3,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_codec import (
    AccountOwnerAssignmentProvenanceReceiptV3CodecError,
    decode_account_owner_assignment_provenance_receipt_v3_record,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    CanonicalAccountCreationBindingV2CodecError,
    decode_canonical_account_creation_binding_v2,
)


class AccountOwnerAssignmentEvidenceV3CodecError(ValueError):
    """An evidence-v3 payload is malformed, substituted, or non-canonical."""


def encode_account_owner_assignment_subject_v3(
    value: AccountOwnerAssignmentSubjectV3,
) -> dict[str, object]:
    """Encode one complete pending subject without compressing its upstream evidence."""

    if type(value) is not AccountOwnerAssignmentSubjectV3:
        raise TypeError("value must be an exact AccountOwnerAssignmentSubjectV3")
    value.__post_init__()
    return cast(dict[str, object], value.to_payload())


def encode_account_owner_assignment_evidence_v3(
    value: AccountOwnerAssignmentEvidenceV3,
) -> dict[str, object]:
    """Encode one complete evidence root without compressing nested evidence."""

    if type(value) is not AccountOwnerAssignmentEvidenceV3:
        raise TypeError("value must be an exact AccountOwnerAssignmentEvidenceV3")
    value.__post_init__()
    return cast(dict[str, object], value.to_payload())


def decode_account_owner_assignment_evidence_v3(
    payload: object,
) -> AccountOwnerAssignmentEvidenceV3:
    """Restore every nested value, revalidate Domain, and require canonical roundtrip."""

    data = _mapping(payload, "evidence")
    _keys(data, _EVIDENCE_KEYS, "evidence")
    try:
        subject = decode_account_owner_assignment_subject_v3(data["subject"])
        approved_by = _actor(data["approved_by"], "approved_by")
        _fixed_boolean(data["activation_available"], False, "activation_available")
        _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
        value = AccountOwnerAssignmentEvidenceV3(
            evidence_id=_string(data["evidence_id"]),
            evidence_version=_string(data["evidence_version"]),
            subject=subject,
            assigned_owner_user_id=_integer(data["assigned_owner_user_id"]),
            approved_by=approved_by,
            approved_at=_datetime(data["approved_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            approval_valid_until=_datetime(data["approval_valid_until"]),
            valid_until=_datetime(data["valid_until"]),
            account_claim_hash=_string(data["account_claim_hash"]),
            underlying_claim_hash=_string(data["underlying_claim_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            assignment_state=_string(data["assignment_state"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
        )
    except (
        AccountOwnerAssignmentEvidenceV3CodecError,
        AccountOwnerAssignmentProvenanceReceiptV3CodecError,
        CanonicalAccountCreationBindingV2CodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AccountOwnerAssignmentEvidenceV3CodecError):
            raise
        raise AccountOwnerAssignmentEvidenceV3CodecError(
            "evidence-v3 payload is invalid"
        ) from error
    if encode_account_owner_assignment_evidence_v3(value) != payload:
        raise AccountOwnerAssignmentEvidenceV3CodecError("evidence-v3 payload is non-canonical")
    return value


def decode_account_owner_assignment_subject_v3(
    payload: object,
) -> AccountOwnerAssignmentSubjectV3:
    """Restore and canonically revalidate one complete pending subject."""

    data = _mapping(payload, "subject")
    _keys(data, _SUBJECT_KEYS, "subject")
    receipt_payload = _mapping(data["receipt"], "receipt")
    claimant_payload = _mapping(receipt_payload.get("claimant"), "receipt claimant")
    claimant = _actor(claimant_payload, "receipt claimant")
    issuer = claimant.to_payload()
    receipt = decode_account_owner_assignment_provenance_receipt_v3_record(
        {"receipt": receipt_payload, "issued_by": issuer}
    ).receipt
    binding = decode_canonical_account_creation_binding_v2(data["binding"])
    physical_payload = _mapping(data["physical_root"], "physical_root")
    if physical_payload != binding.creation_root.to_payload():
        raise AccountOwnerAssignmentEvidenceV3CodecError(
            "physical_root does not equal the strict Binding-v2 creation root"
        )
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    try:
        subject = AccountOwnerAssignmentSubjectV3(
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            receipt=receipt,
            binding=binding,
            physical_root=binding.creation_root,
            receipt_identity_hash=_string(data["receipt_identity_hash"]),
            receipt_content_hash=_string(data["receipt_content_hash"]),
            binding_identity_hash=_string(data["binding_identity_hash"]),
            binding_content_hash=_string(data["binding_content_hash"]),
            creation_root_identity_hash=_string(data["creation_root_identity_hash"]),
            creation_root_content_hash=_string(data["creation_root_content_hash"]),
            account_claim_hash=_string(data["account_claim_hash"]),
            underlying_claim_hash=_string(data["underlying_claim_hash"]),
            physical_observation_content_hash=_string(data["physical_observation_content_hash"]),
            physical_source_content_hash=_string(data["physical_source_content_hash"]),
            physical_raw_observation_content_hash=_string(
                data["physical_raw_observation_content_hash"]
            ),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV3CodecError("subject-v3 payload is invalid") from error
    if subject.to_payload() != payload:
        raise AccountOwnerAssignmentEvidenceV3CodecError("subject-v3 payload is non-canonical")
    if encode_account_owner_assignment_subject_v3(subject) != payload:
        raise AccountOwnerAssignmentEvidenceV3CodecError("subject-v3 payload is non-canonical")
    return subject


_EVIDENCE_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "evidence_id",
    "evidence_version",
    "subject",
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
    "binding_identity_hash",
    "binding_content_hash",
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
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentEvidenceV3CodecError(f"{name} must be an exact mapping")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise AccountOwnerAssignmentEvidenceV3CodecError(f"{name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentEvidenceV3CodecError("expected an exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentEvidenceV3CodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountOwnerAssignmentEvidenceV3CodecError("expected an exact boolean")
    return value


def _fixed_boolean(value: object, expected: bool, name: str) -> None:
    if _boolean(value) is not expected:
        raise AccountOwnerAssignmentEvidenceV3CodecError(f"{name} is fixed")


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentEvidenceV3CodecError("datetime must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentEvidenceV3CodecError("datetime is invalid") from error
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentEvidenceV3CodecError("datetime is non-canonical")
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountOwnerAssignmentEvidenceV3CodecError("expected an exact list")
    return tuple(_string(item) for item in cast(list[object], value))


def _actor(value: object, name: str) -> AccountOwnerAssignmentActor:
    data = _mapping(value, name)
    _keys(data, _ACTOR_KEYS, name)
    return AccountOwnerAssignmentActor(
        actor_id=_string(data["actor_id"]),
        user_id=_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )


__all__ = [
    "AccountOwnerAssignmentEvidenceV3CodecError",
    "decode_account_owner_assignment_evidence_v3",
    "decode_account_owner_assignment_subject_v3",
    "encode_account_owner_assignment_evidence_v3",
    "encode_account_owner_assignment_subject_v3",
]
