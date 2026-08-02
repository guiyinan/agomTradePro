"""Tests for typed runtime profiles and storage-policy fail-closed behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

import pytest

from apps.config_center.application.runtime_config import (
    RuntimeConfigService,
    StorageBudgetQueryService,
)
from apps.config_center.application.storage_budget import StoragePressureGuard, StoragePressureState
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    RuntimeValueType,
    StorageBudgetPolicy,
)

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


class _Definitions:
    def __init__(self, definitions: list[RuntimeConfigDefinition]) -> None:
        self.items = definitions

    def list_all(self) -> list[RuntimeConfigDefinition]:
        return self.items

    def get(self, key: str) -> RuntimeConfigDefinition | None:
        return next((item for item in self.items if item.key == key), None)


class _Profiles:
    def __init__(self) -> None:
        self.saved: list[RuntimeConfigProfile] = []

    def save(self, profile: RuntimeConfigProfile) -> RuntimeConfigProfile:
        self.saved.append(profile)
        return profile

    def get(self, profile_id: str) -> RuntimeConfigProfile | None:
        return next((item for item in self.saved if item.profile_id == profile_id), None)

    def get_active(self, environment: str) -> RuntimeConfigProfile | None:
        return next(
            (
                item
                for item in self.saved
                if item.environment == environment and item.status is RuntimeProfileStatus.ACTIVE
            ),
            None,
        )


class _Values:
    def __init__(self) -> None:
        self.saved: list[RuntimeConfigValue] = []

    def save(self, value: RuntimeConfigValue) -> RuntimeConfigValue:
        self.saved.append(value)
        return value

    def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
        return [item for item in self.saved if item.profile_id == profile_id]


class _Revisions:
    def save(self, revision):  # type: ignore[no-untyped-def]
        return revision


class _Snapshots:
    def __init__(self) -> None:
        self.saved = []

    def save(self, snapshot):  # type: ignore[no-untyped-def]
        self.saved.append(snapshot)
        return snapshot

    def get_latest(self, profile_key: str):  # type: ignore[no-untyped-def]
        return self.saved[-1] if self.saved else None


class _Budget:
    def __init__(self, policy: StorageBudgetPolicy | None) -> None:
        self.policy = policy

    def get_active(self) -> StorageBudgetPolicy | None:
        return self.policy

    def save(self, policy: StorageBudgetPolicy) -> StorageBudgetPolicy:
        self.policy = policy
        return policy


def test_runtime_definition_rejects_secret_plaintext() -> None:
    definition = RuntimeConfigDefinition(
        key="provider.api_key",
        namespace="provider",
        owner_app="data_center",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.CRITICAL,
        secret=True,
    )
    with pytest.raises(ValueError, match="secret_ref"):
        definition.validate("plaintext")


def test_runtime_profile_activation_produces_snapshot_hash() -> None:
    definition = RuntimeConfigDefinition(
        key="storage.capacity.bytes",
        namespace="storage",
        owner_app="config_center",
        value_type=RuntimeValueType.BYTES,
        criticality=RuntimeConfigCriticality.CRITICAL,
    )
    definitions = _Definitions([definition])
    profiles = _Profiles()
    values = _Values()
    snapshots = _Snapshots()
    service = RuntimeConfigService(definitions, profiles, values, _Revisions(), snapshots)
    profile = RuntimeConfigProfile(
        profile_id=str(uuid4()),
        profile_key="production-90g",
        environment="production",
        version=1,
        created_at=NOW,
    )
    saved, snapshot = service.activate(
        profile,
        (
            RuntimeConfigValue(
                profile_id=profile.profile_id,
                definition_key=definition.key,
                value_json=90 * 1024**3,
            ),
        ),
        actor="pytest",
        reason="initial production policy",
    )
    assert saved.status is RuntimeProfileStatus.ACTIVE
    assert saved.content_hash == snapshot.snapshot_hash
    assert snapshot.resolved_values[definition.key] == 90 * 1024**3


def test_runtime_profile_preview_reports_impact_without_persisting() -> None:
    definition = RuntimeConfigDefinition(
        key="storage.capacity.bytes",
        namespace="storage",
        owner_app="config_center",
        value_type=RuntimeValueType.BYTES,
        criticality=RuntimeConfigCriticality.CRITICAL,
    )
    definitions = _Definitions([definition])
    profiles = _Profiles()
    values = _Values()
    service = RuntimeConfigService(definitions, profiles, values, _Revisions(), _Snapshots())
    profile = RuntimeConfigProfile(
        profile_id=str(uuid4()),
        profile_key="preview",
        environment="development",
        version=1,
        created_at=NOW,
    )
    value = RuntimeConfigValue(
        profile_id=profile.profile_id,
        definition_key=definition.key,
        value_json=1024,
    )

    preview = service.preview(profile, (value,))

    assert preview["valid"] is True
    assert preview["changed_keys"] == (definition.key,)
    assert preview["impact"]["critical_changes"] == (definition.key,)
    assert profiles.saved == []
    assert values.saved == []


def test_runtime_profile_rollback_advances_version() -> None:
    definition = RuntimeConfigDefinition(
        key="storage.capacity.bytes",
        namespace="storage",
        owner_app="config_center",
        value_type=RuntimeValueType.BYTES,
        criticality=RuntimeConfigCriticality.CRITICAL,
    )
    definitions = _Definitions([definition])
    profiles = _Profiles()
    values = _Values()
    service = RuntimeConfigService(definitions, profiles, values, _Revisions(), _Snapshots())
    first = RuntimeConfigProfile(
        profile_id=str(uuid4()),
        profile_key="production",
        environment="production",
        version=1,
        created_at=NOW,
    )
    first_value = RuntimeConfigValue(
        profile_id=first.profile_id,
        definition_key=definition.key,
        value_json=1024,
    )
    service.activate(first, (first_value,), actor="pytest", reason="initial")
    rollback_target = RuntimeConfigProfile(
        profile_id=str(uuid4()),
        profile_key="production-previous",
        environment="production",
        version=1,
        created_at=NOW,
    )
    rollback_value = RuntimeConfigValue(
        profile_id=rollback_target.profile_id,
        definition_key=definition.key,
        value_json=512,
    )

    rolled_back, _snapshot = service.rollback(
        rollback_target,
        (rollback_value,),
        actor="pytest",
        reason="restore known-good profile",
    )

    assert rolled_back.version == 2
    assert rolled_back.based_on_profile == first.profile_id


def test_storage_budget_query_fails_closed_without_active_policy() -> None:
    service = StorageBudgetQueryService(_Budget(None))
    assert service.get_active() is None
    with pytest.raises(RuntimeError, match="storage_budget_policy_missing_or_inactive"):
        service.require_active()


def test_storage_budget_policy_rejects_sub_budget_overflow() -> None:
    with pytest.raises(ValueError, match="sub-budgets"):
        StorageBudgetPolicy(
            policy_key="production-90g",
            version=1,
            configured_capacity_bytes=90 * 1024**3,
            raw_budget_ratio=0.4,
            quarantine_budget_ratio=0.3,
            database_budget_ratio=0.3,
            logs_budget_ratio=0.2,
            emergency_reserve_ratio=0.1,
            warning_ratio=0.7,
            critical_ratio=0.85,
        )


def test_storage_pressure_guard_uses_effective_capacity_and_blocks_without_policy() -> None:
    """The observed disk can lower capacity, and missing policy must block."""

    policy = StorageBudgetPolicy(
        policy_key="production-90g",
        version=1,
        configured_capacity_bytes=1000,
        raw_budget_ratio=0.1,
        quarantine_budget_ratio=0.1,
        database_budget_ratio=0.4,
        logs_budget_ratio=0.1,
        emergency_reserve_ratio=0.05,
        warning_ratio=0.7,
        critical_ratio=0.85,
        active=True,
    )
    report = StoragePressureGuard(_Budget(policy)).evaluate(
        used_bytes=800,
        actual_capacity_bytes=900,
    )
    assert report.effective_capacity_bytes == 900
    assert report.state is StoragePressureState.CRITICAL
    blocked = StoragePressureGuard(_Budget(None)).evaluate(used_bytes=1)
    assert blocked.state is StoragePressureState.BLOCKED


@pytest.mark.parametrize("capacity_gib", [60, 90, 120])
def test_storage_pressure_fault_injection_covers_non_default_capacity_profiles(
    capacity_gib: int,
) -> None:
    """Warning, critical, and emergency watermarks scale with active capacity."""

    capacity = capacity_gib * 1024**3
    policy = StorageBudgetPolicy(
        policy_key=f"fault-{capacity_gib}g",
        version=1,
        configured_capacity_bytes=capacity,
        raw_budget_ratio=0.1,
        quarantine_budget_ratio=0.1,
        database_budget_ratio=0.4,
        logs_budget_ratio=0.1,
        emergency_reserve_ratio=0.05,
        warning_ratio=0.7,
        critical_ratio=0.85,
        active=True,
    )
    guard = StoragePressureGuard(_Budget(policy))

    assert guard.evaluate(used_bytes=int(capacity * 0.69)).state is StoragePressureState.HEALTHY
    assert guard.evaluate(used_bytes=ceil(capacity * 0.70)).state is StoragePressureState.WARNING
    assert guard.evaluate(used_bytes=ceil(capacity * 0.85)).state is StoragePressureState.CRITICAL
    assert guard.evaluate(used_bytes=ceil(capacity * 0.95)).state is StoragePressureState.EMERGENCY


@pytest.mark.django_db
def test_runtime_profile_and_storage_policy_repositories_round_trip() -> None:
    """The new models persist typed profile/snapshot inputs without plaintext secrets."""

    from apps.config_center.domain.runtime_config import (
        RuntimeConfigDefinition,
        RuntimeConfigProfile,
        RuntimeConfigValue,
    )
    from apps.config_center.infrastructure.runtime_config_repositories import (
        RuntimeConfigDefinitionRepository,
        RuntimeConfigProfileRepository,
        RuntimeConfigValueRepository,
        StorageBudgetPolicyRepository,
    )

    definition = RuntimeConfigDefinition(
        key="storage.capacity.bytes",
        namespace="storage",
        owner_app="config_center",
        value_type=RuntimeValueType.BYTES,
        criticality=RuntimeConfigCriticality.CRITICAL,
    )
    RuntimeConfigDefinitionRepository().save(definition)
    profile = RuntimeConfigProfile(
        profile_id=str(uuid4()),
        profile_key="development",
        environment="development",
        version=1,
        created_at=NOW,
    )
    RuntimeConfigProfileRepository().save(profile)
    RuntimeConfigValueRepository().save(
        RuntimeConfigValue(
            profile_id=profile.profile_id,
            definition_key=definition.key,
            value_json=1024,
        )
    )
    assert RuntimeConfigValueRepository().list_for_profile(profile.profile_id)[0].value_json == 1024
    policy = StorageBudgetPolicy(
        policy_key="development",
        version=1,
        configured_capacity_bytes=1024,
        raw_budget_ratio=0.1,
        quarantine_budget_ratio=0.1,
        database_budget_ratio=0.4,
        logs_budget_ratio=0.1,
        emergency_reserve_ratio=0.05,
        warning_ratio=0.7,
        critical_ratio=0.85,
        active=True,
    )
    StorageBudgetPolicyRepository().save(policy)
    assert StorageBudgetPolicyRepository().get_active() == policy
