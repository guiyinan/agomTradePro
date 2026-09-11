"""Closed-world durable record codec for Account owner Subject V5."""

from __future__ import annotations

from typing import cast

from apps.account.application.account_owner_assignment_subject_v5 import (
    PersistedAccountOwnerAssignmentSubjectV5,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_codec import (
    decode_account_owner_assignment_subject_v5,
    encode_account_owner_assignment_subject_v5,
)


class AccountOwnerAssignmentSubjectV5RecordCodecError(ValueError):
    """A persisted Subject V5 envelope has an invalid shape or seal."""


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountOwnerAssignmentSubjectV5RecordCodecError(
            "Subject V5 record must be an exact mapping"
        )
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != {
        "subject",
        "record_seal",
        "ledger_seal",
    }:
        raise AccountOwnerAssignmentSubjectV5RecordCodecError(
            "Subject V5 record has an invalid shape"
        )
    return data


def _seal(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AccountOwnerAssignmentSubjectV5RecordCodecError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def encode_account_owner_assignment_subject_v5_record(
    value: PersistedAccountOwnerAssignmentSubjectV5,
) -> dict[str, object]:
    """Encode the exact Subject V5 graph and both durable seals."""

    if type(value) is not PersistedAccountOwnerAssignmentSubjectV5:
        raise AccountOwnerAssignmentSubjectV5RecordCodecError(
            "expected exact PersistedAccountOwnerAssignmentSubjectV5"
        )
    try:
        value.__post_init__()
        return {
            "subject": encode_account_owner_assignment_subject_v5(value.subject),
            "record_seal": _seal(value.record_seal, "record_seal"),
            "ledger_seal": _seal(value.ledger_seal, "ledger_seal"),
        }
    except (TypeError, ValueError) as error:
        if isinstance(error, AccountOwnerAssignmentSubjectV5RecordCodecError):
            raise
        raise AccountOwnerAssignmentSubjectV5RecordCodecError(
            "Subject V5 record cannot be encoded"
        ) from error


def decode_account_owner_assignment_subject_v5_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentSubjectV5:
    """Decode one closed-world Subject V5 record and require canonical roundtrip."""

    try:
        data = _mapping(payload)
        result = PersistedAccountOwnerAssignmentSubjectV5(
            subject=decode_account_owner_assignment_subject_v5(data["subject"]),
            record_seal=_seal(data["record_seal"], "record_seal"),
            ledger_seal=_seal(data["ledger_seal"], "ledger_seal"),
        )
        if encode_account_owner_assignment_subject_v5_record(result) != data:
            raise AccountOwnerAssignmentSubjectV5RecordCodecError(
                "Subject V5 record is not canonical"
            )
        return result
    except AccountOwnerAssignmentSubjectV5RecordCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentSubjectV5RecordCodecError(
            "invalid sealed Subject V5 record"
        ) from error


__all__ = [
    "AccountOwnerAssignmentSubjectV5RecordCodecError",
    "decode_account_owner_assignment_subject_v5_record",
    "encode_account_owner_assignment_subject_v5_record",
]
