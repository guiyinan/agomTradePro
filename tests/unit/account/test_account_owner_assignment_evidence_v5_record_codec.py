"""Unit contracts for the strict EvidenceV5 persisted record codec."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    PersistedAccountOwnerAssignmentEvidenceV5,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_record_codec import (
    encode_account_owner_assignment_evidence_v4_record,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_record_codec import (
    AccountOwnerAssignmentEvidenceV5RecordCodecError,
    decode_account_owner_assignment_evidence_v5_record,
    encode_account_owner_assignment_evidence_v5_record,
)
from tests.unit.account.test_account_owner_assignment_evidence_v4_record_codec import (
    _record as _v4_record,
)
from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence


def _record() -> PersistedAccountOwnerAssignmentEvidenceV5:
    """Build one complete V5 evidence record with a real staff authority fact."""

    evidence = _evidence()
    approved_by = evidence.approved_by
    authority = CurrentAccountActorAuthorityV3(
        principal_id="test-principal-v5",
        user_id=approved_by.user_id,
        authentication_context_hash="b" * 64,
        actor_id=approved_by.actor_id,
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        source_id="test-source-v5",
        source_version="v5",
        source_content_hash="c" * 64,
        recorded_at=evidence.approved_at - timedelta(seconds=1),
        valid_until=evidence.approval_valid_until,
    )
    return PersistedAccountOwnerAssignmentEvidenceV5(
        evidence=evidence,
        authority=authority,
    )


def _section(payload: dict[str, object], name: str) -> dict[str, object]:
    """Return one mutable payload section for an intentional tamper test."""

    value = payload[name]
    assert type(value) is dict
    return cast(dict[str, object], value)


def test_record_json_roundtrip_preserves_full_v5_evidence_and_authority() -> None:
    """JSON transport retains nested EvidenceV5 and all authority source facts."""

    record = _record()
    payload = encode_account_owner_assignment_evidence_v5_record(record)

    assert decode_account_owner_assignment_evidence_v5_record(payload) == record
    assert set(payload) == {"evidence", "authority"}
    assert set(_section(payload, "authority")) == {
        "principal_id",
        "user_id",
        "authentication_context_hash",
        "actor_id",
        "is_authenticated",
        "is_active",
        "is_staff",
        "is_superuser",
        "rbac_role",
        "source_id",
        "source_version",
        "source_content_hash",
        "recorded_at",
        "valid_until",
    }
    assert _section(payload, "evidence")["schema"] == record.evidence.schema
    assert _section(payload, "authority")["recorded_at"] == ("2026-08-15T14:34:59.000000Z")


@pytest.mark.parametrize("section", [None, "evidence", "authority"])
def test_record_rejects_extra_keys_at_each_closed_world_boundary(
    section: str | None,
) -> None:
    """No envelope or nested section may silently carry unknown fields."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    target = payload if section is None else _section(payload, section)
    target["unexpected"] = "value"

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)


@pytest.mark.parametrize("section", ["evidence", "authority"])
def test_record_rejects_missing_required_boundary(section: str) -> None:
    """Removing either authenticated half must fail closed."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    payload.pop(section)

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", True),
        ("user_id", 991),
        ("actor_id", "different-actor"),
        ("is_staff", False),
        ("is_staff", 1),
        ("is_authenticated", False),
        ("is_active", False),
        ("is_authenticated", 1),
        ("rbac_role", "user"),
        ("authentication_context_hash", ""),
        ("source_content_hash", "z" * 64),
        ("source_id", ""),
        ("recorded_at", "2026-08-15T14:34:59+00:00"),
        ("recorded_at", "2026-08-15T14:34:59Z"),
        ("recorded_at", "2026-08-15T16:00:00.000000Z"),
        ("valid_until", "2026-08-15T15:30:00+00:00"),
        ("valid_until", "2026-08-15T15:29:59.000000Z"),
    ],
)
def test_record_rejects_authority_type_and_clock_substitution(
    field: str,
    value: object,
) -> None:
    """Authority type, source facts, and clocks cannot be coerced or replaced."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    _section(payload, "authority")[field] = value

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_active", 1),
        ("is_authenticated", "true"),
        ("is_staff", "true"),
        ("is_superuser", 1),
    ],
)
def test_record_rejects_non_boolean_authority_flags(field: str, value: object) -> None:
    """Integer or textual truthiness cannot bypass exact authority typing."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    _section(payload, "authority")[field] = value

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)


def test_record_rejects_blank_or_cross_version_nested_evidence() -> None:
    """Nested V5 seals and schema/version boundaries remain closed world."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    evidence_payload = _section(payload, "evidence")
    evidence_payload["content_hash"] = ""
    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    evidence_payload = _section(payload, "evidence")
    evidence_payload["schema"] = "account-owner-assignment-evidence.v4"
    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    v4_payload = encode_account_owner_assignment_evidence_v4_record(_v4_record())
    payload["evidence"] = v4_payload["evidence"]
    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)


def test_record_rejects_permission_and_nested_hash_tampering() -> None:
    """Evidence-only semantics and upstream content seals remain immutable."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    _section(payload, "evidence")["permission"] = "execution_eligible"
    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    _section(payload, "evidence")["identity_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v5_record(_record()))
    subject = _section(_section(payload, "evidence"), "subject")
    subject["reobservation_content_hash"] = "1" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)


def test_encoder_revalidates_mutated_frozen_authority_and_evidence() -> None:
    """Encoding re-runs DTO validation instead of trusting mutated frozen values."""

    record = _record()
    object.__setattr__(record.authority, "is_active", False)

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        encode_account_owner_assignment_evidence_v5_record(record)

    record = _record()
    object.__setattr__(record.evidence, "identity_hash", "0" * 64)

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        encode_account_owner_assignment_evidence_v5_record(record)


def test_encoder_requires_exact_persisted_record_type() -> None:
    """A Domain evidence value cannot be mistaken for its authenticated record."""

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        encode_account_owner_assignment_evidence_v5_record(cast(object, _evidence()))


def test_record_rejects_noncanonical_json_nested_mapping() -> None:
    """A JSON object with a noncanonical nested timestamp cannot bypass validation."""

    payload = encode_account_owner_assignment_evidence_v5_record(_record())
    payload["evidence"] = cast(dict[str, object], payload["evidence"])
    cast(dict[str, object], payload["evidence"])["approved_at"] = "2026-08-15T14:35:00+00:00"

    with pytest.raises(AccountOwnerAssignmentEvidenceV5RecordCodecError):
        decode_account_owner_assignment_evidence_v5_record(payload)
