"""Strict authenticated record codec tests, independent of database provenance."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_record_codec import (
    AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_record_codec import (
    decode_account_owner_assignment_provenance_receipt_v4_record as decode,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_record_codec import (
    encode_account_owner_assignment_provenance_receipt_v4_record as encode,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import _receipt


def _record() -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    receipt = _receipt()
    claimant = receipt.claimant
    return PersistedAccountOwnerAssignmentProvenanceReceiptV4(
        receipt,
        AccountOwnerAssignmentServerActor(
            claimant.actor_id, claimant.user_id, claimant.role, claimant.kind, claimant.is_staff
        ),
        CurrentAccountActorAuthorityV3(
            "test-principal",
            claimant.user_id,
            "b" * 64,
            claimant.actor_id,
            True,
            True,
            True,
            True,
            "admin",
            "test-source",
            "1",
            "c" * 64,
            receipt.issued_at - timedelta(seconds=1),
            receipt.valid_until,
        ),
    )


def test_record_json_roundtrip_preserves_authentication_and_real_staff() -> None:
    record = _record()
    payload = json.loads(json.dumps(encode(record)))
    assert decode(payload) == record
    assert payload["authority"]["authentication_context_hash"] == "b" * 64
    assert payload["issued_by"]["is_staff"] is True
    assert payload["receipt"]["policy"] == record.receipt.policy.to_payload()


@pytest.mark.parametrize("section", [None, "receipt", "issued_by", "authority"])
def test_record_rejects_extra_keys_at_each_boundary(section: str | None) -> None:
    payload = deepcopy(encode(_record()))
    target = payload if section is None else payload[section]
    target["unexpected"] = "value"
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError):
        decode(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", True),
        ("user_id", 991),
        ("actor_id", "different-actor"),
        ("is_staff", False),
        ("is_staff", 1),
        ("is_active", False),
        ("is_authenticated", False),
        ("is_superuser", 1),
        ("rbac_role", "user"),
        ("authentication_context_hash", ""),
        ("source_content_hash", "z" * 64),
        ("recorded_at", "2026-08-09T12:00:00+00:00"),
        ("recorded_at", "2026-08-09T12:00:00Z"),
        ("recorded_at", "2026-08-09T12:00:00"),
        ("recorded_at", "2026-08-12T12:00:00.000000Z"),
        ("valid_until", "2026-08-09T12:00:00.000000Z"),
    ],
)
def test_record_rejects_unbound_or_invalid_actor_facts(field: str, value: object) -> None:
    payload = deepcopy(encode(_record()))
    payload["authority"][field] = value
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError):
        decode(payload)


@pytest.mark.parametrize("field,value", [("is_staff", 1), ("user_id", True), ("role", "admin")])
def test_issuer_cannot_be_coerced_or_replaced(field: str, value: object) -> None:
    payload = deepcopy(encode(_record()))
    payload["issued_by"][field] = value
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError):
        decode(payload)


def test_record_requires_authority_envelope_and_v4_receipt() -> None:
    payload = encode(_record())
    payload.pop("authority")
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError):
        decode(payload)
    payload = encode(_record())
    payload["receipt"]["schema"] = "account-owner-assignment-provenance-receipt.v3"
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError):
        decode(payload)


def test_encoder_revalidates_mutated_frozen_authority() -> None:
    record = _record()
    authority = replace(record.authority)
    mutated = replace(record, authority=authority)
    object.__setattr__(authority, "is_active", False)
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV4RecordCodecError):
        encode(mutated)
