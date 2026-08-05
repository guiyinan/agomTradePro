"""Public application ports for Config Center runtime summaries.

Business apps may consume these read-only functions from their infrastructure
composition roots.  They must not import Config Center ORM models directly.
"""

from __future__ import annotations

from typing import Any

from .config_summary_service import get_config_center_summary_service


def get_system_settings_summary() -> dict[str, Any]:
    """Return the Config Center-owned system settings summary."""

    return get_config_center_summary_service().get_system_settings_summary()


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


__all__ = [
    "get_runtime_alpha_fixed_provider",
    "get_runtime_alpha_pool_mode",
    "get_runtime_asset_proxy_map",
    "get_runtime_benchmark_code",
    "get_runtime_market_visual_tokens",
    "get_runtime_qlib_config",
    "get_system_settings_summary",
]
