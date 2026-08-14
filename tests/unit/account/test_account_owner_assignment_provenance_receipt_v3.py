from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
    resolve_account_owner_assignment_provenance_receipt_v3_head,
    validate_account_owner_assignment_provenance_receipt_v3_binding,
    validate_account_owner_assignment_provenance_receipt_v3_root,
    validate_account_owner_assignment_provenance_receipt_v3_successor,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationBinding
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def _receipt(
    binding: CanonicalAccountCreationBindingV2 | None = None, **changes: object
) -> AccountOwnerAssignmentProvenanceReceiptV3:
    value = binding or _binding()
    allocation = value.allocation
    root = value.creation_root
    physical = root.physical_observation
    values: dict[str, object] = {
        "receipt_id": "creation-claim-7",
        "receipt_version": "v3.1",
        "binding": value,
        "account_namespace": value.account_namespace_claim,
        "account_id": value.account_id_claim,
        "underlying_unified_account_namespace": value.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id": value.underlying_unified_account_id_claim,
        "allocation_identity_hash": allocation.identity_hash,
        "allocation_content_hash": allocation.content_hash,
        "creation_root_identity_hash": root.identity_hash,
        "creation_root_content_hash": root.content_hash,
        "binding_identity_hash": value.identity_hash,
        "binding_content_hash": value.content_hash,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "physical_observation_content_hash": physical.content_hash,
        "physical_source_content_hash": physical.source_content_hash,
        "physical_raw_observation_content_hash": physical.raw_observation_content_hash,
        "assigned_owner_user_id": allocation.requested_row_user_id,
        "claimant": AccountOwnerAssignmentActor("human-42", 42, "account_owner_claimant"),
        "issued_at": _at(8, 13),
        "recorded_at": _at(8, 14),
        "valid_until": _at(13),
    }
    values.update(changes)
    return AccountOwnerAssignmentProvenanceReceiptV3(**values)  # type: ignore[arg-type]


def test_v3_is_creation_claim_only_inactive_frozen_and_non_executable() -> None:
    receipt = _receipt()
    assert receipt.provenance_kind == "creation"
    assert receipt.assignment_state == "claimed_owner"
    assert receipt.permission == "claim_evidence_only"
    assert receipt.status == "inactive"
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True
    assert not hasattr(receipt, "__dict__")
    with pytest.raises(FrozenInstanceError):
        receipt.status = "active"  # type: ignore[misc]
    for changes in (
        {"provenance_kind": "manual_reclaim"},
        {"provenance_kind": "migration"},
        {"permission": "execution_eligible"},
        {"status": "active"},
        {"blocker_codes": ()},
    ):
        with pytest.raises(ValueError, match="fixed"):
            _receipt(**changes)


def test_creation_claimant_equals_allocation_requester_and_physical_row_user() -> None:
    receipt = _receipt()
    assert (
        receipt.claimant.user_id
        == receipt.binding.allocation.requested_row_user_id
        == receipt.binding.creation_root.physical_observation.row_user_id
    )
    with pytest.raises(ValueError, match="claimant"):
        _receipt(
            claimant=AccountOwnerAssignmentActor("human-7", 7, "account_owner_claimant"),
            assigned_owner_user_id=7,
        )
    with pytest.raises(ValueError, match="non-staff"):
        _receipt(
            claimant=AccountOwnerAssignmentActor(
                "staff-42", 42, "account_owner_claimant", is_staff=True
            )
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "allocation_identity_hash",
        "allocation_content_hash",
        "creation_root_identity_hash",
        "creation_root_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "physical_observation_content_hash",
        "physical_source_content_hash",
        "physical_raw_observation_content_hash",
    ],
)
def test_exact_binding_v2_and_all_hash_seals_fail_closed(field_name: str) -> None:
    binding = _binding()
    receipt = _receipt(binding)
    validate_account_owner_assignment_provenance_receipt_v3_binding(receipt, binding)
    with pytest.raises(ValueError, match="exact canonical Binding v2"):
        _receipt(**{field_name: "0" * 64})
    with pytest.raises(TypeError, match="BindingV2"):
        replace(
            receipt,
            binding=cast(CanonicalAccountCreationBindingV2, object()),
            identity_hash="",
            content_hash="",
        )
    assert CanonicalAccountCreationBinding is not CanonicalAccountCreationBindingV2


def test_account_underlying_and_clock_validity_are_exact() -> None:
    for changes in (
        {"account_id": "other"},
        {"underlying_unified_account_id": 999},
        {"issued_at": _at(8, 11)},
        {"recorded_at": _at(14)},
        {"valid_until": _at(15)},
        {"recorded_at": datetime(2026, 8, 8, 14)},
    ):
        with pytest.raises((TypeError, ValueError)):
            _receipt(**changes)


def test_successor_and_pit_resolution_never_fall_back() -> None:
    first = _receipt(valid_until=_at(11))
    validate_account_owner_assignment_provenance_receipt_v3_root(first)
    second = replace(
        first,
        receipt_version="v3.2",
        issued_at=_at(9),
        recorded_at=_at(10),
        valid_until=_at(12),
        supersedes_content_hash=first.content_hash,
        identity_hash="",
        content_hash="",
    )
    validate_account_owner_assignment_provenance_receipt_v3_successor(first, second)
    assert (
        resolve_account_owner_assignment_provenance_receipt_v3_head((first, second), as_of=_at(10))
        is second
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v3_head((first, second), as_of=_at(12))
        is None
    )
    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_provenance_receipt_v3_root(second)
    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_provenance_receipt_v3_successor(
            first, replace(second, supersedes_content_hash="0" * 64, content_hash="")
        )


def test_domain_does_not_import_prior_receipt_or_binding_v1() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "account_owner_assignment_provenance_receipt_v3.py"
    )
    imported_modules = {
        node.module
        for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert (
        "apps.account.domain.account_owner_assignment_provenance_receipt_v2" not in imported_modules
    )
    assert "apps.account.domain.canonical_account_creation" not in imported_modules
