import pytest

from apps.account.infrastructure.models import SystemSettingsModel


@pytest.mark.django_db
def test_system_settings_runtime_alpha_pool_mode_defaults_to_strict():
    settings = SystemSettingsModel.get_settings()

    assert settings.alpha_pool_mode == SystemSettingsModel.ALPHA_POOL_MODE_STRICT_VALUATION
    assert (
        SystemSettingsModel.get_runtime_alpha_pool_mode()
        == SystemSettingsModel.ALPHA_POOL_MODE_STRICT_VALUATION
    )


@pytest.mark.django_db
def test_system_settings_runtime_alpha_pool_mode_can_be_overridden():
    settings = SystemSettingsModel.get_settings()
    settings.alpha_pool_mode = SystemSettingsModel.ALPHA_POOL_MODE_PRICE_COVERED
    settings.save(update_fields=["alpha_pool_mode", "updated_at"])

    assert (
        SystemSettingsModel.get_runtime_alpha_pool_mode()
        == SystemSettingsModel.ALPHA_POOL_MODE_PRICE_COVERED
    )
