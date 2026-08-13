from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
    CanonicalAccountCreationRequester,
    CanonicalAccountCreationServiceRecorder,
    resolve_canonical_account_creation_binding,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _requester(**changes: object) -> CanonicalAccountCreationRequester:
    values: dict[str, object] = {
        "actor_id": "user-42",
        "user_id": 42,
        "role": "account_creator",
    }
    values.update(changes)
    return CanonicalAccountCreationRequester(**values)  # type: ignore[arg-type]


def _allocation(**changes: object) -> CanonicalAccountCreationAllocation:
    values: dict[str, object] = {
        "allocation_id": "allocation-7",
        "allocation_version": "v1",
        "canonical_account_namespace": "account",
        "canonical_account_id": "acct-0007",
        "requested_row_user_id": 42,
        "requested_raw_account_type": "SIMULATED",
        "intended_underlying_unified_account_namespace": "simulated-account-row",
        "request_fingerprint_hash": "a" * 64,
        "requested_by": _requester(),
        "allocated_at": _at(1),
        "valid_until": _at(20),
    }
    values.update(changes)
    return CanonicalAccountCreationAllocation(**values)  # type: ignore[arg-type]


def _physical(**changes: object) -> PhysicalAccountRowObservationV2:
    physical_changes = dict(changes)
    raw_is_active = physical_changes.pop("is_active", True)
    raw = SimulatedAccountRawObservation(
        observation_id="simulated-account-row-7",
        observation_version="event-v1",
        row_pk=7,
        row_user_id=42,
        raw_account_type="SIMULATED",
        is_active=raw_is_active,  # type: ignore[arg-type]
        row_created_at=_at(2),
        row_updated_at=_at(3),
        is_present=True,
        is_tombstone=False,
        observed_at=_at(4),
        valid_until=_at(18),
    )
    source = SimulatedAccountRowSourceV2(
        source_id=raw.observation_id,
        source_version=raw.observation_version,
        account_namespace="account",
        account_id="acct-0007",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=raw.row_pk,
        row_user_id=raw.row_user_id,
        raw_account_type=raw.raw_account_type,
        is_active=raw.is_active,
        row_created_at=raw.row_created_at,
        row_updated_at=raw.row_updated_at,
        is_present=raw.is_present,
        is_tombstone=raw.is_tombstone,
        observed_at=raw.observed_at,
        recorded_at=_at(5),
        source_valid_until=raw.valid_until,
        ttl_valid_until=_at(16),
        valid_until=_at(16),
        raw_observation_id=raw.observation_id,
        raw_observation_version=raw.observation_version,
        raw_observation_identity_hash=raw.identity_hash,
        raw_observation_content_hash=raw.content_hash,
        raw_observation_observed_at=raw.observed_at,
        raw_observation_valid_until=raw.valid_until,
    )
    values: dict[str, object] = {
        "observation_id": "physical-row-7",
        "observation_version": "capture-v1",
        "account_namespace": source.account_namespace,
        "account_id": source.account_id,
        "underlying_unified_account_namespace": source.underlying_unified_account_namespace,
        "underlying_unified_account_id": source.underlying_unified_account_id,
        "row_user_id": source.row_user_id,
        "raw_account_type": source.raw_account_type,
        "is_active": source.is_active,
        "row_created_at": source.row_created_at,
        "row_updated_at": source.row_updated_at,
        "is_present": source.is_present,
        "is_tombstone": source.is_tombstone,
        "source_id": source.source_id,
        "source_version": source.source_version,
        "source_identity_hash": source.identity_hash,
        "source_content_hash": source.content_hash,
        "source_supersedes_content_hash": None,
        "source_observed_at": source.observed_at,
        "source_recorded_at": source.recorded_at,
        "source_valid_until": source.source_valid_until,
        "source_ttl_valid_until": source.ttl_valid_until,
        "source_effective_valid_until": source.valid_until,
        "raw_observation_id": source.raw_observation_id,
        "raw_observation_version": source.raw_observation_version,
        "raw_observation_identity_hash": source.raw_observation_identity_hash,
        "raw_observation_content_hash": source.raw_observation_content_hash,
        "raw_observation_supersedes_content_hash": None,
        "raw_observation_observed_at": source.raw_observation_observed_at,
        "raw_observation_valid_until": source.raw_observation_valid_until,
        "recorded_at": _at(6),
        "ttl_valid_until": _at(15),
        "valid_until": _at(15),
    }
    values.update(physical_changes)
    return PhysicalAccountRowObservationV2(**values)  # type: ignore[arg-type]


def _binding(**changes: object) -> CanonicalAccountCreationBinding:
    values: dict[str, object] = {
        "binding_id": "binding-7",
        "binding_version": "v1",
        "allocation": _allocation(),
        "physical_observation": _physical(),
        "account_namespace_claim": "account",
        "account_id_claim": "acct-0007",
        "underlying_unified_account_namespace_claim": "simulated-account-row",
        "underlying_unified_account_id_claim": 7,
        "recorded_by": CanonicalAccountCreationServiceRecorder(
            service_id="account-creation-binder",
            role="canonical_account_creation_binder",
        ),
        "recorded_at": _at(7),
        "valid_until": _at(15),
    }
    values.update(changes)
    return CanonicalAccountCreationBinding(**values)  # type: ignore[arg-type]


def test_self_service_allocation_is_fixed_hash_sealed_and_non_executable() -> None:
    allocation = _allocation()

    assert allocation.requested_by.user_id == allocation.requested_row_user_id
    assert allocation.permission == "identity_allocation_only"
    assert allocation.status == "inactive"
    assert allocation.must_not_execute is True
    assert allocation.activation_available is False
    assert len(allocation.identity_hash) == len(allocation.content_hash) == 64
    assert not hasattr(allocation, "underlying_unified_account_id")
    with pytest.raises(FrozenInstanceError):
        allocation.canonical_account_id = "acct-8"  # type: ignore[misc]
    with pytest.raises(ValueError, match="requester"):
        _allocation(requested_row_user_id=43)
    with pytest.raises(ValueError, match="human account_creator"):
        _requester(role="admin")
    with pytest.raises(ValueError, match="timezone-aware"):
        _allocation(allocated_at=datetime(2026, 8, 1, 12))


def test_binding_revalidates_full_roots_and_dual_claims_without_authority() -> None:
    binding = _binding()

    assert binding.permission == "identity_binding_evidence_only"
    assert binding.status == "inactive"
    assert binding.binding_state == "pending_owner_approval"
    assert binding.owner_assignment_state == "unknown"
    assert binding.must_not_execute is True
    assert binding.activation_available is False
    assert len(binding.content_hash) == 64

    for changes, message in (
        ({"account_id_claim": "acct-8"}, "account claim"),
        ({"underlying_unified_account_id_claim": 8}, "underlying claim"),
        ({"recorded_at": _at(20)}, "allocation"),
        ({"valid_until": _at(14)}, "minimum"),
    ):
        with pytest.raises(ValueError, match=message):
            _binding(**changes)
    with pytest.raises(ValueError, match="physical live root"):
        _binding(physical_observation=_physical(is_active=False))
    with pytest.raises(ValueError, match="user"):
        _binding(
            allocation=_allocation(requested_row_user_id=43, requested_by=_requester(user_id=43))
        )
    with pytest.raises(ValueError, match="type"):
        _binding(allocation=_allocation(requested_raw_account_type="PAPER"))
    with pytest.raises(ValueError, match="root"):
        _binding(physical_observation=_physical(supersedes_content_hash="a" * 64))


def test_binding_pit_has_no_expiry_fallback_or_execution_transition() -> None:
    binding = _binding()

    assert resolve_canonical_account_creation_binding(binding, as_of=_at(8)) is binding
    assert resolve_canonical_account_creation_binding(binding, as_of=_at(6)) is None
    assert resolve_canonical_account_creation_binding(binding, as_of=_at(15)) is None


def test_supplied_hashes_and_tampering_are_revalidated() -> None:
    allocation = _allocation()
    assert _allocation(content_hash=allocation.content_hash) == allocation
    with pytest.raises(ValueError, match="content_hash"):
        _allocation(content_hash="a" * 64)

    binding = _binding()
    object.__setattr__(binding.allocation, "canonical_account_id", "acct-8")
    with pytest.raises(ValueError):
        binding.to_payload()


def test_production_module_has_no_cross_app_or_framework_imports() -> None:
    source_path = (
        Path(__file__).parents[3] / "apps" / "account" / "domain" / "canonical_account_creation.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(
        name.startswith("apps.") and not name.startswith("apps.account.") for name in imports
    )
    assert not any(name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
