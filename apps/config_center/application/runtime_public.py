"""Stable application ports for runtime configuration and storage policy."""

from __future__ import annotations

from pathlib import Path

from apps.config_center.application.runtime_definition_reconcile import (
    reconcile_runtime_definitions as _reconcile_runtime_definitions,
)
from apps.config_center.application.runtime_repository_provider import (
    get_runtime_config_service,
    get_runtime_definition_repository,
    get_storage_budget_query_service,
    get_storage_capacity_observation_service,
)
from apps.config_center.application.storage_budget import StoragePressureGuard
from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    StorageBudgetPolicy,
    StorageCapacityObservation,
)

_QLIB_RUNTIME_FIELDS: tuple[tuple[str, str, type[object]], ...] = (
    ("enabled", "alpha.qlib.enabled", bool),
    ("provider_uri", "alpha.qlib.provider_uri", str),
    ("region", "alpha.qlib.region", str),
    ("model_path", "alpha.qlib.model_path", str),
    ("default_universe", "alpha.qlib.default_universe", str),
    ("default_feature_set_id", "alpha.qlib.default_feature_set_id", str),
    ("default_label_id", "alpha.qlib.default_label_id", str),
    ("train_queue_name", "alpha.qlib.train_queue_name", str),
    ("infer_queue_name", "alpha.qlib.infer_queue_name", str),
    ("allow_auto_activate", "alpha.qlib.allow_auto_activate", bool),
)

_DOMAIN_RUNTIME_FIELDS: tuple[tuple[str, str, type[object]], ...] = (
    ("alpha_fixed_provider", "alpha.runtime.fixed_provider", str),
    ("alpha_pool_mode", "alpha.runtime.pool_mode", str),
    ("market_color_convention", "config_center.market.color_convention", str),
    ("benchmark_code_map", "config_center.market.benchmark_code_map", dict),
    ("asset_proxy_code_map", "config_center.market.asset_proxy_code_map", dict),
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


def get_active_qlib_runtime_config(environment: str) -> dict[str, object] | None:
    """Resolve a complete Qlib runtime mapping from the active snapshot.

    The typed snapshot is an opt-in cutover path.  A partial, stale or malformed
    snapshot returns ``None`` so the owner can keep its explicitly documented
    SystemSettings compatibility path.  No values are invented here.
    """

    normalized_environment = str(environment or "").strip()
    if not normalized_environment:
        return None
    resolved: dict[str, object] = {}
    for field_name, definition_key, expected_type in _QLIB_RUNTIME_FIELDS:
        value = get_active_runtime_value(
            environment=normalized_environment,
            definition_key=definition_key,
        )
        if isinstance(value, bool) and expected_type is bool:
            resolved[field_name] = value
        elif isinstance(value, str) and expected_type is str and value.strip():
            resolved[field_name] = value
        else:
            return None

    provider_uri = str(resolved["provider_uri"])
    resolved["is_configured"] = bool(
        bool(resolved["enabled"]) and Path(provider_uri).expanduser().exists()
    )
    return resolved


def get_active_domain_runtime_config(environment: str) -> dict[str, object] | None:
    """Resolve typed Alpha/market runtime values from one active snapshot.

    The projection is intentionally all-or-nothing: a partial snapshot returns
    ``None`` so the owning repository can apply its explicitly documented
    compatibility policy rather than mixing values from two configuration
    sources.
    """

    normalized_environment = str(environment or "").strip()
    if not normalized_environment:
        return None

    resolved: dict[str, object] = {}
    for field_name, definition_key, expected_type in _DOMAIN_RUNTIME_FIELDS:
        value = get_active_runtime_value(
            environment=normalized_environment,
            definition_key=definition_key,
        )
        if expected_type is dict:
            if not isinstance(value, dict):
                return None
            resolved[field_name] = dict(value)
        elif isinstance(value, expected_type):
            resolved[field_name] = value
        else:
            return None
    return resolved


def reconcile_runtime_definitions() -> tuple[RuntimeConfigDefinition, ...]:
    """Idempotently reconcile the Config Center-owned definition catalog."""

    return _reconcile_runtime_definitions(get_runtime_definition_repository())


def validate_active_runtime_profile(environment: str) -> dict[str, object]:
    """Validate the active profile without changing runtime state."""

    return get_runtime_config_service().validate_active_profile(environment)


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
    "get_active_domain_runtime_config",
    "get_active_qlib_runtime_config",
    "get_active_storage_budget",
    "get_latest_runtime_snapshot",
    "get_latest_storage_capacity_observation",
    "reconcile_runtime_definitions",
    "require_active_storage_budget",
    "preview_runtime_profile",
    "rollback_runtime_profile",
    "record_storage_capacity_observation",
    "validate_runtime_values",
    "validate_active_runtime_profile",
]
