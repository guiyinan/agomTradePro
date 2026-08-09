from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from apps.data_center.infrastructure.models import IndicatorCatalogModel, IndicatorUnitRuleModel
from apps.macro.application.indicator_service import IndicatorService, IndicatorUnitRuleService
from core.application.config_center import get_system_settings_summary
from core.context_processors import get_market_visuals
from core.integration.runtime_settings import (
    get_runtime_macro_index_metadata_map,
    get_runtime_macro_publication_lags,
)


@pytest.mark.django_db
def test_missing_market_runtime_config_fails_closed():
    payload = get_system_settings_summary()
    summary = payload["summary"]

    assert summary["benchmark_map_size"] == 0
    assert summary["asset_proxy_map_size"] == 0
    assert payload["status"] == "blocked"


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
    runtime_metadata = get_runtime_macro_index_metadata_map()

    assert metadata["TEST.INDEX"]["name"] == "测试指数"
    assert IndicatorUnitRuleService.get_unit_for_indicator("TEST.INDEX") == "点"
    assert get_runtime_macro_publication_lags()["TEST.INDEX"]["days"] == 2
    assert runtime_metadata["TEST.INDEX"]["default_period_type"] == "D"


@pytest.mark.django_db
def test_macro_runtime_metadata_exposes_schedule_and_period_override_fields():
    IndicatorCatalogModel.objects.update_or_create(
        code="TEST.SCHEDULED",
        defaults={
            "name_cn": "测试调度指标",
            "name_en": "Test Scheduled Indicator",
            "category": "测试",
            "description": "用于测试运行时调度元数据",
            "default_period_type": "Q",
            "is_active": True,
            "extra": {
                "schedule_frequency": "quarterly",
                "schedule_day_of_month": 20,
                "schedule_release_months": [1, 4, 7, 10],
                "publication_lag_days": 20,
                "publication_lag_description": "季后20日",
                "orm_period_type_override": "Q",
                "domain_period_type_override": "Q",
            },
        },
    )

    runtime_metadata = get_runtime_macro_index_metadata_map()

    assert runtime_metadata["TEST.SCHEDULED"]["schedule_frequency"] == "quarterly"
    assert runtime_metadata["TEST.SCHEDULED"]["schedule_day_of_month"] == 20
    assert runtime_metadata["TEST.SCHEDULED"]["schedule_release_months"] == [1, 4, 7, 10]
    assert runtime_metadata["TEST.SCHEDULED"]["orm_period_type_override"] == "Q"
    assert runtime_metadata["TEST.SCHEDULED"]["domain_period_type_override"] == "Q"


@pytest.mark.django_db
def test_missing_market_runtime_uses_safe_a_share_visual_tokens():
    tokens = get_market_visuals(request=None)["market_visuals"]

    assert tokens["convention"] == "cn_a_share"
    assert tokens["rise"] == "var(--color-error)"
    assert tokens["fall"] == "var(--color-success)"
    assert tokens["rise_soft"] == "var(--color-error-light)"
    assert tokens["fall_soft"] == "var(--color-success-light)"
    assert tokens["inflow"] == "var(--color-error)"
    assert tokens["outflow"] == "var(--color-success)"


@pytest.mark.django_db
def test_runtime_market_visual_tokens_support_canonical_us_convention(monkeypatch):
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_market_runtime_config",
        lambda environment: {
            "market_color_convention": "us_market",
            "benchmark_code_map": {},
            "asset_proxy_code_map": {},
        },
    )
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_account_runtime_config",
        lambda environment: {
            "default_mcp_enabled": False,
            "allow_token_plaintext_view": False,
        },
    )

    summary = get_system_settings_summary()["summary"]
    context = get_market_visuals(request=None)["market_visuals"]

    assert summary["market_color_convention"] == "us_market"
    assert summary["market_color_label"] == "美股绿涨红跌"
    assert context["rise"] == "var(--color-success)"
    assert context["fall"] == "var(--color-error)"
    assert context["rise_strong"] == "var(--color-success-dark)"
    assert context["fall_strong"] == "var(--color-error-dark)"
    assert context["convention"] == "us_market"


@pytest.mark.django_db
def test_get_market_visuals_uses_default_tokens_for_anonymous_auth_pages():
    factory = RequestFactory()
    request = factory.get("/account/login/")
    request.user = AnonymousUser()

    with patch(
        "apps.account.application.config_summary_service.get_account_config_summary_service",
        side_effect=AssertionError("auth pages should not query runtime summary service"),
    ):
        context = get_market_visuals(request)["market_visuals"]

    assert context["convention"] == "cn_a_share"
    assert context["rise"] == "var(--color-error)"
    assert context["fall"] == "var(--color-success)"
