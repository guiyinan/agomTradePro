from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
    AccountOwnerAssignmentSubjectV4,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_codec import (
    encode_account_owner_assignment_evidence_v3,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_codec import (
    AccountOwnerAssignmentEvidenceV4CodecError,
    decode_account_owner_assignment_evidence_v4,
    decode_account_owner_assignment_subject_v4,
    encode_account_owner_assignment_evidence_v4,
    encode_account_owner_assignment_subject_v4,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence as _v3_evidence
from tests.unit.account.test_account_owner_assignment_evidence_v4 import (
    _evidence,
    _subject,
)


def _copy(value: dict[str, object]) -> dict[str, object]:
    """Make an independent JSON-shaped payload for one mutation test."""

    return cast(dict[str, object], deepcopy(value))


def test_v4_subject_and_evidence_roundtrip_preserves_complete_nested_graph() -> None:
    subject = _subject()
    evidence = _evidence(subject)

    subject_payload = encode_account_owner_assignment_subject_v4(subject)
    evidence_payload = encode_account_owner_assignment_evidence_v4(evidence)

    assert decode_account_owner_assignment_subject_v4(subject_payload) == subject
    assert decode_account_owner_assignment_evidence_v4(evidence_payload) == evidence
    assert subject_payload["requested_at"] == "2026-08-08T15:00:00.000000Z"
    assert evidence_payload["approved_at"] == "2026-08-08T16:00:00.000000Z"
    assert evidence_payload["subject"] == subject_payload
    assert subject_payload["receipt"] == subject.receipt.to_payload()
    assert subject_payload["binding"] == subject.binding.to_payload()
    assert subject_payload["physical_root"] == subject.physical_root.to_payload()


def test_v4_codec_rejects_v3_values_and_exact_type_substitution() -> None:
    old_evidence = cast(AccountOwnerAssignmentEvidenceV3, _v3_evidence())

    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="shape|invalid"):
        decode_account_owner_assignment_subject_v4(
            encode_account_owner_assignment_evidence_v3(old_evidence)["subject"]  # type: ignore[index]
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="shape|invalid"):
        decode_account_owner_assignment_evidence_v4(
            encode_account_owner_assignment_evidence_v3(old_evidence)
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="exact"):
        encode_account_owner_assignment_subject_v4(cast(AccountOwnerAssignmentSubjectV4, object()))
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="exact"):
        encode_account_owner_assignment_evidence_v4(
            cast(AccountOwnerAssignmentEvidenceV4, object())
        )


@pytest.mark.parametrize("container", ["subject", "evidence"])
def test_v4_codec_closed_world_shape_rejects_missing_and_extra_keys(container: str) -> None:
    subject = _subject()
    payload = (
        encode_account_owner_assignment_subject_v4(subject)
        if container == "subject"
        else encode_account_owner_assignment_evidence_v4(_evidence(subject))
    )
    missing = _copy(payload)
    missing.pop(next(iter(missing)))
    extra = _copy(payload)
    extra["unexpected"] = "reject"

    decoder = (
        decode_account_owner_assignment_subject_v4
        if container == "subject"
        else decode_account_owner_assignment_evidence_v4
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="shape"):
        decoder(missing)
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="shape"):
        decoder(extra)


@pytest.mark.parametrize(
    "field_name",
    [
        "identity_hash",
        "content_hash",
        "receipt_identity_hash",
        "receipt_content_hash",
        "policy_identity_hash",
        "policy_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "allocation_identity_hash",
        "allocation_content_hash",
        "creation_root_identity_hash",
        "creation_root_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "physical_observation_content_hash",
        "physical_source_content_hash",
        "physical_raw_observation_content_hash",
    ],
)
def test_subject_decode_requires_nonblank_seals(field_name: str) -> None:
    payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))
    payload[field_name] = ""

    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="seal"):
        decode_account_owner_assignment_subject_v4(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "identity_hash",
        "content_hash",
        "policy_identity_hash",
        "policy_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
    ],
)
def test_evidence_decode_requires_nonblank_seals(field_name: str) -> None:
    payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    payload[field_name] = ""

    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="seal"):
        decode_account_owner_assignment_evidence_v4(payload)


def test_v4_codec_rejects_boolean_integer_and_execution_flag_substitutions() -> None:
    subject_payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))
    subject_payload["activation_available"] = 0
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="bool|fixed"):
        decode_account_owner_assignment_subject_v4(subject_payload)

    evidence_payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    evidence_payload["assigned_owner_user_id"] = True
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="integer"):
        decode_account_owner_assignment_evidence_v4(evidence_payload)
    evidence_payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    evidence_payload["must_not_execute"] = 1
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="bool|fixed"):
        decode_account_owner_assignment_evidence_v4(evidence_payload)

    evidence_payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    actor = cast(dict[str, object], evidence_payload["approved_by"])
    actor["is_staff"] = 1
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="bool|invalid"):
        decode_account_owner_assignment_evidence_v4(evidence_payload)


@pytest.mark.parametrize("field_name", ["requested_at", "valid_until"])
def test_subject_codec_rejects_noncanonical_clock_text(field_name: str) -> None:
    payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))
    payload[field_name] = cast(str, payload[field_name]).replace(".000000Z", "Z")

    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="canonical"):
        decode_account_owner_assignment_subject_v4(payload)


def test_evidence_codec_rejects_noncanonical_clock_offset_and_bad_actor_shape() -> None:
    payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    payload["approved_at"] = "2026-08-08T16:00:00.000000+00:00"
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="UTC|canonical"):
        decode_account_owner_assignment_evidence_v4(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    actor = cast(dict[str, object], payload["approved_by"])
    actor.pop("role")
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="shape"):
        decode_account_owner_assignment_evidence_v4(payload)


def test_v4_codec_rejects_nested_receipt_binding_physical_and_hash_tampering() -> None:
    payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))

    receipt = cast(dict[str, object], payload["receipt"])
    policy = cast(dict[str, object], receipt["policy"])
    policy["account_id"] = "different-account"
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="invalid|receipt"):
        decode_account_owner_assignment_subject_v4(payload)

    payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))
    physical = cast(dict[str, object], payload["physical_root"])
    physical["content_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="physical|invalid"):
        decode_account_owner_assignment_subject_v4(payload)

    payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))
    payload["policy_content_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="seal|invalid"):
        decode_account_owner_assignment_subject_v4(payload)


def test_v4_codec_rejects_nested_subject_tampering_and_noncanonical_roundtrip() -> None:
    payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    subject = cast(dict[str, object], payload["subject"])
    subject["status"] = "active"
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="invalid|fixed"):
        decode_account_owner_assignment_evidence_v4(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    subject = cast(dict[str, object], payload["subject"])
    subject["content_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="invalid|hash|seal"):
        decode_account_owner_assignment_evidence_v4(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    payload["policy_identity_hash"] = "f" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="invalid|seal"):
        decode_account_owner_assignment_evidence_v4(payload)


def test_v4_codec_does_not_accept_naive_datetime_objects_or_nonlist_blockers() -> None:
    subject_payload = _copy(encode_account_owner_assignment_subject_v4(_subject()))
    subject_payload["requested_at"] = datetime(2026, 8, 8, 15, tzinfo=UTC)
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="clock|string"):
        decode_account_owner_assignment_subject_v4(subject_payload)

    evidence_payload = _copy(encode_account_owner_assignment_evidence_v4(_evidence()))
    evidence_payload["blocker_codes"] = tuple(cast(list[object], evidence_payload["blocker_codes"]))
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="list|mapping"):
        decode_account_owner_assignment_evidence_v4(evidence_payload)


def test_v4_encode_revalidates_tampered_domain_hashes() -> None:
    subject = _subject()
    object.__setattr__(subject, "content_hash", "0" * 64)
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="encode|invalid"):
        encode_account_owner_assignment_subject_v4(subject)

    evidence = _evidence()
    object.__setattr__(evidence, "identity_hash", "0" * 64)
    with pytest.raises(AccountOwnerAssignmentEvidenceV4CodecError, match="encode|invalid"):
        encode_account_owner_assignment_evidence_v4(evidence)
