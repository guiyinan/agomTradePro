"""App-neutral bridge for Config Center runtime read ports.

The configuration app owns runtime-profile resolution and storage-budget policy
evaluation.  Consumers register against this small Protocol at the composition
root instead of importing Config Center application modules directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class RuntimeConfigDefinitionSpec:
    """App-neutral scalar configuration metadata supplied to the owner."""

    key: str
    namespace: str
    owner_app: str
    value_type: Literal["bool", "int", "string", "bytes"]
    criticality: Literal["bootstrap", "critical", "normal", "experimental"] = "normal"
    reload_mode: Literal["immediate", "next_task", "restart_required"] = "next_task"
    secret: bool = False
    description: str = ""
    minimum: int | None = None


class ConfigCenterRuntimeReadPort(Protocol):
    """Config Center-owned runtime operations used by registered consumers."""

    def get_active_runtime_secret_ref(self, *, environment: str, definition_key: str) -> str | None:
        """Read a secret reference without returning secret material."""

    def register_runtime_definitions(
        self, specifications: tuple[RuntimeConfigDefinitionSpec, ...]
    ) -> tuple[str, ...]:
        """Validate and persist definition metadata through the owner."""

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

    def collect_storage_capacity_profile(
        self,
        *,
        environment: str,
        source: str,
    ) -> dict[str, object]:
        """Collect and persist one policy-bound capacity observation payload."""


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


def get_active_runtime_secret_ref(*, environment: str, definition_key: str) -> str | None:
    """Read an owner-validated secret ref, returning None before registration."""

    if _provider is None:
        return None
    return _provider.get_active_runtime_secret_ref(
        environment=environment, definition_key=definition_key
    )


def register_runtime_definitions(
    definitions: tuple[RuntimeConfigDefinitionSpec, ...],
) -> tuple[str, ...]:
    """Persist supplied metadata only through the configured owner facade."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    return _provider.register_runtime_definitions(definitions)


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


def collect_storage_capacity_profile(
    *,
    environment: str,
    source: str,
) -> dict[str, object]:
    """Collect policy-bound capacity evidence through the owner facade."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    return _provider.collect_storage_capacity_profile(
        environment=environment,
        source=source,
    )


def activate_runtime_profile_patch(
    *,
    environment: str,
    patch: Mapping[str, object],
    bootstrap_values: Mapping[str, object] | None,
    secret_ref_patch: Mapping[str, str] | None = None,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Activate a typed runtime patch through the configured owner bridge."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    callback = getattr(_provider, "activate_runtime_profile_patch_payload", None)
    if not callable(callback):
        raise RuntimeError("config_center_runtime_write_port_unconfigured")
    options: dict[str, object] = {
        "environment": environment,
        "patch": patch,
        "bootstrap_values": bootstrap_values,
        "actor": actor,
        "reason": reason,
    }
    if secret_ref_patch is not None:
        options["secret_ref_patch"] = secret_ref_patch
    result = callback(**options)
    if not isinstance(result, dict):
        raise TypeError("Config Center runtime write port returned an invalid payload")
    return dict(result)


__all__ = [
    "ConfigCenterRuntimeReadPort",
    "RuntimeConfigDefinitionSpec",
    "activate_runtime_profile_patch",
    "collect_storage_capacity_profile",
    "configure_config_center_runtime_port",
    "evaluate_storage_pressure",
    "get_active_runtime_value",
    "get_active_runtime_secret_ref",
    "register_runtime_definitions",
]
