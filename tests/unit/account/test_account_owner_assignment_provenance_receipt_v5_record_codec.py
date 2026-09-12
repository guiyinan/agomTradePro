"""Unit contracts for the ReceiptV5 persisted record envelope codec."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_record_codec import (
    AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError,
    decode_account_owner_assignment_provenance_receipt_v5_record,
    encode_account_owner_assignment_provenance_receipt_v5_record,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import (
    _receipt as _v4_receipt,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v5 import _receipt


def _record() -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
    """Build one sealed persisted V5 record from the Domain fixture."""

    return PersistedAccountOwnerAssignmentProvenanceReceiptV5(_receipt())


def test_record_codec_round_trips_exact_closed_envelope() -> None:
    """Encoding includes exactly the nested receipt and both durable seals."""

    record = _record()
    payload = encode_account_owner_assignment_provenance_receipt_v5_record(record)

    assert set(payload) == {"receipt", "record_seal", "ledger_seal"}
    assert payload["receipt"] == record.receipt.to_payload()
    assert payload["record_seal"] == record.record_seal
    assert payload["ledger_seal"] == record.ledger_seal
    assert decode_account_owner_assignment_provenance_receipt_v5_record(payload) == record


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {},
    ],
)
def test_record_codec_rejects_added_or_missing_envelope_fields(change: dict[str, object]) -> None:
    """The envelope is closed and cannot silently gain or lose fields."""

    payload = encode_account_owner_assignment_provenance_receipt_v5_record(_record())
    if change:
        payload.update(change)
    else:
        del payload["ledger_seal"]
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(payload)


def test_record_codec_rejects_v4_nested_receipt_and_wrong_envelope_types() -> None:
    """V4 values and non-string seals cannot cross the V5 record boundary."""

    v4_payload = encode_account_owner_assignment_provenance_receipt_v5_record(_record())
    v4_payload["receipt"] = cast(object, _v4_receipt().to_payload())
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(v4_payload)

    typed_payload = encode_account_owner_assignment_provenance_receipt_v5_record(_record())
    typed_payload["record_seal"] = 7
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(typed_payload)

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        encode_account_owner_assignment_provenance_receipt_v5_record(cast(object, _v4_receipt()))


@pytest.mark.parametrize("field", ["record_seal", "ledger_seal"])
def test_record_codec_rejects_tampered_seals(field: str) -> None:
    """A changed record or ledger seal is rejected by the persisted wrapper."""

    payload = encode_account_owner_assignment_provenance_receipt_v5_record(_record())
    payload[field] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(payload)


def test_record_codec_rejects_tampered_nested_hash() -> None:
    """A nested ReceiptV5 content hash change fails sealed Domain decoding."""

    payload = encode_account_owner_assignment_provenance_receipt_v5_record(_record())
    receipt_payload = cast(dict[str, object], payload["receipt"])
    receipt_payload["content_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(payload)


def test_record_codec_rejects_noncanonical_nested_mapping() -> None:
    """A semantically equivalent reordered or altered nested value cannot bypass seals."""

    payload = encode_account_owner_assignment_provenance_receipt_v5_record(_record())
    receipt_payload = cast(dict[str, object], payload["receipt"])
    receipt_payload["owner"] = "v4"
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(payload)


def test_record_wrapper_rejects_changed_receipt_before_encoding() -> None:
    """The immutable application envelope recomputes and rejects changed hashes."""

    receipt = _receipt()
    changed = replace(receipt, receipt_version="v5.9", identity_hash="", content_hash="")
    changed_record = PersistedAccountOwnerAssignmentProvenanceReceiptV5(changed)
    payload = encode_account_owner_assignment_provenance_receipt_v5_record(changed_record)
    payload["ledger_seal"] = _record().ledger_seal
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError):
        decode_account_owner_assignment_provenance_receipt_v5_record(payload)
