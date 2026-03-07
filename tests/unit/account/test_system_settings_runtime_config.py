import pytest

from apps.account.infrastructure.models import SystemSettingsModel
from apps.macro.application.indicator_service import IndicatorService, IndicatorUnitService


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
