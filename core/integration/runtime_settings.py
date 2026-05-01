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


def configure_runtime_settings_provider(provider: RuntimeSettingsProvider) -> None:
    """Register the runtime settings provider from the owning app."""

    global _provider
    _provider = provider


def get_runtime_macro_index_metadata_map() -> dict[str, dict]:
    """Return runtime macro index metadata map from the configured provider."""

    if _provider is None:
        return {}
    return _provider.get_runtime_macro_index_metadata_map()


def get_runtime_macro_index_codes() -> list[str]:
    """Return runtime macro index codes from the configured provider."""

    if _provider is None:
        return []
    return _provider.get_runtime_macro_index_codes()


def get_runtime_macro_publication_lags() -> dict[str, dict]:
    """Return runtime macro publication lag configuration."""

    if _provider is None:
        return {}
    return _provider.get_runtime_macro_publication_lags()


def get_runtime_qlib_config() -> dict[str, object]:
    """Return runtime qlib configuration."""

    if _provider is None:
        return {}
    return _provider.get_runtime_qlib_config()


def get_runtime_alpha_fixed_provider() -> str:
    """Return runtime fixed alpha provider selection."""

    if _provider is None:
        return ""
    return _provider.get_runtime_alpha_fixed_provider()


def get_runtime_alpha_pool_mode(default_mode: str) -> str:
    """Return runtime alpha pool mode with caller-supplied fallback."""

    if _provider is None:
        return default_mode
    return _provider.get_runtime_alpha_pool_mode(default_mode)


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return runtime benchmark code with caller-supplied fallback."""

    if _provider is None:
        return default
    return _provider.get_runtime_benchmark_code(key, default)
