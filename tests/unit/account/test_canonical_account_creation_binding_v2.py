from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
    resolve_canonical_account_creation_binding_v2,
)
from tests.unit.account.test_allocated_physical_account_row_observation_v3 import (
    _root,
)
from tests.unit.account.test_canonical_account_creation import _allocation


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def _binding(**changes: object) -> CanonicalAccountCreationBindingV2:
    root = _root()
    physical = root.physical_observation
    values: dict[str, object] = {
        "binding_id": "durable-binding-7",
        "binding_version": "v2",
        "allocation": root.allocation,
        "creation_root": root,
        "account_namespace_claim": physical.account_namespace,
        "account_id_claim": physical.account_id,
        "underlying_unified_account_namespace_claim": (
            physical.underlying_unified_account_namespace
        ),
        "underlying_unified_account_id_claim": (physical.underlying_unified_account_id),
        "creation_root_identity_hash": root.identity_hash,
        "creation_root_content_hash": root.content_hash,
        "physical_observation_content_hash": physical.content_hash,
        "physical_source_content_hash": physical.source_content_hash,
        "physical_raw_observation_content_hash": (physical.raw_observation_content_hash),
        "recorded_by": CanonicalAccountCreationServiceRecorder(
            service_id="account-creation-binder-v2",
            role="canonical_account_creation_binder",
        ),
        "recorded_at": _at(8),
    }
    values.update(changes)
    return CanonicalAccountCreationBindingV2(**values)  # type: ignore[arg-type]


def test_durable_binding_is_fixed_frozen_and_has_no_expiry_or_successor_fields() -> None:
    binding = _binding()
    field_names = {field.name for field in fields(CanonicalAccountCreationBindingV2)}

    assert "valid_until" not in field_names
    assert "ttl_valid_until" not in field_names
    assert not any("supersedes" in field_name for field_name in field_names)
    assert binding.owner == "account"
    assert binding.artifact_type == "canonical_account_creation_binding_v2"
    assert binding.schema == "canonical-account-creation-binding.v2"
    assert binding.permission == "identity_binding_evidence_only"
    assert binding.status == "inactive"
    assert binding.binding_state == "bound_pending_owner_approval"
    assert binding.owner_assignment_state == "unknown"
    assert binding.activation_available is False
    assert binding.must_not_execute is True
    assert binding.mapping_reusable is False
    assert not hasattr(binding, "__dict__")
    with pytest.raises(FrozenInstanceError):
        binding.binding_version = "v3"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("owner", "simulated_trading"),
        ("artifact_type", "canonical_account_creation_binding"),
        ("schema", "canonical-account-creation-binding.v1"),
        ("permission", "execute"),
        ("status", "active"),
        ("binding_state", "approved"),
        ("owner_assignment_state", "assigned"),
    ],
)
def test_authority_and_pending_owner_approval_semantics_are_fixed(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="fixed"):
        _binding(**{field_name: value})


def test_binding_revalidates_exact_allocation_and_creation_root() -> None:
    root = _root(allocation=_allocation(allocation_id="allocation-8"))

    with pytest.raises(ValueError, match="exact allocation"):
        _binding(creation_root=root)
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationAllocation"):
        _binding(allocation=cast(object, {"allocation_id": "allocation-7"}))
    with pytest.raises(TypeError, match="exact AllocatedPhysicalAccountRowObservationV3"):
        _binding(creation_root=cast(object, {"observation_id": "root-7"}))


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("account_namespace_claim", "other", "account claim"),
        ("account_id_claim", "acct-0008", "account claim"),
        (
            "underlying_unified_account_namespace_claim",
            "other-row",
            "underlying claim",
        ),
        ("underlying_unified_account_id_claim", 8, "underlying claim"),
        ("creation_root_identity_hash", "a" * 64, "creation root identity"),
        ("creation_root_content_hash", "b" * 64, "creation root content"),
        (
            "physical_observation_content_hash",
            "c" * 64,
            "physical observation content",
        ),
        ("physical_source_content_hash", "d" * 64, "physical source content"),
        (
            "physical_raw_observation_content_hash",
            "e" * 64,
            "physical raw observation content",
        ),
    ],
)
def test_dual_mapping_claims_and_all_three_inner_hashes_are_exact(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _binding(**{field_name: value})


def test_user_type_and_nested_tampering_fail_closed() -> None:
    binding = _binding()
    object.__setattr__(binding.creation_root.allocation, "requested_row_user_id", 99)
    with pytest.raises(ValueError):
        binding.to_payload()

    binding = _binding()
    object.__setattr__(binding.creation_root.physical_observation, "raw_account_type", "PAPER")
    with pytest.raises(ValueError):
        binding.to_payload()


def test_recording_requires_both_inputs_live_but_mapping_never_expires() -> None:
    binding = _binding()

    with pytest.raises(ValueError, match="allocation.*valid"):
        _binding(recorded_at=_at(20))
    with pytest.raises(ValueError, match="creation root.*valid"):
        _binding(recorded_at=_at(14))
    with pytest.raises(ValueError, match="timezone-aware"):
        _binding(recorded_at=datetime(2026, 8, 8, 12))

    assert resolve_canonical_account_creation_binding_v2(binding, as_of=_at(7)) is None
    assert resolve_canonical_account_creation_binding_v2(binding, as_of=_at(8)) is binding
    assert resolve_canonical_account_creation_binding_v2(binding, as_of=_at(30)) is binding


def test_claim_hashes_are_domain_separated_and_full_payload_is_sealed() -> None:
    binding = _binding()
    payload = binding.to_payload()

    assert binding.account_claim_hash != binding.underlying_claim_hash
    assert len(binding.identity_hash) == len(binding.content_hash) == 64
    assert payload["allocation"]["content_hash"] == binding.allocation.content_hash  # type: ignore[index]
    assert payload["creation_root"] == binding.creation_root.to_payload()

    changed = _binding(recorded_at=_at(8, 13))
    assert changed.identity_hash == binding.identity_hash
    assert changed.content_hash != binding.content_hash
    with pytest.raises(ValueError, match="account_claim_hash"):
        _binding(account_claim_hash="a" * 64)
    with pytest.raises(ValueError, match="underlying_claim_hash"):
        _binding(underlying_claim_hash="b" * 64)


def test_supplied_hashes_and_equivalent_instants_are_canonical() -> None:
    binding = _binding()
    assert (
        _binding(identity_hash=binding.identity_hash, content_hash=binding.content_hash) == binding
    )
    with pytest.raises(ValueError, match="identity_hash"):
        _binding(identity_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _binding(content_hash="b" * 64)

    offset = timezone(timedelta(hours=8))
    equivalent = _binding(recorded_at=_at(8).astimezone(offset))
    assert equivalent.content_hash == binding.content_hash


def test_exact_runtime_types_and_as_of_fail_closed() -> None:
    binding = _binding()

    with pytest.raises(TypeError, match="exact CanonicalAccountCreationBindingV2"):
        resolve_canonical_account_creation_binding_v2(
            cast(CanonicalAccountCreationBindingV2, object()),
            as_of=_at(8),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_canonical_account_creation_binding_v2(
            binding,
            as_of=datetime(2026, 8, 8, 12),
        )


def test_domain_module_has_only_standard_library_and_same_app_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "canonical_account_creation_binding_v2.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(
        name.startswith("apps.") and not name.startswith("apps.account.domain.") for name in imports
    )
    assert imports <= {
        "__future__",
        "apps.account.domain.allocated_physical_account_row_observation_v3",
        "apps.account.domain.canonical_account_creation",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
