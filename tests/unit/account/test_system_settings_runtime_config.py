import pytest

from apps.account.infrastructure.models import SystemSettingsModel
from apps.macro.application.indicator_service import IndicatorService, IndicatorUnitService
from core.application.config_center import get_system_settings_summary
from core.context_processors import get_market_visuals


@pytest.mark.django_db
def test_system_settings_runtime_market_config_defaults():
    settings = SystemSettingsModel.get_settings()

    assert settings.get_benchmark_code("equity_default_index") == "000300.SH"
    assert settings.get_asset_proxy_code("a_share_growth") == "000300.SH"
    assert "000300.SH" in settings.get_macro_index_codes()


@pytest.mark.django_db
def test_macro_indicator_metadata_is_loaded_from_system_settings():
    settings = SystemSettingsModel.get_settings()
    settings.macro_index_catalog = [
        {
            "code": "TEST.INDEX",
            "name": "测试指数",
            "name_en": "Test Index",
            "category": "股票",
            "unit": "点",
            "description": "用于测试的指数配置",
            "publication_lag_days": 2,
            "publication_lag_description": "T+2",
        }
    ]
    settings.save(update_fields=["macro_index_catalog", "updated_at"])

    metadata = IndicatorService.get_indicator_metadata_map()

    assert metadata["TEST.INDEX"]["name"] == "测试指数"
    assert IndicatorUnitService.get_unit_for_indicator("TEST.INDEX") == "点"
    assert SystemSettingsModel.get_runtime_macro_publication_lags()["TEST.INDEX"]["days"] == 2


@pytest.mark.django_db
def test_system_settings_runtime_market_visual_tokens_default_to_a_share():
    settings = SystemSettingsModel.get_settings()

    tokens = settings.get_market_visual_tokens()

    assert settings.market_color_convention == "cn_a_share"
    assert tokens["rise"] == "var(--color-error)"
    assert tokens["fall"] == "var(--color-success)"
    assert tokens["rise_soft"] == "var(--color-error-light)"
    assert tokens["fall_soft"] == "var(--color-success-light)"
    assert tokens["inflow"] == "var(--color-error)"
    assert tokens["outflow"] == "var(--color-success)"


@pytest.mark.django_db
def test_system_settings_runtime_market_visual_tokens_support_us_convention():
    settings = SystemSettingsModel.get_settings()
    settings.market_color_convention = "us_market"
    settings.save(update_fields=["market_color_convention", "updated_at"])

    tokens = SystemSettingsModel.get_runtime_market_visual_tokens()
    summary = get_system_settings_summary()["summary"]
    context = get_market_visuals(request=None)["market_visuals"]

    assert tokens["rise"] == "var(--color-success)"
    assert tokens["fall"] == "var(--color-error)"
    assert tokens["rise_strong"] == "var(--color-success-dark)"
    assert tokens["fall_strong"] == "var(--color-error-dark)"
    assert summary["market_color_convention"] == "us_market"
    assert summary["market_color_label"] == "美股绿涨红跌"
    assert context["convention"] == "us_market"
