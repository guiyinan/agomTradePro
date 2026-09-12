"""Strict authenticated record codec tests for Account evidence v4."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    PersistedAccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_codec import (
    encode_account_owner_assignment_evidence_v3,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_record_codec import (
    AccountOwnerAssignmentEvidenceV4RecordCodecError,
    decode_account_owner_assignment_evidence_v4_record,
    encode_account_owner_assignment_evidence_v4_record,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence as _v3_evidence
from tests.unit.account.test_account_owner_assignment_evidence_v4 import _evidence


def _record() -> PersistedAccountOwnerAssignmentEvidenceV4:
    """Build one complete v4 evidence record with a real staff authority fact."""

    evidence = _evidence()
    approved_by = evidence.approved_by
    authority = CurrentAccountActorAuthorityV3(
        principal_id="test-principal",
        user_id=approved_by.user_id,
        authentication_context_hash="b" * 64,
        actor_id=approved_by.actor_id,
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        source_id="test-source",
        source_version="1",
        source_content_hash="c" * 64,
        recorded_at=evidence.approved_at - timedelta(seconds=1),
        valid_until=evidence.approval_valid_until,
    )
    return PersistedAccountOwnerAssignmentEvidenceV4(
        evidence=evidence,
        authority=authority,
    )


def _section(payload: dict[str, object], name: str) -> dict[str, object]:
    """Return one mutable payload section for an intentional tamper test."""

    value = payload[name]
    assert type(value) is dict
    return cast(dict[str, object], value)


def test_record_json_roundtrip_preserves_full_evidence_and_authority() -> None:
    """JSON transport must retain both nested evidence and all source facts."""

    record = _record()
    payload = json.loads(json.dumps(encode_account_owner_assignment_evidence_v4_record(record)))

    assert decode_account_owner_assignment_evidence_v4_record(payload) == record
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
    assert _section(payload, "authority")["recorded_at"] == ("2026-08-08T15:59:59.000000Z")


@pytest.mark.parametrize("section", [None, "evidence", "authority"])
def test_record_rejects_extra_keys_at_each_closed_world_boundary(
    section: str | None,
) -> None:
    """No envelope or nested section may silently carry unknown fields."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    target = payload if section is None else _section(payload, section)
    target["unexpected"] = "value"

    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)


@pytest.mark.parametrize("section", ["evidence", "authority"])
def test_record_rejects_missing_required_boundary(section: str) -> None:
    """Removing either authenticated half must fail closed."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    if section == "authority":
        payload.pop("authority")
    else:
        payload.pop("evidence")

    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)


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
        ("recorded_at", "2026-08-08T15:59:59+00:00"),
        ("recorded_at", "2026-08-08T15:59:59Z"),
        ("recorded_at", "2026-08-08T17:00:00.000000Z"),
        ("valid_until", "2026-08-13T12:00:00+00:00"),
        ("valid_until", "2026-08-13T11:59:59.000000Z"),
    ],
)
def test_record_rejects_actor_staff_permission_source_and_clock_substitution(
    field: str,
    value: object,
) -> None:
    """Authority type and cross-object facts must never be coerced or replaced."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    _section(payload, "authority")[field] = value

    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)


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

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    _section(payload, "authority")[field] = value

    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)


def test_record_rejects_blank_or_cross_version_nested_evidence() -> None:
    """Nested v4 seals and schema/version boundaries remain closed world."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    evidence_payload = _section(payload, "evidence")
    evidence_payload["content_hash"] = ""
    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    evidence_payload = _section(payload, "evidence")
    evidence_payload["schema"] = "account_owner_assignment_evidence_v3"
    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    payload["evidence"] = encode_account_owner_assignment_evidence_v3(_v3_evidence())
    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)


def test_record_rejects_permission_and_nested_hash_tampering() -> None:
    """Evidence-only semantics and upstream content seals cannot be relaxed."""

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    _section(payload, "evidence")["permission"] = "execution_eligible"
    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)

    payload = deepcopy(encode_account_owner_assignment_evidence_v4_record(_record()))
    _section(payload, "evidence")["identity_hash"] = "0" * 64
    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        decode_account_owner_assignment_evidence_v4_record(payload)


def test_encoder_revalidates_mutated_frozen_authority_and_dto() -> None:
    """Encoding re-runs DTO validation instead of trusting a mutated frozen object."""

    record = _record()
    object.__setattr__(record.authority, "is_active", False)

    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        encode_account_owner_assignment_evidence_v4_record(record)


def test_encoder_requires_exact_persisted_record_type() -> None:
    """A domain evidence value cannot be mistaken for its authenticated record."""

    evidence: AccountOwnerAssignmentEvidenceV4 = _evidence()

    with pytest.raises(AccountOwnerAssignmentEvidenceV4RecordCodecError):
        encode_account_owner_assignment_evidence_v4_record(evidence)  # type: ignore[arg-type]
