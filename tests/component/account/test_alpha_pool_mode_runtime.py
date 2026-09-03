import pytest

from apps.config_center.application.runtime_public import get_active_alpha_runtime_config
from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository
from apps.data_center.application.interface_services import save_provider_settings_payload
from tests.support.runtime_config import configure_critical_runtime


@pytest.mark.django_db
def test_alpha_runtime_missing_profile_fails_closed():
    assert get_active_alpha_runtime_config("development") is None


@pytest.mark.django_db
def test_alpha_runtime_pool_mode_can_be_configured_canonically():
    configure_critical_runtime()
    save_provider_settings_payload(
        default_source="akshare",
        enable_failover=True,
        failover_tolerance=0.01,
        actor="alpha-runtime-test",
    )
    ConfigCenterSettingsRepository().update_runtime_config(
        {
            "alpha_fixed_provider": "cache",
            "alpha_pool_mode": "market",
        },
        actor="alpha-runtime-test",
    )

    assert get_active_alpha_runtime_config("development") == {
        "alpha_fixed_provider": "cache",
        "alpha_pool_mode": "market",
    }
