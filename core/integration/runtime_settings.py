"""Bridge helpers for runtime settings lookups."""

from __future__ import annotations

from typing import Any, Protocol


class RuntimeSettingsProvider(Protocol):
    """Read-model contract used by the core runtime settings bridge."""

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro index metadata map."""

    def get_runtime_macro_index_codes(self) -> list[str]:
        """Return runtime macro index codes."""

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro publication lag configuration."""

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        """Return runtime qlib configuration."""

    def get_runtime_alpha_fixed_provider(self) -> str:
        """Return runtime fixed alpha provider selection."""

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        """Return runtime alpha pool mode."""

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        """Return runtime benchmark code."""


_provider: RuntimeSettingsProvider | None = None


def get_config_center_summary_service():
    """Return the config-center owned runtime settings service."""

    from apps.config_center.application.config_summary_service import (
        get_config_center_summary_service as load_config_center_summary_service,
    )

    return load_config_center_summary_service()


def _get_runtime_settings_source() -> RuntimeSettingsProvider | None:
    """Resolve the current runtime settings source.

    Prefer the config-center owned summary service so tests can monkeypatch the public
    bridge entrypoint. Fall back to the explicitly configured provider during
    early bootstrap or partial app initialization.
    """

    try:
        return get_config_center_summary_service()
    except Exception:
        return _provider


def configure_runtime_settings_provider(provider: RuntimeSettingsProvider) -> None:
    """Register the runtime settings provider from the owning app."""

    global _provider
    _provider = provider


def get_runtime_macro_index_metadata_map() -> dict[str, dict]:
    """Return runtime macro index metadata map from the configured provider."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return {}
    return provider.get_runtime_macro_index_metadata_map()


def get_runtime_macro_index_codes() -> list[str]:
    """Return runtime macro index codes from the configured provider."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return []
    return provider.get_runtime_macro_index_codes()


def get_runtime_macro_publication_lags() -> dict[str, dict]:
    """Return runtime macro publication lag configuration."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return {}
    return provider.get_runtime_macro_publication_lags()


def get_runtime_qlib_config() -> dict[str, object]:
    """Return runtime qlib configuration."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return {}
    return provider.get_runtime_qlib_config()


def get_runtime_alpha_fixed_provider() -> str:
    """Return runtime fixed alpha provider selection."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return ""
    return provider.get_runtime_alpha_fixed_provider()


def get_runtime_alpha_pool_mode(default_mode: str) -> str:
    """Return runtime alpha pool mode with caller-supplied fallback."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return default_mode
    return provider.get_runtime_alpha_pool_mode(default_mode)


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return runtime benchmark code with caller-supplied fallback."""

    provider = _get_runtime_settings_source()
    if provider is None:
        return default
    return provider.get_runtime_benchmark_code(key, default)
