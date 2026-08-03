"""Stable application ports for runtime configuration and storage policy."""

from __future__ import annotations

from apps.config_center.application.runtime_repository_provider import (
    get_runtime_config_service,
    get_storage_budget_query_service,
    get_storage_capacity_observation_service,
)
from apps.config_center.application.storage_budget import StoragePressureGuard
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    StorageBudgetPolicy,
    StorageCapacityObservation,
)


def validate_runtime_values(values: tuple[RuntimeConfigValue, ...]) -> dict[str, object]:
    """Validate typed values against the registered definition catalog."""

    return get_runtime_config_service().validate_values(values)


def get_active_runtime_profile(environment: str) -> RuntimeConfigProfile | None:
    """Read the active typed runtime profile for an environment."""

    return get_runtime_config_service().get_active_profile(environment)


def get_latest_runtime_snapshot(profile_key: str) -> RuntimeConfigSnapshot | None:
    """Read the latest resolved snapshot for a profile key."""

    return get_runtime_config_service().get_latest_snapshot(profile_key)


def get_active_runtime_value(*, environment: str, definition_key: str) -> object | None:
    """Read one value from the active, version-matched runtime snapshot.

    Consumers must not read a raw profile value directly.  The active profile and
    its immutable snapshot are checked together so a stale snapshot cannot be
    mistaken for the currently active configuration.  Missing or unavailable
    configuration is represented by ``None`` and the caller owns its declared
    compatibility/fail-closed policy.
    """

    normalized_environment = str(environment or "").strip()
    normalized_key = str(definition_key or "").strip()
    if not normalized_environment or not normalized_key:
        return None
    profile = get_active_runtime_profile(normalized_environment)
    if profile is None:
        return None
    snapshot = get_latest_runtime_snapshot(profile.profile_key)
    if snapshot is None:
        return None
    if snapshot.profile_id != profile.profile_id or snapshot.profile_version != profile.version:
        return None
    return snapshot.resolved_values.get(normalized_key)


def preview_runtime_profile(
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
) -> dict[str, object]:
    """Return validation, changed keys and operational impact without writes."""

    return get_runtime_config_service().preview(profile, values)


def activate_runtime_profile(
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
    *,
    actor: str,
    reason: str,
    release_ref: str = "",
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    """Activate a profile and return its immutable resolved snapshot."""

    return get_runtime_config_service().activate(
        profile,
        values,
        actor=actor,
        reason=reason,
        release_ref=release_ref,
    )


def rollback_runtime_profile(
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
    *,
    actor: str,
    reason: str,
    release_ref: str = "",
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    """Restore a known-good profile as a new forward revision."""

    return get_runtime_config_service().rollback(
        profile,
        values,
        actor=actor,
        reason=reason,
        release_ref=release_ref,
    )


def get_active_storage_budget() -> StorageBudgetPolicy | None:
    """Read the active policy without silently defaulting capacity."""

    return get_storage_budget_query_service().get_active()


def require_active_storage_budget() -> StorageBudgetPolicy:
    """Read the active policy or raise a stable fail-closed error."""

    return get_storage_budget_query_service().require_active()


def evaluate_storage_pressure(
    *,
    used_bytes: int,
    actual_capacity_bytes: int | None = None,
) -> dict[str, object]:
    """Evaluate filesystem usage against the active policy without fallback."""

    try:
        report = StoragePressureGuard(get_storage_budget_query_service()).evaluate(
            used_bytes=used_bytes,
            actual_capacity_bytes=actual_capacity_bytes,
        )
    except Exception:
        return {
            "state": "blocked",
            "used_bytes": used_bytes,
            "effective_capacity_bytes": None,
            "configured_capacity_bytes": None,
            "usage_ratio": None,
            "reason": "storage_budget_unavailable",
        }
    return {
        "state": report.state.value,
        "used_bytes": report.used_bytes,
        "effective_capacity_bytes": report.effective_capacity_bytes,
        "configured_capacity_bytes": report.configured_capacity_bytes,
        "usage_ratio": report.usage_ratio,
        "reason": report.reason,
    }


def record_storage_capacity_observation(
    observation: StorageCapacityObservation,
) -> StorageCapacityObservation:
    """Persist one filesystem/database capacity observation."""

    return get_storage_capacity_observation_service().record(observation)


def get_latest_storage_capacity_observation(
    environment: str,
) -> StorageCapacityObservation | None:
    """Return the latest capacity observation without a fallback."""

    return get_storage_capacity_observation_service().get_latest(environment)


__all__ = [
    "activate_runtime_profile",
    "evaluate_storage_pressure",
    "get_active_runtime_profile",
    "get_active_runtime_value",
    "get_active_storage_budget",
    "get_latest_runtime_snapshot",
    "get_latest_storage_capacity_observation",
    "require_active_storage_budget",
    "preview_runtime_profile",
    "rollback_runtime_profile",
    "record_storage_capacity_observation",
    "validate_runtime_values",
]
