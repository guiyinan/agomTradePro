from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_owner_assignment_evidence_v3_codec import (
    AccountOwnerAssignmentEvidenceV3CodecError,
    decode_account_owner_assignment_evidence_v3,
    decode_account_owner_assignment_subject_v3,
    encode_account_owner_assignment_evidence_v3,
    encode_account_owner_assignment_subject_v3,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence


def test_complete_subject_receipt_binding_physical_source_raw_roundtrip() -> None:
    value = _evidence()
    payload = encode_account_owner_assignment_evidence_v3(value)
    restored = decode_account_owner_assignment_evidence_v3(payload)
    assert restored == value
    physical = restored.subject.physical_root.physical_observation
    assert physical.source_content_hash
    assert physical.raw_observation_content_hash
    assert restored.subject.receipt.binding == restored.subject.binding
    assert encode_account_owner_assignment_evidence_v3(restored) == payload


def test_pending_subject_has_an_independent_public_strict_codec() -> None:
    subject = _evidence().subject
    payload = encode_account_owner_assignment_subject_v3(subject)
    assert decode_account_owner_assignment_subject_v3(payload) == subject
    assert (
        encode_account_owner_assignment_subject_v3(
            decode_account_owner_assignment_subject_v3(payload)
        )
        == payload
    )


@pytest.mark.parametrize(
    "path",
    [
        ("content_hash",),
        ("identity_hash",),
        ("account_claim_hash",),
        ("subject", "content_hash"),
        ("subject", "receipt", "content_hash"),
        ("subject", "binding", "content_hash"),
        ("subject", "physical_root", "content_hash"),
        ("subject", "physical_root", "physical_observation", "content_hash"),
        (
            "subject",
            "physical_root",
            "physical_observation",
            "source_content_hash",
        ),
        (
            "subject",
            "physical_root",
            "physical_observation",
            "raw_observation_content_hash",
        ),
    ],
)
def test_nested_seal_tampering_fails_closed(path: tuple[str, ...]) -> None:
    payload = deepcopy(encode_account_owner_assignment_evidence_v3(_evidence()))
    target: object = payload
    for key in path[:-1]:
        assert type(target) is dict
        target = target[key]
    assert type(target) is dict
    target[path[-1]] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV3CodecError):
        decode_account_owner_assignment_evidence_v3(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("activation_available",), True),
        (("must_not_execute",), False),
        (("subject", "activation_available"), True),
        (("subject", "must_not_execute"), False),
        (("schema",), "account-owner-assignment-evidence.v2"),
        (("assignment_state",), "pending"),
        (("approved_by", "is_staff"), 1),
        (("approved_by", "user_id"), "9"),
        (("recorded_at",), "2026-08-09T12:00:00+00:00"),
        (("subject", "requested_at"), "2026-08-08T15:00:00+00:00"),
    ],
)
def test_fixed_semantics_types_actor_and_utc_z_are_strict(
    path: tuple[str, ...], value: object
) -> None:
    payload = deepcopy(encode_account_owner_assignment_evidence_v3(_evidence()))
    target: object = payload
    for key in path[:-1]:
        assert type(target) is dict
        target = target[key]
    assert type(target) is dict
    target[path[-1]] = value
    with pytest.raises(AccountOwnerAssignmentEvidenceV3CodecError):
        decode_account_owner_assignment_evidence_v3(payload)


def test_duplicate_nested_binding_or_root_cannot_be_laundered() -> None:
    payload = deepcopy(encode_account_owner_assignment_evidence_v3(_evidence()))
    subject = payload["subject"]
    assert type(subject) is dict
    binding = subject["binding"]
    assert type(binding) is dict
    binding["binding_id"] = "substituted-binding"
    with pytest.raises(AccountOwnerAssignmentEvidenceV3CodecError):
        decode_account_owner_assignment_evidence_v3(payload)


def test_exact_shapes_and_encoder_type_are_enforced() -> None:
    payload = deepcopy(encode_account_owner_assignment_evidence_v3(_evidence()))
    payload["extra"] = True
    with pytest.raises(AccountOwnerAssignmentEvidenceV3CodecError, match="shape"):
        decode_account_owner_assignment_evidence_v3(payload)
    with pytest.raises(AccountOwnerAssignmentEvidenceV3CodecError, match="mapping"):
        decode_account_owner_assignment_evidence_v3([])
    with pytest.raises(TypeError):
        encode_account_owner_assignment_evidence_v3(object())  # type: ignore[arg-type]
