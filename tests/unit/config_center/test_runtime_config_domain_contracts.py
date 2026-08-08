"""Boundary tests for Config Center runtime configuration domain objects."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from math import nan

import pytest

from apps.config_center.domain.entities import (
    AlphaUniverseConfig,
    DecisionRuntimeState,
    DecisionRuntimeStatus,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    RuntimeValueType,
    StorageBudgetPolicy,
    StorageCapacityObservation,
)
from shared.domain.reliability import ReliabilityStatus

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _definition(**overrides: object) -> RuntimeConfigDefinition:
    values: dict[str, object] = {
        "key": "runtime.sample",
        "namespace": "runtime",
        "owner_app": "config_center",
        "value_type": RuntimeValueType.STRING,
    }
    values.update(overrides)
    return RuntimeConfigDefinition(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": "unnamespaced"},
        {"namespace": ""},
        {"owner_app": ""},
        {"secret": True, "value_type": RuntimeValueType.TYPED_JSON},
        {"is_deprecated": True},
    ],
)
def test_runtime_definition_rejects_invalid_registry_metadata(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _definition(**overrides)


@pytest.mark.parametrize(
    ("definition", "value", "secret_ref"),
    [
        (_definition(secret=True), "plain-text", "secret://configured"),
        (_definition(secret=True), None, ""),
        (_definition(), "value", "secret://unexpected"),
        (_definition(value_type=RuntimeValueType.BOOL), 1, ""),
        (_definition(value_type=RuntimeValueType.INT), True, ""),
        (_definition(value_type=RuntimeValueType.DECIMAL), "not-decimal", ""),
        (_definition(value_type=RuntimeValueType.PERCENTAGE), "1.01", ""),
        (_definition(value_type=RuntimeValueType.STRING), 1, ""),
        (_definition(value_type=RuntimeValueType.DURATION), -1, ""),
        (_definition(value_type=RuntimeValueType.BYTES), True, ""),
        (
            _definition(
                value_type=RuntimeValueType.ENUM,
                constraints={"choices": ("safe", "fast")},
            ),
            "unknown",
            "",
        ),
        (_definition(value_type=RuntimeValueType.TYPED_JSON), "[]", ""),
        (_definition(value_type=RuntimeValueType.INT, constraints={"minimum": 2}), 1, ""),
        (_definition(value_type=RuntimeValueType.INT, constraints={"maximum": 2}), 3, ""),
    ],
)
def test_runtime_definition_rejects_invalid_values(
    definition: RuntimeConfigDefinition,
    value: object,
    secret_ref: str,
) -> None:
    with pytest.raises(ValueError):
        definition.validate(value, secret_ref=secret_ref)


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (RuntimeValueType.BOOL, True),
        (RuntimeValueType.INT, 2),
        (RuntimeValueType.DECIMAL, "2.5"),
        (RuntimeValueType.PERCENTAGE, "0.5"),
        (RuntimeValueType.STRING, "value"),
        (RuntimeValueType.DURATION, 0),
        (RuntimeValueType.BYTES, 0),
        (RuntimeValueType.TYPED_JSON, {"enabled": True}),
    ],
)
def test_runtime_definition_accepts_each_scalar_shape(
    value_type: RuntimeValueType,
    value: object,
) -> None:
    _definition(value_type=value_type).validate(value)
    _definition(secret=True).validate(None, secret_ref="secret://runtime/sample")


def test_runtime_profile_value_revision_and_snapshot_reject_invalid_state() -> None:
    profile = RuntimeConfigProfile(
        profile_id="profile-1",
        profile_key="runtime.default",
        environment="production",
        version=1,
        created_at=NOW,
    )
    for overrides in (
        {"profile_id": ""},
        {"version": 0},
        {"created_at": datetime(2026, 8, 8)},
        {"activated_at": datetime(2026, 8, 8)},
        {"status": RuntimeProfileStatus.ACTIVE},
    ):
        with pytest.raises(ValueError):
            replace(profile, **overrides)

    for kwargs in (
        {"profile_id": "", "definition_key": "runtime.sample"},
        {"profile_id": "profile-1", "definition_key": ""},
        {
            "profile_id": "profile-1",
            "definition_key": "runtime.sample",
            "validation_status": "unknown",
        },
    ):
        with pytest.raises(ValueError):
            RuntimeConfigValue(**kwargs)

    revision = RuntimeConfigRevision(
        revision_id="revision-1",
        profile_id="profile-1",
        before_hash="before",
        after_hash="after",
        changed_keys=("runtime.sample",),
        before_projection={},
        after_projection={"runtime.sample": True},
        actor="operator",
        reason="promotion",
        changed_at=NOW,
    )
    for overrides in (
        {"revision_id": ""},
        {"actor": ""},
        {"changed_at": datetime(2026, 8, 8)},
    ):
        with pytest.raises(ValueError):
            replace(revision, **overrides)

    snapshot = RuntimeConfigSnapshot(
        snapshot_id="snapshot-1",
        profile_id="profile-1",
        profile_key="runtime.default",
        profile_version=1,
        snapshot_hash="hash",
        resolved_values={"runtime.sample": True},
        generated_at=NOW,
    )
    for overrides in (
        {"snapshot_id": ""},
        {"profile_version": 0},
        {"snapshot_hash": ""},
        {"generated_at": datetime(2026, 8, 8)},
    ):
        with pytest.raises(ValueError):
            replace(snapshot, **overrides)
    assert RuntimeConfigSnapshot.hash_values({"b": 2, "a": 1}) == RuntimeConfigSnapshot.hash_values(
        {"a": 1, "b": 2}
    )


def test_storage_budget_policy_rejects_invalid_boundaries() -> None:
    policy = StorageBudgetPolicy(
        policy_key="production.default",
        version=1,
        configured_capacity_bytes=1_000,
        raw_budget_ratio=0.2,
        quarantine_budget_ratio=0.1,
        database_budget_ratio=0.2,
        logs_budget_ratio=0.1,
        emergency_reserve_ratio=0.1,
        warning_ratio=0.7,
        critical_ratio=0.9,
    )
    for overrides in (
        {"policy_key": ""},
        {"configured_capacity_bytes": 0},
        {"raw_budget_ratio": 1.1},
        {"warning_ratio": 0.9},
        {
            "raw_budget_ratio": 0.3,
            "quarantine_budget_ratio": 0.2,
            "database_budget_ratio": 0.3,
            "logs_budget_ratio": 0.2,
            "emergency_reserve_ratio": 0.1,
        },
    ):
        with pytest.raises(ValueError):
            replace(policy, **overrides)


def test_storage_capacity_observation_rejects_invalid_evidence() -> None:
    observation = StorageCapacityObservation(
        observation_id="observation-1",
        environment="production",
        observed_at=NOW,
        filesystem_total_bytes=100,
        filesystem_used_bytes=40,
        filesystem_free_bytes=50,
        database_size_bytes=20,
        relation_sizes={"facts": 10},
    )
    for overrides in (
        {"observation_id": ""},
        {"observed_at": datetime(2026, 8, 8)},
        {"filesystem_used_bytes": -1},
        {"filesystem_free_bytes": 70},
        {"relation_sizes": {"facts": -1}},
        {"configured_capacity_bytes": 0},
        {"effective_capacity_bytes": 0},
        {"usage_ratio": nan},
        {"usage_ratio": -0.1},
    ):
        with pytest.raises(ValueError):
            replace(observation, **overrides)


def test_decision_runtime_state_covers_active_and_blocked_reliability_contracts() -> None:
    with pytest.raises(ValueError):
        DecisionRuntimeState(status=DecisionRuntimeStatus.MAINTENANCE)
    with pytest.raises(ValueError):
        DecisionRuntimeState(changed_at=datetime(2026, 8, 8))
    with pytest.raises(ValueError):
        DecisionRuntimeState(status=DecisionRuntimeStatus.ACTIVE).to_reliability_contract()

    active = DecisionRuntimeState(changed_at=NOW)
    assert active.to_reliability_contract().status is ReliabilityStatus.FRESH
    assert active.to_dict()["changed_at"] == NOW.isoformat()

    for status, expected in (
        (DecisionRuntimeStatus.MAINTENANCE, ReliabilityStatus.MAINTENANCE),
        (DecisionRuntimeStatus.VALIDATING, ReliabilityStatus.MAINTENANCE),
        (DecisionRuntimeStatus.BLOCKED, ReliabilityStatus.FAILED),
    ):
        state = DecisionRuntimeState(status=status, reason="controlled gate", changed_at=NOW)
        contract = state.to_reliability_contract()
        assert contract.status is expected
        assert contract.block_reason_code == f"decision_runtime_{status.value}"


def test_alpha_universe_rejects_invalid_sources_and_serializes_valid_index() -> None:
    valid = AlphaUniverseConfig(
        universe_id="csi300",
        name="CSI 300",
        source_type="tushare_index",
        filters={"index_code": "000300.sh"},
    )
    assert valid.to_dict()["filters"] == {"index_code": "000300.sh"}

    for kwargs in (
        {"universe_id": "", "name": "name", "source_type": "manual"},
        {"universe_id": "id", "name": "", "source_type": "manual"},
        {"universe_id": "id", "name": "name", "source_type": "unknown"},
        {
            "universe_id": "id",
            "name": "name",
            "source_type": "tushare_index",
            "filters": {"index_code": "bad"},
        },
    ):
        with pytest.raises(ValueError):
            AlphaUniverseConfig(**kwargs)
