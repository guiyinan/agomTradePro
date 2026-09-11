from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from tests.unit.account.test_allocated_physical_account_row_observation_v3 import (
    _root,
)
from tests.unit.account.test_physical_account_row_observation_v2 import (
    _observation,
    _raw,
    _source,
)


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def _binding(
    *,
    root: AllocatedPhysicalAccountRowObservationV3 | None = None,
    recorded_at: datetime = _at(8),
    **changes: object,
) -> CanonicalAccountCreationBindingV2:
    creation_root = root if root is not None else _root(ttl_valid_until=_at(9), valid_until=_at(9))
    physical = creation_root.physical_observation
    values: dict[str, object] = {
        "binding_id": "durable-binding-reobserve-7",
        "binding_version": "v2",
        "allocation": creation_root.allocation,
        "creation_root": creation_root,
        "account_namespace_claim": physical.account_namespace,
        "account_id_claim": physical.account_id,
        "underlying_unified_account_namespace_claim": (
            physical.underlying_unified_account_namespace
        ),
        "underlying_unified_account_id_claim": physical.underlying_unified_account_id,
        "creation_root_identity_hash": creation_root.identity_hash,
        "creation_root_content_hash": creation_root.content_hash,
        "physical_observation_content_hash": physical.content_hash,
        "physical_source_content_hash": physical.source_content_hash,
        "physical_raw_observation_content_hash": physical.raw_observation_content_hash,
        "recorded_by": CanonicalAccountCreationServiceRecorder(
            service_id="account-creation-binder-reobserve",
            role="canonical_account_creation_binder",
        ),
        "recorded_at": recorded_at,
    }
    values.update(changes)
    return CanonicalAccountCreationBindingV2(**values)  # type: ignore[arg-type]


def _current_physical(
    *,
    recorded_at: datetime = _at(10),
    ttl_valid_until: datetime = _at(12),
    valid_until: datetime = _at(12),
    **changes: object,
) -> PhysicalAccountRowObservationV2:
    physical_changes = dict(changes)
    observation_id = cast(
        str,
        physical_changes.pop("observation_id", "physical-account-row-reobserve-7"),
    )
    observation_version = cast(
        str,
        physical_changes.pop("observation_version", "reobservation-v1"),
    )
    row_user_id = physical_changes.pop("row_user_id", 42)
    raw_account_type = physical_changes.pop("raw_account_type", "SIMULATED")
    row_created_at = physical_changes.pop("row_created_at", _at(2))
    row_updated_at = physical_changes.pop("row_updated_at", _at(3))
    is_active = physical_changes.pop("is_active", True)
    has_present = "is_present" in physical_changes
    has_tombstone = "is_tombstone" in physical_changes
    is_present = physical_changes.pop("is_present", False if has_tombstone else True)
    is_tombstone = physical_changes.pop("is_tombstone", not is_present)
    if has_present and not has_tombstone:
        is_tombstone = not is_present
    elif has_tombstone and not has_present:
        is_present = not is_tombstone
    account_namespace = physical_changes.pop("account_namespace", "account")
    account_id = physical_changes.pop("account_id", "acct-0007")
    underlying_namespace = physical_changes.pop(
        "underlying_unified_account_namespace",
        "simulated-account-row",
    )
    underlying_id = physical_changes.pop("underlying_unified_account_id", 7)
    raw = _raw(
        row_pk=underlying_id,
        row_user_id=row_user_id,
        raw_account_type=raw_account_type,
        is_active=is_active,
        row_created_at=row_created_at,
        row_updated_at=row_updated_at,
        is_present=is_present,
        is_tombstone=is_tombstone,
    )
    source = _source(
        raw=raw,
        account_namespace=account_namespace,
        account_id=account_id,
        underlying_unified_account_namespace=underlying_namespace,
        recorded_at=_at(4),
        ttl_valid_until=_at(12),
        valid_until=_at(12),
    )
    values: dict[str, object] = {
        "source": source,
        "observation_id": observation_id,
        "observation_version": observation_version,
        "recorded_at": recorded_at,
        "ttl_valid_until": ttl_valid_until,
        "valid_until": valid_until,
    }
    values.update(physical_changes)
    return _observation(**values)


def _reobservation(
    *,
    binding: CanonicalAccountCreationBindingV2 | None = None,
    current_physical: PhysicalAccountRowObservationV2 | None = None,
    **changes: object,
) -> CanonicalAccountOwnershipReobservationV1:
    current = _current_physical() if current_physical is None else current_physical
    current_valid_until = (
        current.valid_until if type(current) is PhysicalAccountRowObservationV2 else _at(12)
    )
    values: dict[str, object] = {
        "observation_id": "account-ownership-reobserve-7",
        "observation_version": "v1",
        "binding": binding or _binding(),
        "current_physical": current,
        "recorded_at": _at(10),
        "valid_until": current_valid_until,
    }
    values.update(changes)
    return CanonicalAccountOwnershipReobservationV1(**values)  # type: ignore[arg-type]


def test_reobservation_accepts_expired_creation_root_and_seals_live_row_shape() -> None:
    binding = _binding()
    current = _current_physical()
    reobservation = _reobservation(binding=binding, current_physical=current)

    assert binding.creation_root.is_knowable_at(_at(10)) is False
    assert binding.is_knowable_at(_at(10)) is True
    assert reobservation.owner == "account"
    assert reobservation.artifact_type == "canonical_account_ownership_reobservation_v1"
    assert reobservation.schema == "canonical-account-ownership-reobservation.v1"
    assert reobservation.permission == "evidence_only"
    assert reobservation.status == "inactive"
    assert reobservation.activation_available is False
    assert reobservation.must_not_execute is True
    assert reobservation.is_current_at(_at(10)) is True
    assert reobservation.is_current_at(_at(12)) is False
    assert len(reobservation.identity_hash) == len(reobservation.content_hash) == 64

    payload = reobservation.to_payload()
    assert payload["binding"] == binding.to_payload()
    assert payload["current_physical"] == current.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
    assert not hasattr(reobservation, "__dict__")


def test_reobservation_is_frozen_and_has_only_the_declared_evidence_fields() -> None:
    value = _reobservation()
    assert {field.name for field in fields(CanonicalAccountOwnershipReobservationV1)} == {
        "observation_id",
        "observation_version",
        "binding",
        "current_physical",
        "recorded_at",
        "valid_until",
        "identity_hash",
        "content_hash",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "status",
    }
    with pytest.raises(FrozenInstanceError):
        value.observation_version = "v2"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("owner", "simulated_trading"),
        ("artifact_type", "canonical_account_ownership_reobservation"),
        ("schema", "canonical-account-ownership-reobservation.v2"),
        ("permission", "execute"),
        ("status", "active"),
    ],
)
def test_reobservation_fixed_semantics_cannot_be_reinterpreted(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="fixed"):
        _reobservation(**{field_name: value})


@pytest.mark.parametrize("field_name", ["owner", "artifact_type", "schema", "permission", "status"])
def test_reobservation_fixed_semantics_require_exact_strings(field_name: str) -> None:
    with pytest.raises(TypeError, match="exact string"):
        _reobservation(**{field_name: cast(object, True)})


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("account_namespace", "other-account", "canonical account scope"),
        ("account_id", "acct-other", "canonical account scope"),
        ("underlying_unified_account_namespace", "other-row", "underlying row scope"),
        ("underlying_unified_account_id", 8, "underlying row scope"),
        ("row_user_id", 99, "row user"),
        ("raw_account_type", "PAPER", "raw account type"),
        ("row_created_at", _at(1), "row_created_at"),
        ("row_updated_at", _at(2), "row_updated_at"),
    ],
)
def test_reobservation_requires_exact_original_identity_and_monotonic_update(
    field_name: str,
    value: object,
    message: str,
) -> None:
    current = _current_physical(**{field_name: value})
    with pytest.raises(ValueError, match=message):
        _reobservation(current_physical=current)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("is_active", False, "current physical"),
        ("is_present", False, "current physical"),
        ("is_tombstone", True, "current physical"),
    ],
)
def test_reobservation_rejects_unavailable_current_physical_fact(
    field_name: str,
    value: bool,
    message: str,
) -> None:
    current = _current_physical(**{field_name: value})
    with pytest.raises(ValueError, match=message):
        _reobservation(current_physical=current)


def test_reobservation_requires_recording_after_both_sources_and_exact_expiry() -> None:
    with pytest.raises(ValueError, match="recorded_at"):
        _reobservation(recorded_at=_at(9, 23, 59))

    future = _current_physical(recorded_at=_at(11), ttl_valid_until=_at(12), valid_until=_at(12))
    with pytest.raises(ValueError, match="physical"):
        _reobservation(current_physical=future)

    expired = _current_physical(recorded_at=_at(8), ttl_valid_until=_at(9), valid_until=_at(9))
    with pytest.raises(ValueError, match="current"):
        _reobservation(current_physical=expired)

    with pytest.raises(ValueError, match="valid_until"):
        _reobservation(valid_until=_at(11))


def test_reobservation_rejects_naive_and_noncanonical_clocks() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _reobservation(recorded_at=datetime(2026, 8, 10, 12))
    with pytest.raises(ValueError, match="timezone-aware"):
        _reobservation().is_current_at(datetime(2026, 8, 10, 12))

    offset = timezone(timedelta(hours=8))
    equivalent = _reobservation(
        recorded_at=_at(10).astimezone(offset),
        valid_until=_at(12).astimezone(offset),
    )
    assert equivalent.identity_hash == _reobservation().identity_hash
    assert equivalent.content_hash == _reobservation().content_hash


def test_reobservation_hashes_are_strict_and_domain_separated() -> None:
    value = _reobservation()
    assert value.identity_hash != value.content_hash
    with pytest.raises(ValueError, match="identity_hash"):
        _reobservation(identity_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _reobservation(content_hash="b" * 64)
    with pytest.raises(TypeError, match="exact string"):
        _reobservation(identity_hash=cast(object, True))


def test_reobservation_nested_tampering_fails_closed_and_old_payloads_stay_unchanged() -> None:
    binding = _binding()
    current = _current_physical()
    binding_payload = binding.to_payload()
    current_payload = current.to_payload()
    value = _reobservation(binding=binding, current_physical=current)

    assert binding.to_payload() == binding_payload
    assert current.to_payload() == current_payload

    object.__setattr__(current, "row_user_id", 99)
    with pytest.raises(ValueError):
        value.to_payload()


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("observation_id", 1, "exact string"),
        ("observation_version", True, "exact string"),
    ],
)
def test_reobservation_service_observation_identity_is_strict(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        _reobservation(**{field_name: value})


def test_reobservation_requires_exact_nested_v2_types() -> None:
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationBindingV2"):
        _reobservation(binding=cast(CanonicalAccountCreationBindingV2, object()))
    with pytest.raises(TypeError, match="exact PhysicalAccountRowObservationV2"):
        _reobservation(current_physical=cast(PhysicalAccountRowObservationV2, object()))


def test_reobservation_never_revives_the_expired_current_capture() -> None:
    value = _reobservation()
    assert value.binding.is_knowable_at(_at(30)) is True
    assert value.is_knowable_at(_at(30)) is True
    assert value.is_current_at(_at(12)) is False
    assert value.is_current_at(_at(30)) is False
