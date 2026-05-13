"""Config-center owned runtime and summary service."""

from __future__ import annotations

from typing import Any, Protocol


class ConfigCenterSummaryRepository(Protocol):
    def get_system_settings_summary(self) -> dict[str, Any]:
        """Return singleton system-settings summary."""

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro indicator metadata map."""

    def get_runtime_macro_index_codes(self) -> list[str]:
        """Return runtime macro indicator codes."""

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro publication lag configuration."""

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        """Return runtime qlib config."""

    def get_runtime_alpha_fixed_provider(self) -> str:
        """Return runtime fixed alpha provider."""

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        """Return runtime alpha pool mode."""

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        """Return runtime benchmark code."""

    def get_runtime_asset_proxy_map(self) -> dict[str, str]:
        """Return runtime asset proxy map."""


class ConfigCenterSummaryService:
    def __init__(self, repository: ConfigCenterSummaryRepository):
        self.repository = repository

    def get_system_settings_summary(self) -> dict[str, Any]:
        return self.repository.get_system_settings_summary()

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        return self.repository.get_runtime_macro_index_metadata_map()

    def get_runtime_macro_index_codes(self) -> list[str]:
        return self.repository.get_runtime_macro_index_codes()

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        return self.repository.get_runtime_macro_publication_lags()

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        return self.repository.get_runtime_qlib_config()

    def get_runtime_alpha_fixed_provider(self) -> str:
        return self.repository.get_runtime_alpha_fixed_provider()

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        return self.repository.get_runtime_alpha_pool_mode(default_mode)

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        return self.repository.get_runtime_benchmark_code(key, default)

    def get_runtime_asset_proxy_map(self) -> dict[str, str]:
        return self.repository.get_runtime_asset_proxy_map()


_config_center_summary_repository: ConfigCenterSummaryRepository | None = None


def configure_config_center_summary_repository(
    repository: ConfigCenterSummaryRepository,
) -> None:
    global _config_center_summary_repository
    _config_center_summary_repository = repository


def get_config_center_summary_service() -> ConfigCenterSummaryService:
    if _config_center_summary_repository is None:
        raise RuntimeError("Config center summary repository is not configured")
    return ConfigCenterSummaryService(_config_center_summary_repository)

