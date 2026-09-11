"""Unit coverage for the strict EvidenceV5 JSON codec."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.account.infrastructure.account_owner_assignment_evidence_v3_codec import (
    encode_account_owner_assignment_evidence_v3,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_codec import (
    encode_account_owner_assignment_evidence_v4,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_codec import (
    AccountOwnerAssignmentEvidenceV5CodecError,
    decode_account_owner_assignment_evidence_v5,
    encode_account_owner_assignment_evidence_v5,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import (
    _evidence as _v3_evidence,
)
from tests.unit.account.test_account_owner_assignment_evidence_v4 import (
    _evidence as _v4_evidence,
)
from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence


def _copy(value: dict[str, object]) -> dict[str, object]:
    """Make an independent JSON-shaped payload for one mutation test."""

    return cast(dict[str, object], deepcopy(value))


def test_v5_evidence_roundtrip_preserves_complete_subject_graph() -> None:
    """JSON roundtrip keeps every nested SubjectV5 source and inactive flags."""

    evidence = _evidence()
    payload = json.loads(json.dumps(encode_account_owner_assignment_evidence_v5(evidence)))

    assert decode_account_owner_assignment_evidence_v5(payload) == evidence
    assert payload["subject"] == evidence.subject.to_payload()
    assert payload["approved_by"] == evidence.approved_by.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True


def test_v5_codec_rejects_cross_version_values_and_exact_type_substitution() -> None:
    """V3/V4 payloads and arbitrary objects cannot cross the V5 boundary."""

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="shape|invalid"):
        decode_account_owner_assignment_evidence_v5(
            encode_account_owner_assignment_evidence_v4(_v4_evidence())
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="shape|invalid"):
        decode_account_owner_assignment_evidence_v5(
            encode_account_owner_assignment_evidence_v4(_v4_evidence())["subject"]  # type: ignore[index]
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="shape|invalid"):
        decode_account_owner_assignment_evidence_v5(
            encode_account_owner_assignment_evidence_v3(_v3_evidence())
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="exact"):
        encode_account_owner_assignment_evidence_v5(cast(object, _v4_evidence()))


def test_v5_codec_rejects_untyped_encode_substitution() -> None:
    """An object with a coincidental payload method is still not a Domain value."""

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="exact"):
        encode_account_owner_assignment_evidence_v5(cast(object, object()))


@pytest.mark.parametrize("missing", ["subject", "approved_by", "identity_hash"])
def test_v5_codec_closed_world_shape_rejects_missing_keys(missing: str) -> None:
    """Every top-level EvidenceV5 field is required."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    del payload[missing]

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="shape"):
        decode_account_owner_assignment_evidence_v5(payload)


def test_v5_codec_closed_world_shape_rejects_extra_keys() -> None:
    """Unknown top-level EvidenceV5 fields are rejected before construction."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["unexpected"] = "reject"

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="shape"):
        decode_account_owner_assignment_evidence_v5(payload)


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
def test_v5_codec_requires_nonblank_seals(field_name: str) -> None:
    """Stored EvidenceV5 seals must be complete lowercase SHA-256 values."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload[field_name] = ""

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="seal"):
        decode_account_owner_assignment_evidence_v5(payload)


def test_v5_codec_rejects_boolean_integer_and_execution_flag_substitutions() -> None:
    """Integer truthiness and mutable execution flags fail closed."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["assigned_owner_user_id"] = True
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="integer"):
        decode_account_owner_assignment_evidence_v5(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["activation_available"] = 0
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="bool|fixed"):
        decode_account_owner_assignment_evidence_v5(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["must_not_execute"] = 1
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="bool|fixed"):
        decode_account_owner_assignment_evidence_v5(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    actor = cast(dict[str, object], payload["approved_by"])
    actor["is_staff"] = 1
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="bool|invalid"):
        decode_account_owner_assignment_evidence_v5(payload)


@pytest.mark.parametrize(
    "field_name",
    ["approved_at", "recorded_at", "approval_valid_until", "valid_until"],
)
def test_v5_codec_rejects_noncanonical_clock_text(field_name: str) -> None:
    """All EvidenceV5 clocks require canonical UTC text with microseconds."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload[field_name] = cast(str, payload[field_name]).replace(".000000Z", "Z")

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="canonical"):
        decode_account_owner_assignment_evidence_v5(payload)


def test_v5_codec_rejects_bad_actor_shape_and_nonlist_blockers() -> None:
    """Nested actors and blocker lists retain exact JSON container shapes."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    actor = cast(dict[str, object], payload["approved_by"])
    actor.pop("role")
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="shape"):
        decode_account_owner_assignment_evidence_v5(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["blocker_codes"] = tuple(cast(list[object], payload["blocker_codes"]))
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="list|mapping"):
        decode_account_owner_assignment_evidence_v5(payload)


def test_v5_codec_rejects_nested_subject_tampering() -> None:
    """SubjectV5 version, source graph, and sealed hashes remain fail-closed."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    subject = cast(dict[str, object], payload["subject"])
    subject["schema"] = "account-owner-assignment-subject.v4"
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="invalid|fixed"):
        decode_account_owner_assignment_evidence_v5(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    subject = cast(dict[str, object], payload["subject"])
    subject["content_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="invalid|hash|seal"):
        decode_account_owner_assignment_evidence_v5(payload)

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    subject = cast(dict[str, object], payload["subject"])
    receipt = cast(dict[str, object], subject["receipt"])
    receipt["schema"] = "account-owner-assignment-provenance-receipt.v4"
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="invalid|receipt"):
        decode_account_owner_assignment_evidence_v5(payload)


def test_v5_codec_rejects_noncanonical_datetime_objects() -> None:
    """Payload fields must be serialized clock text, never datetime objects."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["approved_at"] = datetime(2026, 8, 15, 14, 35, tzinfo=UTC)

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="clock|string"):
        decode_account_owner_assignment_evidence_v5(payload)


def test_v5_encoder_revalidates_tampered_domain_hashes_and_nested_subject() -> None:
    """Encoding re-runs Domain validation instead of trusting mutated frozen values."""

    evidence = _evidence()
    object.__setattr__(evidence, "content_hash", "0" * 64)
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="encode|invalid"):
        encode_account_owner_assignment_evidence_v5(evidence)

    evidence = _evidence()
    object.__setattr__(evidence.subject, "content_hash", "0" * 64)
    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="encode|invalid"):
        encode_account_owner_assignment_evidence_v5(evidence)


def test_v5_codec_does_not_accept_noncanonical_payload_roundtrip() -> None:
    """A validly typed but semantically substituted fixed field is rejected."""

    payload = _copy(encode_account_owner_assignment_evidence_v5(_evidence()))
    payload["status"] = "active"

    with pytest.raises(AccountOwnerAssignmentEvidenceV5CodecError, match="invalid|fixed"):
        decode_account_owner_assignment_evidence_v5(payload)
