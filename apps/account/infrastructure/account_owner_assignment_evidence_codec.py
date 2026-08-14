"""Strict canonical codecs for Account owner-assignment subjects and evidence."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentSubject,
    ExactAccountAssignmentProvenanceReceipt,
    ExactAccountRowObservation,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
    AccountOwnerAssignmentEvidence,
)


class AccountOwnerAssignmentEvidenceCodecError(ValueError):
    """A persisted owner-assignment payload is malformed or non-canonical."""


def encode_account_owner_assignment_subject(
    value: AccountOwnerAssignmentSubject,
) -> dict[str, object]:
    """Encode one complete immutable registration subject."""

    return {**value._content_payload(), "content_hash": value.content_hash}


def decode_account_owner_assignment_subject(
    payload: object,
) -> AccountOwnerAssignmentSubject:
    """Restore and revalidate one complete immutable registration subject."""

    data = _mapping(
        payload,
        {
            "evidence_id",
            "evidence_version",
            "row",
            "receipt",
            "claimant",
            "requested_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        value = AccountOwnerAssignmentSubject(
            evidence_id=_string(data["evidence_id"]),
            evidence_version=_string(data["evidence_version"]),
            row=_decode_row(data["row"]),
            receipt=_decode_receipt(data["receipt"]),
            claimant=_decode_server_actor(data["claimant"]),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (AccountOwnerAssignmentEvidenceCodecError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceCodecError(
            "owner-assignment subject is invalid"
        ) from error
    _require_canonical(payload, encode_account_owner_assignment_subject(value))
    return value


def encode_account_owner_assignment_evidence(
    value: AccountOwnerAssignmentEvidence,
) -> dict[str, object]:
    """Encode one complete immutable inactive assignment evidence record."""

    return value.to_payload()


def decode_account_owner_assignment_evidence(
    payload: object,
) -> AccountOwnerAssignmentEvidence:
    """Restore and revalidate one complete immutable inactive evidence record."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "evidence_id",
            "evidence_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "underlying_unified_account_id",
            "assignment_state",
            "assigned_owner_user_id",
            "row_observation_owner",
            "row_observation_artifact_type",
            "row_observation_id",
            "row_observation_version",
            "row_observation_content_hash",
            "provenance_kind",
            "provenance_ref_owner",
            "provenance_ref_artifact_type",
            "provenance_ref_id",
            "provenance_ref_version",
            "provenance_ref_content_hash",
            "subject_content_hash",
            "claimant",
            "approved_by",
            "issued_at",
            "approved_at",
            "recorded_at",
            "valid_until",
            "supersedes_content_hash",
            "permission",
            "status",
            "blocker_codes",
            "identity_hash",
            "content_hash",
            "activation_available",
            "must_not_execute",
        },
    )
    try:
        if _boolean(data["activation_available"]) is not False:
            raise ValueError("activation_available must remain false")
        if _boolean(data["must_not_execute"]) is not True:
            raise ValueError("must_not_execute must remain true")
        value = AccountOwnerAssignmentEvidence(
            evidence_id=_string(data["evidence_id"]),
            evidence_version=_string(data["evidence_version"]),
            account_namespace=_string(data["account_namespace"]),
            account_id=_string(data["account_id"]),
            underlying_unified_account_namespace=_string(
                data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_positive_integer(data["underlying_unified_account_id"]),
            assignment_state=_string(data["assignment_state"]),
            assigned_owner_user_id=_optional_positive_integer(data["assigned_owner_user_id"]),
            row_observation_owner=_string(data["row_observation_owner"]),
            row_observation_artifact_type=_string(data["row_observation_artifact_type"]),
            row_observation_id=_string(data["row_observation_id"]),
            row_observation_version=_string(data["row_observation_version"]),
            row_observation_content_hash=_string(data["row_observation_content_hash"]),
            provenance_kind=_string(data["provenance_kind"]),
            provenance_ref_owner=_string(data["provenance_ref_owner"]),
            provenance_ref_artifact_type=_string(data["provenance_ref_artifact_type"]),
            provenance_ref_id=_string(data["provenance_ref_id"]),
            provenance_ref_version=_string(data["provenance_ref_version"]),
            provenance_ref_content_hash=_string(data["provenance_ref_content_hash"]),
            subject_content_hash=_string(data["subject_content_hash"]),
            claimant=_decode_domain_actor(data["claimant"]),
            approved_by=_decode_domain_actor(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            approved_at=_datetime(data["approved_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
        )
    except (AccountOwnerAssignmentEvidenceCodecError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceCodecError(
            "owner-assignment evidence is invalid"
        ) from error
    _require_canonical(payload, encode_account_owner_assignment_evidence(value))
    return value


def _decode_row(payload: object) -> ExactAccountRowObservation:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "observation_id",
            "observation_version",
            "content_hash",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "underlying_unified_account_id",
            "observed_at",
            "recorded_at",
            "valid_until",
        },
    )
    value = ExactAccountRowObservation(
        observation_id=_string(data["observation_id"]),
        observation_version=_string(data["observation_version"]),
        content_hash=_string(data["content_hash"]),
        account_namespace=_string(data["account_namespace"]),
        account_id=_string(data["account_id"]),
        underlying_unified_account_namespace=_string(data["underlying_unified_account_namespace"]),
        underlying_unified_account_id=_positive_integer(data["underlying_unified_account_id"]),
        observed_at=_datetime(data["observed_at"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
    )
    _require_canonical(payload, value.to_payload())
    return value


def _decode_receipt(payload: object) -> ExactAccountAssignmentProvenanceReceipt:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "receipt_id",
            "receipt_version",
            "content_hash",
            "provenance_kind",
            "assignment_state",
            "assigned_owner_user_id",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "underlying_unified_account_id",
            "row_observation_id",
            "row_observation_version",
            "row_observation_content_hash",
            "claimant",
            "issued_at",
            "recorded_at",
            "valid_until",
        },
    )
    claimant = _decode_server_actor(data["claimant"])
    value = ExactAccountAssignmentProvenanceReceipt(
        receipt_id=_string(data["receipt_id"]),
        receipt_version=_string(data["receipt_version"]),
        content_hash=_string(data["content_hash"]),
        provenance_kind=_string(data["provenance_kind"]),
        assignment_state=_string(data["assignment_state"]),
        assigned_owner_user_id=_optional_positive_integer(data["assigned_owner_user_id"]),
        account_namespace=_string(data["account_namespace"]),
        account_id=_string(data["account_id"]),
        underlying_unified_account_namespace=_string(data["underlying_unified_account_namespace"]),
        underlying_unified_account_id=_positive_integer(data["underlying_unified_account_id"]),
        row_observation_id=_string(data["row_observation_id"]),
        row_observation_version=_string(data["row_observation_version"]),
        row_observation_content_hash=_string(data["row_observation_content_hash"]),
        claimant_actor_id=claimant.actor_id,
        claimant_user_id=claimant.user_id,
        claimant_role=claimant.role,
        claimant_kind=claimant.kind,
        claimant_is_staff=claimant.is_staff,
        issued_at=_datetime(data["issued_at"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
    )
    _require_canonical(payload, value.to_payload())
    return value


def _decode_server_actor(payload: object) -> AccountOwnerAssignmentServerActor:
    data = _mapping(payload, {"actor_id", "user_id", "role", "kind", "is_staff"})
    value = AccountOwnerAssignmentServerActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )
    _require_canonical(payload, value.to_payload())
    return value


def _decode_domain_actor(payload: object) -> AccountOwnerAssignmentActor:
    data = _mapping(payload, {"actor_id", "user_id", "role", "kind", "is_staff"})
    value = AccountOwnerAssignmentActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )
    _require_canonical(payload, value.to_payload())
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise AccountOwnerAssignmentEvidenceCodecError("owner-assignment payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected bool")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _optional_positive_integer(value: object) -> int | None:
    return None if value is None else _positive_integer(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError("expected a string list")
    return tuple(cast(list[str], value))


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed


def _require_canonical(original: object, canonical: dict[str, object]) -> None:
    if original != canonical:
        raise AccountOwnerAssignmentEvidenceCodecError("owner-assignment payload is not canonical")


__all__ = [
    "AccountOwnerAssignmentEvidenceCodecError",
    "decode_account_owner_assignment_evidence",
    "decode_account_owner_assignment_subject",
    "encode_account_owner_assignment_evidence",
    "encode_account_owner_assignment_subject",
]
