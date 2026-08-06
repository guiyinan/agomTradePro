"""Public application ports for Config Center runtime and governance.

Business apps may consume these functions from their infrastructure
composition roots. They must not import Config Center ORM models directly.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .config_summary_service import get_config_center_summary_service
from .runtime_public import get_active_runtime_value
from .use_cases import (
    GetSystemGovernanceSettingsUseCase,
    UpdateSystemGovernanceSettingsUseCase,
)


def get_system_settings_summary() -> dict[str, Any]:
    """Return the Config Center-owned system settings summary."""

    return get_config_center_summary_service().get_system_settings_summary()


def get_system_governance_settings() -> dict[str, Any]:
    """Return the administrator-facing typed global-settings contract."""

    return GetSystemGovernanceSettingsUseCase().execute()


def update_system_governance_settings(
    payload: Mapping[str, Any],
    *,
    actor: Any = None,
) -> dict[str, Any]:
    """Update Config Center-owned global runtime settings through its use case."""

    return UpdateSystemGovernanceSettingsUseCase().execute(
        payload=dict(payload),
        actor=actor,
    )


def get_runtime_market_visual_tokens() -> dict[str, str]:
    """Return the configured market visual token mapping."""

    return get_config_center_summary_service().get_runtime_market_visual_tokens()


def get_runtime_qlib_config() -> dict[str, Any]:
    """Return the active Qlib runtime configuration."""

    return get_config_center_summary_service().get_runtime_qlib_config()


def get_runtime_alpha_fixed_provider() -> str:
    """Return the configured fixed Alpha provider."""

    return get_config_center_summary_service().get_runtime_alpha_fixed_provider()


def get_runtime_alpha_pool_mode(default_mode: str = "") -> str:
    """Return the configured Alpha pool mode or the caller default."""

    return get_config_center_summary_service().get_runtime_alpha_pool_mode(default_mode)


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return one configured benchmark code."""

    return get_config_center_summary_service().get_runtime_benchmark_code(key, default)


def get_runtime_asset_proxy_map() -> dict[str, str]:
    """Return the configured runtime asset-proxy mapping."""

    return get_config_center_summary_service().get_runtime_asset_proxy_map()


def get_runtime_config_value(
    definition_key: str,
    *,
    environment: str | None = None,
) -> object | None:
    """Return one active typed runtime value through the owner Application Port.

    Callers must provide an explicit environment when they operate outside the
    configured Django settings module.  Missing profiles/snapshots return
    ``None`` so safety-sensitive consumers can fail closed without inventing a
    default.
    """

    normalized_key = str(definition_key or "").strip()
    if not normalized_key:
        return None
    resolved_environment = str(environment or "").strip()
    if not resolved_environment:
        settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
        resolved_environment = (
            "production" if settings_module.endswith(".production") else "development"
        )
    return get_active_runtime_value(
        environment=resolved_environment,
        definition_key=normalized_key,
    )


__all__ = [
    "get_system_governance_settings",
    "get_runtime_alpha_fixed_provider",
    "get_runtime_alpha_pool_mode",
    "get_runtime_asset_proxy_map",
    "get_runtime_benchmark_code",
    "get_runtime_market_visual_tokens",
    "get_runtime_qlib_config",
    "get_runtime_config_value",
    "get_system_settings_summary",
    "update_system_governance_settings",
]
