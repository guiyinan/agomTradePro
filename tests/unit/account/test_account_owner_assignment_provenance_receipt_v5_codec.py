"""Unit coverage for the strict ReceiptV5 JSON codec."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_codec import (
    AccountOwnerAssignmentProvenanceReceiptV5CodecError,
    decode_account_owner_assignment_provenance_receipt_v5,
    encode_account_owner_assignment_provenance_receipt_v5,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v5 import _receipt


def test_roundtrip_preserves_complete_v5_policy_binding_and_reobservation_graph() -> None:
    """JSON round-trip keeps every nested V5 source and inactive flags."""

    receipt = _receipt()
    payload = json.loads(json.dumps(encode_account_owner_assignment_provenance_receipt_v5(receipt)))

    assert decode_account_owner_assignment_provenance_receipt_v5(payload) == receipt
    assert payload["policy"] == receipt.policy.to_payload()
    assert payload["binding"] == receipt.binding.to_payload()
    assert payload["reobservation"] == receipt.reobservation.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True


@pytest.mark.parametrize("section", [None, "policy", "binding", "reobservation", "claimant"])
def test_decoder_rejects_extra_fields_at_every_boundary(section: str | None) -> None:
    """Every object boundary is closed against V4 or unrelated additions."""

    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v5(_receipt()))
    target = payload if section is None else payload[section]
    target["unexpected"] = "value"  # type: ignore[index]

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5CodecError):
        decode_account_owner_assignment_provenance_receipt_v5(payload)


def test_decoder_rejects_v4_payload_and_missing_v5_fields() -> None:
    """A V4 shape cannot cross the exact V5 codec boundary."""

    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v5(_receipt()))
    payload["schema"] = "account-owner-assignment-provenance-receipt.v4"
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5CodecError):
        decode_account_owner_assignment_provenance_receipt_v5(payload)

    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v5(_receipt()))
    del payload["reobservation"]
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5CodecError):
        decode_account_owner_assignment_provenance_receipt_v5(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity_hash", "0" * 64),
        ("content_hash", "1" * 64),
        ("policy_content_hash", "2" * 64),
        ("binding_content_hash", "3" * 64),
        ("reobservation_content_hash", "4" * 64),
        ("assigned_owner_user_id", True),
        ("activation_available", True),
    ],
)
def test_decoder_rejects_seal_or_exact_type_tampering(field: str, value: object) -> None:
    """Mutated source seals, integers, and inactive flags fail closed."""

    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v5(_receipt()))
    payload[field] = value

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5CodecError):
        decode_account_owner_assignment_provenance_receipt_v5(payload)


def test_encoder_requires_exact_v5_domain_type() -> None:
    """The encoder never accepts V4 or arbitrary object substitutions."""

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5CodecError):
        encode_account_owner_assignment_provenance_receipt_v5(object())  # type: ignore[arg-type]
