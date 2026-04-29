import pytest
from django.conf import settings as django_settings

from apps.account.infrastructure.models import SystemSettingsModel
from apps.data_center.infrastructure.models import IndicatorCatalogModel, IndicatorUnitRuleModel
from apps.macro.application.indicator_service import IndicatorService, IndicatorUnitRuleService
from core.application.config_center import get_system_settings_summary
from core.integration.runtime_settings import get_runtime_macro_publication_lags
from core.context_processors import get_market_visuals


@pytest.mark.django_db
def test_system_settings_runtime_market_config_defaults():
    settings = SystemSettingsModel.get_settings()

    assert settings.get_benchmark_code("equity_default_index") == "000300.SH"
    assert settings.get_asset_proxy_code("a_share_growth") == "000300.SH"


@pytest.mark.django_db
def test_macro_indicator_metadata_is_loaded_from_system_settings():
    IndicatorCatalogModel.objects.update_or_create(
        code="TEST.INDEX",
        defaults={
            "name_cn": "测试指数",
            "name_en": "Test Index",
            "category": "股票",
            "description": "用于测试的指数配置",
            "default_period_type": "D",
            "is_active": True,
            "extra": {
                "publication_lag_days": 2,
                "publication_lag_description": "T+2",
            },
        },
    )
    IndicatorUnitRuleModel.objects.update_or_create(
        indicator_code="TEST.INDEX",
        source_type="",
        original_unit="点",
        defaults={
            "dimension_key": "index",
            "storage_unit": "点",
            "display_unit": "点",
            "multiplier_to_storage": 1.0,
            "is_active": True,
            "priority": 10,
            "description": "测试指数单位规则",
        },
    )

    metadata = IndicatorService.get_indicator_metadata_map()

    assert metadata["TEST.INDEX"]["name"] == "测试指数"
    assert IndicatorUnitRuleService.get_unit_for_indicator("TEST.INDEX") == "点"
    assert get_runtime_macro_publication_lags()["TEST.INDEX"]["days"] == 2


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


@pytest.mark.django_db
def test_qlib_runtime_paths_fall_back_when_persisted_path_is_not_local(tmp_path):
    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    original_qlib_settings = dict(django_settings.QLIB_SETTINGS)
    django_settings.QLIB_SETTINGS = {
        **original_qlib_settings,
        "provider_uri": str(provider_dir),
        "model_path": str(model_dir),
    }
    try:
        settings = SystemSettingsModel.get_settings()
        settings.qlib_enabled = True
        settings.qlib_provider_uri = r"Z:\missing\qlib\cn_data"
        settings.qlib_model_path = r"Z:\missing\qlib\models"
        settings.save(
            update_fields=[
                "qlib_enabled",
                "qlib_provider_uri",
                "qlib_model_path",
                "updated_at",
            ]
        )

        runtime_config = SystemSettingsModel.get_runtime_qlib_config()
    finally:
        django_settings.QLIB_SETTINGS = original_qlib_settings

    assert runtime_config["provider_uri"] == str(provider_dir)
    assert runtime_config["model_path"] == str(model_dir)
    assert runtime_config["is_configured"] is True
