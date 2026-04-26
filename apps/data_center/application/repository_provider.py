"""Data center repository providers for application consumers."""

from __future__ import annotations

from apps.data_center.domain.entities import DataProviderSettings, ProviderConfig
from apps.data_center.infrastructure.connection_tester import run_connection_test
from apps.data_center.infrastructure.providers import (
    DataProviderSettingsRepository,
    MacroFactRepository,
    ProviderConfigRepository,
)


def get_macro_fact_repository() -> MacroFactRepository:
    """Return the default macro fact repository."""

    return MacroFactRepository()


def get_data_provider_settings_repository() -> DataProviderSettingsRepository:
    """Return the default data-provider settings repository."""

    return DataProviderSettingsRepository()


def get_provider_config_repository() -> ProviderConfigRepository:
    """Return the default provider-config repository."""

    return ProviderConfigRepository()


def load_data_provider_settings() -> DataProviderSettings:
    """Load the singleton provider settings via the application boundary."""

    return get_data_provider_settings_repository().load()


def list_active_provider_configs() -> list[ProviderConfig]:
    """List active provider configs ordered by priority."""

    return get_provider_config_repository().list_active()


def run_data_center_connection_test(*args, **kwargs):
    """Run a data-center connection test via the infrastructure implementation."""

    return run_connection_test(*args, **kwargs)
