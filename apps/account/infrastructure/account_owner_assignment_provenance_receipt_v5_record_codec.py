"""Strict persisted envelope codec for inactive Account owner ReceiptV5."""

from __future__ import annotations

from typing import cast

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_codec import (
    decode_account_owner_assignment_provenance_receipt_v5,
    encode_account_owner_assignment_provenance_receipt_v5,
)

_RECORD_KEYS = {"receipt", "record_seal", "ledger_seal"}


class AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(ValueError):
    """A persisted ReceiptV5 envelope has invalid shape or seals."""


def encode_account_owner_assignment_provenance_receipt_v5_record(
    value: PersistedAccountOwnerAssignmentProvenanceReceiptV5,
) -> dict[str, object]:
    """Encode one complete immutable ReceiptV5 record envelope."""

    if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV5:
        raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
            "expected exact V5 receipt record"
        )
    try:
        value.__post_init__()
        return {
            "receipt": encode_account_owner_assignment_provenance_receipt_v5(value.receipt),
            "record_seal": value.record_seal,
            "ledger_seal": value.ledger_seal,
        }
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
            "V5 receipt record cannot be encoded"
        ) from error


def decode_account_owner_assignment_provenance_receipt_v5_record(
    payload: object,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
    """Decode the exact V5 record envelope and verify canonical round trip."""

    try:
        if type(payload) is not dict or any(type(key) is not str for key in payload):
            raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
                "expected an exact JSON object"
            )
        data = cast(dict[str, object], payload)
        if set(data) != _RECORD_KEYS:
            raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
                "invalid V5 receipt record shape"
            )
        value = PersistedAccountOwnerAssignmentProvenanceReceiptV5(
            receipt=decode_account_owner_assignment_provenance_receipt_v5(data["receipt"]),
            record_seal=_text(data["record_seal"]),
            ledger_seal=_text(data["ledger_seal"]),
        )
        if encode_account_owner_assignment_provenance_receipt_v5_record(value) != data:
            raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
                "V5 receipt record is not canonical"
            )
        return value
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
            raise
        raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
            "invalid V5 receipt record"
        ) from error


def _text(value: object) -> str:
    """Require one exact envelope seal string before Domain validation."""

    if type(value) is not str:
        raise AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError(
            "V5 receipt record seals must be exact strings"
        )
    return value


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError",
    "decode_account_owner_assignment_provenance_receipt_v5_record",
    "encode_account_owner_assignment_provenance_receipt_v5_record",
]
