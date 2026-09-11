"""Strict canonical codecs for Account owner-assignment evidence v5."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_codec import (
    AccountOwnerAssignmentSubjectV5CodecError,
    decode_account_owner_assignment_subject_v5,
    encode_account_owner_assignment_subject_v5,
)


class AccountOwnerAssignmentEvidenceV5CodecError(ValueError):
    """A stored v5 evidence value is malformed or non-canonical."""


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


def encode_account_owner_assignment_evidence_v5(
    value: AccountOwnerAssignmentEvidenceV5,
) -> dict[str, object]:
    """Encode one complete Evidence v5 without dropping the nested Subject."""

    if type(value) is not AccountOwnerAssignmentEvidenceV5:
        raise AccountOwnerAssignmentEvidenceV5CodecError(
            "expected exact AccountOwnerAssignmentEvidenceV5"
        )
    try:
        value.__post_init__()
        _seal(value.identity_hash)
        _seal(value.content_hash)
        return value.to_payload()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5CodecError("evidence v5 cannot be encoded") from error


def decode_account_owner_assignment_evidence_v5(
    payload: object,
) -> AccountOwnerAssignmentEvidenceV5:
    """Decode one exact Evidence v5 payload and require canonical roundtrip."""

    data = _mapping(payload, "evidence")
    _keys(data, _EVIDENCE_KEYS, "evidence")
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    try:
        evidence = AccountOwnerAssignmentEvidenceV5(
            evidence_id=_text(data["evidence_id"]),
            evidence_version=_text(data["evidence_version"]),
            subject=decode_account_owner_assignment_subject_v5(data["subject"]),
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
        AccountOwnerAssignmentEvidenceV5CodecError,
        AccountOwnerAssignmentSubjectV5CodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AccountOwnerAssignmentEvidenceV5CodecError):
            raise
        raise AccountOwnerAssignmentEvidenceV5CodecError(
            "evidence-v5 payload is invalid"
        ) from error
    if encode_account_owner_assignment_evidence_v5(evidence) != payload:
        raise AccountOwnerAssignmentEvidenceV5CodecError("evidence-v5 payload is non-canonical")
    return evidence


def _mapping(value: object, name: str) -> dict[str, object]:
    """Require an exact string-keyed mapping container."""

    if type(value) is not dict:
        raise AccountOwnerAssignmentEvidenceV5CodecError(f"{name} must be an exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data):
        raise AccountOwnerAssignmentEvidenceV5CodecError(f"{name} keys must be exact strings")
    return data


def _keys(value: dict[str, object], expected: set[str], name: str) -> None:
    """Require the closed-world key set for one payload level."""

    if set(value) != expected:
        raise AccountOwnerAssignmentEvidenceV5CodecError(f"{name} has an invalid canonical shape")


def _text(value: object) -> str:
    """Require one exact string value."""

    if type(value) is not str:
        raise AccountOwnerAssignmentEvidenceV5CodecError("expected exact string")
    return value


def _integer(value: object) -> int:
    """Require one exact integer value and reject bool."""

    if type(value) is not int:
        raise AccountOwnerAssignmentEvidenceV5CodecError("expected exact integer")
    return value


def _boolean(value: object) -> bool:
    """Require one exact boolean value."""

    if type(value) is not bool:
        raise AccountOwnerAssignmentEvidenceV5CodecError("expected exact bool")
    return value


def _fixed_boolean(value: object, expected: bool, name: str) -> None:
    """Require one execution flag to retain its fixed value."""

    if _boolean(value) is not expected:
        raise AccountOwnerAssignmentEvidenceV5CodecError(f"{name} is fixed")


def _seal(value: object) -> str:
    """Require one complete lowercase SHA-256 seal, including non-blankness."""

    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AccountOwnerAssignmentEvidenceV5CodecError(
            "stored v5 value requires full lowercase seal"
        )
    return text


def _clock(value: object) -> datetime:
    """Require canonical UTC ``Z`` text with explicit microseconds."""

    text = _text(value)
    if not text.endswith("Z"):
        raise AccountOwnerAssignmentEvidenceV5CodecError("clock requires canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountOwnerAssignmentEvidenceV5CodecError("clock is invalid") from error
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != text:
        raise AccountOwnerAssignmentEvidenceV5CodecError("clock is non-canonical")
    return parsed


def _blockers(value: object) -> tuple[str, ...]:
    """Decode the canonical JSON list used for blocker codes."""

    if type(value) is not list:
        raise AccountOwnerAssignmentEvidenceV5CodecError("blocker_codes requires exact list")
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
    "AccountOwnerAssignmentEvidenceV5CodecError",
    "AccountOwnerAssignmentSubjectV5CodecError",
    "decode_account_owner_assignment_evidence_v5",
    "decode_account_owner_assignment_subject_v5",
    "encode_account_owner_assignment_evidence_v5",
    "encode_account_owner_assignment_subject_v5",
]
