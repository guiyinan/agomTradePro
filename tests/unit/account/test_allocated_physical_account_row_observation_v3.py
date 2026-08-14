from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
    resolve_allocated_physical_account_row_observation_v3,
)
from tests.unit.account.test_canonical_account_creation import _allocation, _physical


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def _root(**changes: object) -> AllocatedPhysicalAccountRowObservationV3:
    values: dict[str, object] = {
        "observation_id": "allocated-physical-row-7",
        "observation_version": "creation-root-v1",
        "allocation": _allocation(),
        "physical_observation": _physical(),
        "recorded_at": _at(7),
        "ttl_valid_until": _at(14),
        "valid_until": _at(14),
    }
    values.update(changes)
    return AllocatedPhysicalAccountRowObservationV3(**values)  # type: ignore[arg-type]


def _physical_with_underlying_namespace(
    namespace: str,
) -> object:
    physical = _physical()
    object.__setattr__(physical, "underlying_unified_account_namespace", namespace)
    source_hash = hashlib.sha256(
        json.dumps(
            physical._source_content_payload(),  # noqa: SLF001
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    object.__setattr__(physical, "source_content_hash", source_hash)
    object.__setattr__(physical, "content_hash", "")
    physical.__post_init__()
    return physical


def test_creation_root_is_frozen_slotted_fixed_and_has_no_binding_header() -> None:
    root = _root()
    field_names = {field.name for field in fields(AllocatedPhysicalAccountRowObservationV3)}

    assert field_names == {
        "observation_id",
        "observation_version",
        "allocation",
        "physical_observation",
        "recorded_at",
        "ttl_valid_until",
        "valid_until",
        "identity_hash",
        "content_hash",
        "identity_anchor_kind",
        "owner_assignment_state",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "status",
    }
    assert not any("binding" in field_name for field_name in field_names)
    assert not hasattr(root, "__dict__")
    with pytest.raises(FrozenInstanceError):
        root.observation_version = "creation-root-v2"  # type: ignore[misc]
    assert root.owner == "account"
    assert root.artifact_type == "allocated_physical_account_row_observation_v3"
    assert root.schema == "allocated-physical-account-row-observation.v3"
    assert root.identity_anchor_kind == "creation_allocation"
    assert root.owner_assignment_state == "unknown"
    assert root.permission == "evidence_only"
    assert root.status == "inactive"
    assert root.activation_available is False
    assert root.must_not_execute is True


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("owner", "simulated_trading"),
        ("artifact_type", "physical_account_row_observation_v2"),
        ("schema", "allocated-physical-account-row-observation.v2"),
        ("identity_anchor_kind", "binding"),
        ("owner_assignment_state", "assigned"),
        ("permission", "execute"),
        ("status", "active"),
    ],
)
def test_authority_and_creation_anchor_semantics_are_fixed(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="fixed"):
        _root(**{field_name: value})


def test_full_nested_payload_and_hash_seal_allocation_and_physical_root() -> None:
    root = _root()
    payload = root.to_payload()

    assert payload["allocation"] == {
        **root.allocation.to_payload(),
        "identity_hash": root.allocation.identity_hash,
        "content_hash": root.allocation.content_hash,
    }
    assert payload["physical_observation"] == root.physical_observation.to_payload()
    assert len(root.identity_hash) == len(root.content_hash) == 64

    changed_allocation = _allocation(canonical_account_id="acct-0008")
    changed_physical = _physical(account_id="acct-0008")
    alternate = _root(
        allocation=changed_allocation,
        physical_observation=changed_physical,
    )
    assert alternate.identity_hash == root.identity_hash
    assert alternate.content_hash != root.content_hash


def test_nested_tampering_and_supplied_hash_substitution_fail_closed() -> None:
    root = _root()
    assert _root(identity_hash=root.identity_hash, content_hash=root.content_hash) == root
    with pytest.raises(ValueError, match="identity_hash"):
        _root(identity_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _root(content_hash="b" * 64)

    object.__setattr__(root.allocation, "canonical_account_id", "acct-forged")
    with pytest.raises(ValueError):
        root.to_payload()


@pytest.mark.parametrize(
    ("allocation_changes", "physical_changes", "message"),
    [
        ({"canonical_account_id": "acct-0008"}, {}, "account label"),
        ({"requested_row_user_id": 43}, {}, "row user"),
        ({"requested_raw_account_type": "PAPER"}, {}, "account type"),
        ({}, {"is_active": False}, "live physical root"),
    ],
)
def test_allocation_and_live_physical_root_must_match_exactly(
    allocation_changes: dict[str, object],
    physical_changes: dict[str, object],
    message: str,
) -> None:
    if "requested_row_user_id" in allocation_changes:
        requester = _allocation().requested_by
        object.__setattr__(requester, "user_id", 43)
        allocation_changes = {**allocation_changes, "requested_by": requester}
    with pytest.raises(ValueError, match=message):
        _root(
            allocation=_allocation(**allocation_changes),
            physical_observation=_physical(**physical_changes),
        )


def test_underlying_namespace_must_match_the_creation_allocation() -> None:
    with pytest.raises(ValueError, match="underlying namespace"):
        _root(physical_observation=_physical_with_underlying_namespace("other-row"))


@pytest.mark.parametrize(
    "predecessor_field",
    [
        "supersedes_content_hash",
        "source_supersedes_content_hash",
        "raw_observation_supersedes_content_hash",
    ],
)
def test_physical_source_and_raw_layers_must_all_be_roots(
    predecessor_field: str,
) -> None:
    physical = _physical()
    object.__setattr__(physical, predecessor_field, "a" * 64)

    with pytest.raises(ValueError, match="root"):
        _root(physical_observation=physical)


@pytest.mark.parametrize(
    "changes",
    [
        {"recorded_at": datetime(2026, 8, 7, 12)},
        {"ttl_valid_until": datetime(2026, 8, 14, 12)},
        {"valid_until": datetime(2026, 8, 14, 12)},
        {"recorded_at": _at(5)},
        {"ttl_valid_until": _at(7)},
        {"valid_until": _at(13)},
    ],
)
def test_server_clocks_and_three_way_minimum_validity_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _root(**changes)


def test_equivalent_instants_hash_identically_and_payload_uses_utc_z() -> None:
    offset = timezone(timedelta(hours=8))
    root = _root()
    equivalent = _root(
        recorded_at=_at(7).astimezone(offset),
        ttl_valid_until=_at(14).astimezone(offset),
        valid_until=_at(14).astimezone(offset),
    )

    assert equivalent.content_hash == root.content_hash
    assert cast(str, equivalent.to_payload()["recorded_at"]).endswith("Z")


def test_pit_helper_returns_only_the_exact_live_root_without_fallback() -> None:
    root = _root()

    assert resolve_allocated_physical_account_row_observation_v3(root, as_of=_at(8)) is root
    assert resolve_allocated_physical_account_row_observation_v3(root, as_of=_at(6)) is None
    assert resolve_allocated_physical_account_row_observation_v3(root, as_of=_at(14)) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_allocated_physical_account_row_observation_v3(
            root,
            as_of=datetime(2026, 8, 8, 12),
        )


def test_exact_runtime_types_fail_closed() -> None:
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationAllocation"):
        _root(allocation=cast(object, {"allocation_id": "allocation-7"}))
    with pytest.raises(TypeError, match="exact PhysicalAccountRowObservationV2"):
        _root(physical_observation=cast(object, {"observation_id": "physical-row-7"}))
    with pytest.raises(TypeError, match="exact AllocatedPhysicalAccountRowObservationV3"):
        resolve_allocated_physical_account_row_observation_v3(
            cast(AllocatedPhysicalAccountRowObservationV3, object()),
            as_of=_at(8),
        )


def test_domain_module_has_only_standard_library_and_same_app_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "allocated_physical_account_row_observation_v3.py"
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
    assert not any(name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
    assert imports <= {
        "__future__",
        "apps.account.domain.canonical_account_creation",
        "apps.account.domain.physical_account_row_observation_v2",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
