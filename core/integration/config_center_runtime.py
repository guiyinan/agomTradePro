"""App-neutral bridge for Config Center runtime read ports.

The configuration app owns runtime-profile resolution and storage-budget policy
evaluation.  Consumers register against this small Protocol at the composition
root instead of importing Config Center application modules directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class ConfigCenterRuntimeReadPort(Protocol):
    """Read-only Config Center contract used by runtime consumers."""

    def get_active_runtime_value(
        self,
        *,
        environment: str,
        definition_key: str,
    ) -> object | None:
        """Return one typed value from the active runtime snapshot."""

    def evaluate_storage_pressure(
        self,
        *,
        used_bytes: int,
        actual_capacity_bytes: int | None = None,
    ) -> dict[str, object]:
        """Evaluate observed storage usage against the active policy."""


_provider: ConfigCenterRuntimeReadPort | None = None


def configure_config_center_runtime_port(provider: ConfigCenterRuntimeReadPort) -> None:
    """Register the Config Center-owned runtime facade at the composition root."""

    global _provider
    _provider = provider


def get_active_runtime_value(
    *,
    environment: str,
    definition_key: str,
) -> object | None:
    """Read one active runtime value, failing closed when the owner is absent."""

    if _provider is None:
        return None
    return _provider.get_active_runtime_value(
        environment=environment,
        definition_key=definition_key,
    )


def evaluate_storage_pressure(
    *,
    used_bytes: int,
    actual_capacity_bytes: int | None = None,
) -> dict[str, object]:
    """Evaluate storage pressure through the owner facade, fail-closed if absent."""

    if _provider is None:
        return {
            "state": "blocked",
            "used_bytes": used_bytes,
            "effective_capacity_bytes": None,
            "configured_capacity_bytes": None,
            "usage_ratio": None,
            "reason": "config_center_runtime_port_unconfigured",
        }

    try:
        return _provider.evaluate_storage_pressure(
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
            "reason": "config_center_storage_pressure_unavailable",
        }


def activate_runtime_profile_patch(
    *,
    environment: str,
    patch: Mapping[str, object],
    bootstrap_values: Mapping[str, object] | None,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Activate a typed runtime patch through the configured owner bridge."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    callback = getattr(_provider, "activate_runtime_profile_patch_payload", None)
    if not callable(callback):
        raise RuntimeError("config_center_runtime_write_port_unconfigured")
    result = callback(
        environment=environment,
        patch=patch,
        bootstrap_values=bootstrap_values,
        actor=actor,
        reason=reason,
    )
    if not isinstance(result, dict):
        raise TypeError("Config Center runtime write port returned an invalid payload")
    return dict(result)


__all__ = [
    "ConfigCenterRuntimeReadPort",
    "activate_runtime_profile_patch",
    "configure_config_center_runtime_port",
    "evaluate_storage_pressure",
    "get_active_runtime_value",
]
