"""Unit contracts for the strict Subject V5 durable record codec."""

from copy import deepcopy

import pytest

from apps.account.application.account_owner_assignment_subject_v5 import (
    PersistedAccountOwnerAssignmentSubjectV5,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_record_codec import (
    AccountOwnerAssignmentSubjectV5RecordCodecError,
    decode_account_owner_assignment_subject_v5_record,
    encode_account_owner_assignment_subject_v5_record,
)
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


def _payload() -> dict[str, object]:
    return encode_account_owner_assignment_subject_v5_record(
        PersistedAccountOwnerAssignmentSubjectV5(_subject())
    )


def test_subject_v5_record_roundtrip_preserves_graph_and_seals() -> None:
    """Roundtrip retains the exact Subject graph and both application seals."""

    record = PersistedAccountOwnerAssignmentSubjectV5(_subject())
    assert (
        decode_account_owner_assignment_subject_v5_record(
            encode_account_owner_assignment_subject_v5_record(record)
        )
        == record
    )


@pytest.mark.parametrize("field", ["subject", "record_seal", "ledger_seal"])
def test_subject_v5_record_rejects_missing_fields(field: str) -> None:
    """Every durable envelope field is required."""

    payload = _payload()
    del payload[field]
    with pytest.raises(AccountOwnerAssignmentSubjectV5RecordCodecError):
        decode_account_owner_assignment_subject_v5_record(payload)


def test_subject_v5_record_rejects_extra_and_nonmapping_payloads() -> None:
    """The record boundary is closed against added fields and other JSON types."""

    payload = _payload()
    payload["authority"] = {}
    with pytest.raises(AccountOwnerAssignmentSubjectV5RecordCodecError):
        decode_account_owner_assignment_subject_v5_record(payload)
    with pytest.raises(AccountOwnerAssignmentSubjectV5RecordCodecError):
        decode_account_owner_assignment_subject_v5_record([])


@pytest.mark.parametrize("field", ["record_seal", "ledger_seal"])
def test_subject_v5_record_rejects_seal_tampering(field: str) -> None:
    """A recomputed or substituted envelope seal cannot cross the codec."""

    payload = _payload()
    payload[field] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentSubjectV5RecordCodecError):
        decode_account_owner_assignment_subject_v5_record(payload)


def test_subject_v5_record_rejects_nested_subject_tampering() -> None:
    """Nested receipt, Binding, re-observation, and Subject hashes remain sealed."""

    payload = deepcopy(_payload())
    subject = payload["subject"]
    assert type(subject) is dict
    subject["receipt_content_hash"] = "1" * 64
    with pytest.raises(AccountOwnerAssignmentSubjectV5RecordCodecError):
        decode_account_owner_assignment_subject_v5_record(payload)


def test_subject_v5_record_encoder_requires_exact_persisted_type() -> None:
    """V4 records and arbitrary objects cannot enter the V5 ledger."""

    with pytest.raises(AccountOwnerAssignmentSubjectV5RecordCodecError):
        encode_account_owner_assignment_subject_v5_record(object())  # type: ignore[arg-type]
