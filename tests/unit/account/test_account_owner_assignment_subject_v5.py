from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_SCHEMA,
    AccountOwnerAssignmentSubjectV5,
    validate_account_owner_assignment_subject_v5_root,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v5 import (
    _receipt,
)
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import (
    _binding as _reobservation_binding,
)


def _at(
    day: int,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, microsecond, tzinfo=UTC)


def _subject(
    receipt: AccountOwnerAssignmentProvenanceReceiptV5 | None = None,
    **changes: object,
) -> AccountOwnerAssignmentSubjectV5:
    value = receipt or _receipt()
    binding = value.binding
    reobservation = value.reobservation
    current = reobservation.current_physical
    values: dict[str, object] = {
        "subject_id": "ownership-subject-v5-7",
        "subject_version": "v5.1",
        "receipt": value,
        "binding": binding,
        "reobservation": reobservation,
        "receipt_identity_hash": value.identity_hash,
        "receipt_content_hash": value.content_hash,
        "policy_identity_hash": value.policy.identity_hash,
        "policy_content_hash": value.policy.content_hash,
        "binding_identity_hash": binding.identity_hash,
        "binding_content_hash": binding.content_hash,
        "allocation_identity_hash": binding.allocation.identity_hash,
        "allocation_content_hash": binding.allocation.content_hash,
        "account_claim_hash": binding.account_claim_hash,
        "underlying_claim_hash": binding.underlying_claim_hash,
        "reobservation_identity_hash": reobservation.identity_hash,
        "reobservation_content_hash": reobservation.content_hash,
        "current_physical_observation_content_hash": current.content_hash,
        "current_physical_source_content_hash": current.source_content_hash,
        "current_physical_raw_observation_content_hash": current.raw_observation_content_hash,
        "requested_at": value.recorded_at + timedelta(minutes=30),
        "valid_until": value.recorded_at + timedelta(hours=1),
    }
    values.update(changes)
    return AccountOwnerAssignmentSubjectV5(**values)  # type: ignore[arg-type]


def test_v5_subject_accepts_expired_old_root_and_current_reobservation() -> None:
    subject = _subject()
    payload = subject.to_payload()
    upstream_minimum = min(
        subject.receipt.valid_until,
        subject.policy.valid_until,
        subject.reobservation.valid_until,
    )

    assert subject.binding.creation_root.is_knowable_at(_at(15)) is False
    assert subject.binding.is_knowable_at(_at(15)) is True
    assert subject.reobservation.is_current_at(subject.requested_at) is True
    assert subject.owner == "account"
    assert subject.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_ARTIFACT_TYPE
    assert subject.schema == ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_SCHEMA
    assert subject.policy == subject.receipt.policy
    assert subject.claimant == subject.receipt.claimant
    assert subject.valid_until < upstream_minimum
    assert subject.is_knowable_at(subject.requested_at) is True
    assert subject.is_current_at(subject.requested_at) is True
    assert subject.is_current_at(subject.valid_until) is False
    assert subject.activation_available is False
    assert subject.must_not_execute is True
    assert not hasattr(subject, "__dict__")
    assert payload["receipt"] == subject.receipt.to_payload()
    assert payload["binding"] == subject.binding.to_payload()
    assert payload["reobservation"] == subject.reobservation.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
    assert len(subject.identity_hash) == len(subject.content_hash) == 64

    validate_account_owner_assignment_subject_v5_root(subject)

    with pytest.raises(FrozenInstanceError):
        subject.subject_version = "v5.2"  # type: ignore[misc]


def test_v5_subject_has_closed_fields_and_distinct_versioned_hashes() -> None:
    assert {field.name for field in fields(AccountOwnerAssignmentSubjectV5)} == {
        "subject_id",
        "subject_version",
        "receipt",
        "binding",
        "reobservation",
        "receipt_identity_hash",
        "receipt_content_hash",
        "policy_identity_hash",
        "policy_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "allocation_identity_hash",
        "allocation_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "reobservation_identity_hash",
        "reobservation_content_hash",
        "current_physical_observation_content_hash",
        "current_physical_source_content_hash",
        "current_physical_raw_observation_content_hash",
        "requested_at",
        "valid_until",
        "identity_hash",
        "content_hash",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "status",
        "blocker_codes",
    }
    subject = _subject()
    assert subject.identity_hash != subject.content_hash
    assert subject.identity_hash != subject.receipt.identity_hash
    assert subject.content_hash != subject.receipt.content_hash


@pytest.mark.parametrize(
    "field_name",
    [
        "receipt_identity_hash",
        "receipt_content_hash",
        "policy_identity_hash",
        "policy_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "allocation_identity_hash",
        "allocation_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "reobservation_identity_hash",
        "reobservation_content_hash",
        "current_physical_observation_content_hash",
        "current_physical_source_content_hash",
        "current_physical_raw_observation_content_hash",
    ],
)
def test_v5_subject_rejects_each_replaced_upstream_seal(field_name: str) -> None:
    with pytest.raises(ValueError):
        _subject(**{field_name: "0" * 64})


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("subject_id", True, "exact string"),
        ("subject_id", "bad subject token", "bounded canonical token"),
        ("receipt_identity_hash", True, "exact string"),
        ("receipt_identity_hash", "g" * 64, "lowercase SHA-256"),
        ("blocker_codes", ["other"], "exact tuple"),
        ("identity_hash", True, "exact string"),
        ("identity_hash", "a" * 64, "identity_hash is invalid"),
    ],
)
def test_v5_subject_rejects_primitive_and_own_hash_substitution(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _subject(**{field_name: value})


def test_v5_subject_rejects_replaced_binding_and_reobservation() -> None:
    subject = _subject()
    alternate_binding = _reobservation_binding(
        root=subject.binding.creation_root,
        recorded_at=subject.binding.recorded_at,
        binding_id="different-binding-v5-subject",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(ValueError, match="Binding"):
        _subject(binding=alternate_binding)

    alternate_reobservation = replace(
        subject.reobservation,
        observation_id="different-reobservation-v5-subject",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(ValueError, match="reobservation"):
        _subject(reobservation=alternate_reobservation)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("owner", "simulated_trading", "fixed"),
        ("artifact_type", "account_owner_assignment_subject_v4", "fixed"),
        ("schema", "account-owner-assignment-subject.v4", "fixed"),
        ("permission", "execute", "fixed"),
        ("status", "active", "fixed"),
        ("owner", True, "exact string"),
        ("blocker_codes", ("other",), "fixed"),
    ],
)
def test_v5_subject_fixed_semantics_are_not_reinterpretable(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _subject(**{field_name: value})


def test_v5_subject_rejects_future_request_or_validity_beyond_current_sources() -> None:
    with pytest.raises(ValueError, match="clock"):
        _subject(requested_at=_at(15, 13, 59))
    with pytest.raises(ValueError, match="current receipt"):
        _subject(requested_at=_at(16, 13), valid_until=_at(16, 14))
    with pytest.raises(ValueError, match="validity"):
        _subject(valid_until=_at(16, 12, 0, 0, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        _subject(requested_at=datetime(2026, 8, 15, 14, 30))


def test_v5_subject_revalidates_nested_row_and_old_payloads_remain_unchanged() -> None:
    subject = _subject()
    binding_payload = subject.binding.to_payload()
    reobservation_payload = subject.reobservation.to_payload()

    object.__setattr__(subject.reobservation.current_physical, "raw_account_type", "PAPER")
    with pytest.raises(ValueError):
        subject.to_payload()
    assert subject.binding.to_payload() == binding_payload
    with pytest.raises(ValueError):
        subject.reobservation.to_payload()
    assert reobservation_payload["schema"] == "canonical-account-ownership-reobservation.v1"


def test_v5_subject_requires_exact_nested_runtime_types_and_aware_cutoffs() -> None:
    subject = _subject()
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentProvenanceReceiptV5"):
        replace(
            subject,
            receipt=cast(AccountOwnerAssignmentProvenanceReceiptV5, object()),
            identity_hash="",
            content_hash="",
        )
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationBindingV2"):
        replace(
            subject,
            binding=cast(CanonicalAccountCreationBindingV2, object()),
            identity_hash="",
            content_hash="",
        )
    with pytest.raises(TypeError, match="exact CanonicalAccountOwnershipReobservationV1"):
        replace(
            subject,
            reobservation=cast(CanonicalAccountOwnershipReobservationV1, object()),
            identity_hash="",
            content_hash="",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        _subject().is_current_at(datetime(2026, 8, 15, 14, 30))

    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentSubjectV5"):
        validate_account_owner_assignment_subject_v5_root(
            cast(AccountOwnerAssignmentSubjectV5, object())
        )


def test_v5_subject_domain_imports_do_not_cross_into_frameworks_or_v4() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "account_owner_assignment_subject_v5.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
    assert "apps.account.domain.account_owner_assignment_evidence_v4" not in imports
    assert imports <= {
        "__future__",
        "apps.account.domain.account_owner_assignment_evidence",
        "apps.account.domain.account_owner_assignment_provenance_receipt_v5",
        "apps.account.domain.canonical_account_creation_binding_v2",
        "apps.account.domain.canonical_account_ownership_reobservation_v1",
        "apps.account.domain.single_owner_authority_policy_v1",
        "apps.account.domain.validation_graph",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
