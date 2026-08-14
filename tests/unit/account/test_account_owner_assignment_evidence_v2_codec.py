"""Strict codec coverage for Account owner-assignment evidence v2."""

from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_owner_assignment_evidence_v2_codec import (
    AccountOwnerAssignmentEvidenceV2CodecError,
    decode_account_owner_assignment_evidence_v2,
    decode_account_owner_assignment_subject_v2,
    encode_account_owner_assignment_evidence_v2,
    encode_account_owner_assignment_subject_v2,
)
from tests.unit.account.test_account_owner_assignment_evidence_v2 import _evidence, _subject


def test_subject_roundtrip_preserves_complete_upstream_objects() -> None:
    subject = _subject()
    payload = encode_account_owner_assignment_subject_v2(subject)

    restored = decode_account_owner_assignment_subject_v2(payload)

    assert restored == subject
    assert restored.physical == subject.physical
    assert restored.receipt == subject.receipt
    assert encode_account_owner_assignment_subject_v2(restored) == payload
    assert isinstance(payload["physical"], dict)
    assert isinstance(payload["receipt"], dict)


def test_evidence_roundtrip_preserves_complete_nested_subject() -> None:
    evidence = _evidence()
    payload = encode_account_owner_assignment_evidence_v2(evidence)

    restored = decode_account_owner_assignment_evidence_v2(payload)

    assert restored == evidence
    assert restored.subject == evidence.subject
    assert restored.subject.physical == evidence.subject.physical
    assert restored.subject.receipt == evidence.subject.receipt
    assert encode_account_owner_assignment_evidence_v2(restored) == payload


@pytest.mark.parametrize("kind", ["subject", "evidence"])
def test_extra_top_level_key_is_rejected(kind: str) -> None:
    value = _subject() if kind == "subject" else _evidence()
    if kind == "subject":
        payload = encode_account_owner_assignment_subject_v2(value)  # type: ignore[arg-type]
        decode = decode_account_owner_assignment_subject_v2
    else:
        payload = encode_account_owner_assignment_evidence_v2(value)  # type: ignore[arg-type]
        decode = decode_account_owner_assignment_evidence_v2
    payload["extra"] = True

    with pytest.raises(AccountOwnerAssignmentEvidenceV2CodecError, match="shape"):
        decode(payload)


def test_nested_physical_tamper_is_rejected() -> None:
    payload = deepcopy(encode_account_owner_assignment_subject_v2(_subject()))
    physical = payload["physical"]
    assert isinstance(physical, dict)
    physical["account_id"] = "substituted"

    with pytest.raises(AccountOwnerAssignmentEvidenceV2CodecError):
        decode_account_owner_assignment_subject_v2(payload)


def test_nested_receipt_tamper_is_rejected() -> None:
    payload = deepcopy(encode_account_owner_assignment_subject_v2(_subject()))
    receipt = payload["receipt"]
    assert isinstance(receipt, dict)
    receipt["row_observation_content_hash"] = "0" * 64

    with pytest.raises(AccountOwnerAssignmentEvidenceV2CodecError):
        decode_account_owner_assignment_subject_v2(payload)


def test_nested_subject_tamper_is_rejected_from_evidence() -> None:
    payload = deepcopy(encode_account_owner_assignment_evidence_v2(_evidence()))
    subject = payload["subject"]
    assert isinstance(subject, dict)
    subject["content_hash"] = "0" * 64

    with pytest.raises(AccountOwnerAssignmentEvidenceV2CodecError):
        decode_account_owner_assignment_evidence_v2(payload)


def test_noncanonical_datetime_is_rejected() -> None:
    payload = encode_account_owner_assignment_evidence_v2(_evidence())
    payload["approved_at"] = "2026-08-07T12:00:00+00:00"

    with pytest.raises(AccountOwnerAssignmentEvidenceV2CodecError, match="invalid"):
        decode_account_owner_assignment_evidence_v2(payload)


def test_exact_bool_and_integer_types_are_enforced() -> None:
    payload = deepcopy(encode_account_owner_assignment_evidence_v2(_evidence()))
    actor = payload["approved_by"]
    assert isinstance(actor, dict)
    actor["is_staff"] = 1

    with pytest.raises(AccountOwnerAssignmentEvidenceV2CodecError):
        decode_account_owner_assignment_evidence_v2(payload)
