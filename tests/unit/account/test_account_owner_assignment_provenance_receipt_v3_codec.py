from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_codec import (
    AccountOwnerAssignmentProvenanceReceiptV3CodecError,
    decode_account_owner_assignment_provenance_receipt_v3_record,
    encode_account_owner_assignment_provenance_receipt_v3_record,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _receipt


def _record() -> PersistedAccountOwnerAssignmentProvenanceReceiptV3:
    return PersistedAccountOwnerAssignmentProvenanceReceiptV3(
        _receipt(),
        AccountOwnerAssignmentServerActor("human-42", 42, "account_owner_claimant"),
    )


def test_complete_nested_record_roundtrips_canonically() -> None:
    record = _record()
    payload = encode_account_owner_assignment_provenance_receipt_v3_record(record)
    restored = decode_account_owner_assignment_provenance_receipt_v3_record(payload)
    assert restored == record
    assert restored.receipt.binding.creation_root.physical_observation.source_content_hash
    assert restored.receipt.binding.creation_root.physical_observation.raw_observation_content_hash
    assert encode_account_owner_assignment_provenance_receipt_v3_record(restored) == payload


@pytest.mark.parametrize(
    "path",
    [
        ("receipt", "content_hash"),
        ("receipt", "identity_hash"),
        ("receipt", "binding", "content_hash"),
        ("receipt", "binding", "allocation", "content_hash"),
        ("receipt", "binding", "creation_root", "content_hash"),
        (
            "receipt",
            "binding",
            "creation_root",
            "physical_observation",
            "source_content_hash",
        ),
        (
            "receipt",
            "binding",
            "creation_root",
            "physical_observation",
            "raw_observation_content_hash",
        ),
    ],
)
def test_every_nested_seal_is_domain_revalidated(path: tuple[str, ...]) -> None:
    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v3_record(_record()))
    target: object = payload
    for key in path[:-1]:
        assert type(target) is dict
        target = target[key]
    assert type(target) is dict
    target[path[-1]] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV3CodecError):
        decode_account_owner_assignment_provenance_receipt_v3_record(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("receipt", "activation_available"), True),
        (("receipt", "must_not_execute"), False),
        (("receipt", "schema"), "account-owner-assignment-provenance-receipt.v2"),
        (("receipt", "provenance_kind"), "manual_reclaim"),
        (("receipt", "claimant", "user_id"), "42"),
        (("issued_by", "is_staff"), 0),
        (("receipt", "recorded_at"), "2026-08-08T14:00:00+00:00"),
    ],
)
def test_fixed_semantics_exact_types_and_utc_z_fail_closed(
    path: tuple[str, ...], value: object
) -> None:
    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v3_record(_record()))
    target: object = payload
    for key in path[:-1]:
        assert type(target) is dict
        target = target[key]
    assert type(target) is dict
    target[path[-1]] = value
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV3CodecError):
        decode_account_owner_assignment_provenance_receipt_v3_record(payload)


def test_extra_missing_and_non_mapping_shapes_are_rejected() -> None:
    payload = deepcopy(encode_account_owner_assignment_provenance_receipt_v3_record(_record()))
    payload["extra"] = True
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV3CodecError, match="shape"):
        decode_account_owner_assignment_provenance_receipt_v3_record(payload)
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV3CodecError, match="mapping"):
        decode_account_owner_assignment_provenance_receipt_v3_record([])


def test_encoder_rejects_non_exact_record() -> None:
    with pytest.raises(TypeError):
        encode_account_owner_assignment_provenance_receipt_v3_record(object())  # type: ignore[arg-type]
