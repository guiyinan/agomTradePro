"""Strict nested codec for Account owner-assignment evidence v2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v2 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
    AccountOwnerAssignmentSubjectV2,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v2_codec import (
    decode_account_owner_assignment_provenance_receipt_v2_record,
    encode_account_owner_assignment_provenance_receipt_v2_record,
)
from apps.account.infrastructure.physical_account_row_observation_v2_codec import (
    decode_physical_account_row_observation_v2_record,
    encode_physical_account_row_observation_v2_record,
)


class AccountOwnerAssignmentEvidenceV2CodecError(ValueError):
    """Stored owner-assignment v2 bytes are malformed or non-canonical."""


def encode_account_owner_assignment_subject_v2(
    value: AccountOwnerAssignmentSubjectV2,
) -> dict[str, object]:
    """Encode a subject with both complete canonical upstream objects."""

    AccountOwnerAssignmentSubjectV2.__post_init__(value)
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "physical": _encode_physical(value),
        "receipt": _encode_receipt(value),
        "requested_at": _time(value.requested_at),
        "valid_until": _time(value.valid_until),
        "permission": value.permission,
        "status": value.status,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
    }


def decode_account_owner_assignment_subject_v2(
    payload: object,
) -> AccountOwnerAssignmentSubjectV2:
    """Decode and canonical-roundtrip-check one complete subject."""

    data = _mapping(payload)
    _keys(data, _SUBJECT_KEYS)
    try:
        physical = _decode_physical(data["physical"])
        receipt = _decode_receipt(data["receipt"])
        subject = AccountOwnerAssignmentSubjectV2(
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            physical=physical,
            receipt=receipt,
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV2CodecError(
            "invalid owner-assignment v2 subject"
        ) from error
    if encode_account_owner_assignment_subject_v2(subject) != payload:
        raise AccountOwnerAssignmentEvidenceV2CodecError(
            "non-canonical owner-assignment v2 subject"
        )
    return subject


def encode_account_owner_assignment_evidence_v2(
    value: AccountOwnerAssignmentEvidenceV2,
) -> dict[str, object]:
    """Encode complete approved evidence, including its complete subject."""

    AccountOwnerAssignmentEvidenceV2.__post_init__(value)
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "evidence_id": value.evidence_id,
        "evidence_version": value.evidence_version,
        "subject": encode_account_owner_assignment_subject_v2(value.subject),
        "assignment_state": value.assignment_state,
        "assigned_owner_user_id": value.assigned_owner_user_id,
        "approved_by": value.approved_by.to_payload(),
        "approved_at": _time(value.approved_at),
        "recorded_at": _time(value.recorded_at),
        "approval_valid_until": _time(value.approval_valid_until),
        "valid_until": _time(value.valid_until),
        "supersedes_content_hash": value.supersedes_content_hash,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "permission": value.permission,
        "status": value.status,
        "blocker_codes": list(value.blocker_codes),
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
    }


def decode_account_owner_assignment_evidence_v2(
    payload: object,
) -> AccountOwnerAssignmentEvidenceV2:
    """Decode with exact nested shapes and canonical equality."""

    data = _mapping(payload)
    _keys(data, _EVIDENCE_KEYS)
    try:
        actor_data = _mapping(data["approved_by"])
        _keys(actor_data, _ACTOR_KEYS)
        evidence = AccountOwnerAssignmentEvidenceV2(
            evidence_id=_string(data["evidence_id"]),
            evidence_version=_string(data["evidence_version"]),
            subject=decode_account_owner_assignment_subject_v2(data["subject"]),
            assignment_state=_string(data["assignment_state"]),
            assigned_owner_user_id=_optional_integer(data["assigned_owner_user_id"]),
            approved_by=_actor(actor_data),
            approved_at=_datetime(data["approved_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            approval_valid_until=_datetime(data["approval_valid_until"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
            account_claim_hash=_string(data["account_claim_hash"]),
            underlying_claim_hash=_string(data["underlying_claim_hash"]),
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
        raise AccountOwnerAssignmentEvidenceV2CodecError(
            "invalid owner-assignment v2 evidence"
        ) from error
    if encode_account_owner_assignment_evidence_v2(evidence) != payload:
        raise AccountOwnerAssignmentEvidenceV2CodecError(
            "non-canonical owner-assignment v2 evidence"
        )
    return evidence


def _encode_physical(subject: AccountOwnerAssignmentSubjectV2) -> dict[str, object]:
    recorder = PhysicalAccountRowObservationV2Recorder(
        recorder_id="account-owner-assignment-v2-codec",
        service_name="account-owner-assignment-v2-codec",
    )
    encoded = encode_physical_account_row_observation_v2_record(
        PersistedPhysicalAccountRowObservationV2(subject.physical, recorder)
    )
    return _mapping(encoded["observation"])


def _decode_physical(payload: object) -> PhysicalAccountRowObservationV2:
    recorder = {
        "recorder_id": "account-owner-assignment-v2-codec",
        "service_name": "account-owner-assignment-v2-codec",
        "role": "evidence_projector",
        "kind": "service",
        "is_automated": True,
    }
    return decode_physical_account_row_observation_v2_record(
        {"observation": payload, "recorded_by": recorder}
    ).observation


def _encode_receipt(subject: AccountOwnerAssignmentSubjectV2) -> dict[str, object]:
    claimant = subject.receipt.claimant
    issuer = AccountOwnerAssignmentServerActor(
        actor_id=claimant.actor_id,
        user_id=claimant.user_id,
        role=claimant.role,
        kind=claimant.kind,
        is_staff=claimant.is_staff,
    )
    encoded = encode_account_owner_assignment_provenance_receipt_v2_record(
        PersistedAccountOwnerAssignmentProvenanceReceiptV2(subject.receipt, issuer)
    )
    return _mapping(encoded["receipt"])


def _decode_receipt(payload: object) -> AccountOwnerAssignmentProvenanceReceiptV2:
    data = _mapping(payload)
    claimant = _mapping(data.get("claimant"))
    record = decode_account_owner_assignment_provenance_receipt_v2_record(
        {"receipt": payload, "issued_by": claimant}
    )
    return record.receipt


_SUBJECT_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "subject_id",
    "subject_version",
    "physical",
    "receipt",
    "requested_at",
    "valid_until",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
}
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
    "supersedes_content_hash",
    "account_claim_hash",
    "underlying_claim_hash",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentEvidenceV2CodecError("expected exact mapping")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise AccountOwnerAssignmentEvidenceV2CodecError("invalid payload shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountOwnerAssignmentEvidenceV2CodecError("expected exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountOwnerAssignmentEvidenceV2CodecError("expected exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountOwnerAssignmentEvidenceV2CodecError("expected exact boolean")
    return value


def _actor(value: dict[str, object]) -> AccountOwnerAssignmentActor:
    return AccountOwnerAssignmentActor(
        actor_id=_string(value["actor_id"]),
        user_id=_integer(value["user_id"]),
        role=_string(value["role"]),
        kind=_string(value["kind"]),
        is_staff=_boolean(value["is_staff"]),
    )


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentEvidenceV2CodecError("expected UTC Z time")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.isoformat().replace("+00:00", "Z") != text:
        raise AccountOwnerAssignmentEvidenceV2CodecError("non-canonical time")
    return result


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountOwnerAssignmentEvidenceV2CodecError("expected exact list")
    return tuple(_string(item) for item in cast(list[object], value))


__all__ = [
    "AccountOwnerAssignmentEvidenceV2CodecError",
    "decode_account_owner_assignment_evidence_v2",
    "decode_account_owner_assignment_subject_v2",
    "encode_account_owner_assignment_evidence_v2",
    "encode_account_owner_assignment_subject_v2",
]
