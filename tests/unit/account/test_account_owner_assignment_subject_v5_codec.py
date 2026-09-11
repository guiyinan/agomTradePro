"""Unit coverage for the strict SubjectV5 JSON codec."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from apps.account.infrastructure.account_owner_assignment_subject_v5_codec import (
    AccountOwnerAssignmentSubjectV5CodecError,
    decode_account_owner_assignment_subject_v5,
    encode_account_owner_assignment_subject_v5,
)
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


def test_roundtrip_preserves_complete_v5_receipt_binding_and_reobservation_graph() -> None:
    """JSON round-trip keeps every nested source and inactive flags."""

    subject = _subject()
    payload = json.loads(json.dumps(encode_account_owner_assignment_subject_v5(subject)))

    assert decode_account_owner_assignment_subject_v5(payload) == subject
    assert payload["receipt"] == subject.receipt.to_payload()
    assert payload["binding"] == subject.binding.to_payload()
    assert payload["reobservation"] == subject.reobservation.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True


@pytest.mark.parametrize("section", [None, "receipt", "binding", "reobservation"])
def test_decoder_rejects_extra_fields_at_every_boundary(section: str | None) -> None:
    """Every object boundary is closed against unrelated additions."""

    payload = deepcopy(encode_account_owner_assignment_subject_v5(_subject()))
    target = payload if section is None else payload[section]
    target["unexpected"] = "value"  # type: ignore[index]

    with pytest.raises(AccountOwnerAssignmentSubjectV5CodecError):
        decode_account_owner_assignment_subject_v5(payload)


def test_decoder_rejects_v4_receipt_and_missing_v5_fields() -> None:
    """A V4 nested receipt or incomplete SubjectV5 cannot cross the boundary."""

    payload = deepcopy(encode_account_owner_assignment_subject_v5(_subject()))
    payload["receipt"]["schema"] = "account-owner-assignment-provenance-receipt.v4"  # type: ignore[index]
    with pytest.raises(AccountOwnerAssignmentSubjectV5CodecError):
        decode_account_owner_assignment_subject_v5(payload)

    payload = deepcopy(encode_account_owner_assignment_subject_v5(_subject()))
    del payload["reobservation"]
    with pytest.raises(AccountOwnerAssignmentSubjectV5CodecError):
        decode_account_owner_assignment_subject_v5(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity_hash", "0" * 64),
        ("content_hash", "1" * 64),
        ("receipt_content_hash", "2" * 64),
        ("binding_content_hash", "3" * 64),
        ("reobservation_content_hash", "4" * 64),
        ("requested_at", "2026-08-15T12:00:00+00:00"),
        ("activation_available", True),
    ],
)
def test_decoder_rejects_hash_clock_or_flag_tampering(field: str, value: object) -> None:
    """Mutated source seals, clocks, and inactive flags fail closed."""

    payload = deepcopy(encode_account_owner_assignment_subject_v5(_subject()))
    payload[field] = value

    with pytest.raises(AccountOwnerAssignmentSubjectV5CodecError):
        decode_account_owner_assignment_subject_v5(payload)


def test_encoder_requires_exact_v5_domain_type() -> None:
    """The encoder never accepts V4 or arbitrary object substitutions."""

    with pytest.raises(AccountOwnerAssignmentSubjectV5CodecError):
        encode_account_owner_assignment_subject_v5(object())  # type: ignore[arg-type]
