"""V4 storage decoding preserves the entire policy and canonical creation graph."""

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_codec import (
    AccountOwnerAssignmentProvenanceReceiptV3CodecError,
    decode_account_owner_assignment_provenance_receipt_v3_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_codec import (
    AccountOwnerAssignmentProvenanceReceiptV4CodecError,
    decode_account_owner_assignment_provenance_receipt_v4,
    encode_account_owner_assignment_provenance_receipt_v4,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import (
    _receipt as _v3_receipt,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import _receipt


def test_full_graph_roundtrip_preserves_real_staff_and_policy():
    receipt = _receipt()
    payload = encode_account_owner_assignment_provenance_receipt_v4(receipt)
    restored = decode_account_owner_assignment_provenance_receipt_v4(payload)
    assert restored == receipt
    assert restored.claimant.is_staff is True
    assert restored.policy == receipt.policy
    assert restored.binding == receipt.binding
    assert restored.policy_content_hash == receipt.policy.content_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_hash", ""),
        ("identity_hash", "0" * 64),
        ("policy_content_hash", "b" * 64),
        ("policy_identity_hash", None),
        ("assigned_owner_user_id", True),
        ("account_id", "another-account"),
        ("activation_available", 0),
        ("must_not_execute", 1),
        ("permission", "execute"),
        ("blocker_codes", []),
        ("issued_at", "2026-08-08T13:00:00Z"),
    ],
)
def test_modified_shapes_types_clocks_and_seals_fail_closed(field, value):
    payload = _receipt().to_payload()
    payload[field] = value
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4CodecError):
        decode_account_owner_assignment_provenance_receipt_v4(payload)


@pytest.mark.parametrize(
    "node,field,value",
    [
        ("policy", "owner_user_id", 123),
        ("policy", "tenant_id", "another-tenant"),
        ("binding", "account_id_claim", "another-account"),
        ("claimant", "is_staff", False),
        ("claimant", "user_id", True),
    ],
)
def test_nested_policy_creation_or_actor_tampering_is_rejected(node, field, value):
    payload = deepcopy(_receipt().to_payload())
    payload[node][field] = value
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4CodecError):
        decode_account_owner_assignment_provenance_receipt_v4(payload)


def test_missing_nested_graph_and_extra_policy_mode_are_rejected():
    payload = _receipt().to_payload()
    del payload["binding"]
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4CodecError):
        decode_account_owner_assignment_provenance_receipt_v4(payload)
    payload = _receipt().to_payload()
    payload["control_mode"] = "single_owner"
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4CodecError):
        decode_account_owner_assignment_provenance_receipt_v4(payload)


def test_legacy_v3_cannot_substitute_for_a_v4_receipt():
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4CodecError):
        decode_account_owner_assignment_provenance_receipt_v4(_v3_receipt().to_payload())
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4CodecError):
        encode_account_owner_assignment_provenance_receipt_v4(_v3_receipt())


def test_legacy_decoder_does_not_accept_a_v4_envelope():
    receipt = _receipt()
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV3CodecError):
        decode_account_owner_assignment_provenance_receipt_v3_record(
            {"receipt": receipt.to_payload(), "issued_by": receipt.claimant.to_payload()}
        )
