"""Seed governed A-share trading-behavior indicators."""

from __future__ import annotations

from typing import Any

from django.db import migrations

INDICATORS = (
    (
        "CN_A_ADVANCE_COUNT",
        "A股上涨家数",
        "China A-share Advance Count",
        "日度上涨股票家数，用于观察A股市场宽度；缺数时不得补零。",
    ),
    (
        "CN_A_DECLINE_COUNT",
        "A股下跌家数",
        "China A-share Decline Count",
        "日度下跌股票家数，用于观察A股市场宽度；缺数时不得补零。",
    ),
    (
        "CN_A_LIMIT_UP_COUNT",
        "A股涨停家数",
        "China A-share Limit-up Count",
        "日度涨停股票家数，用于观察A股交易热度；缺数时不得补零。",
    ),
    (
        "CN_A_LIMIT_DOWN_COUNT",
        "A股跌停家数",
        "China A-share Limit-down Count",
        "日度跌停股票家数，用于观察A股交易压力；缺数时不得补零。",
    ),
)


def seed_a_share_behavior_indicators(apps: Any, schema_editor: Any) -> None:
    """Create catalog and canonical count-unit rules idempotently."""

    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    for code, name_cn, name_en, description in INDICATORS:
        IndicatorCatalog.objects.update_or_create(
            code=code,
            defaults={
                "name_cn": name_cn,
                "name_en": name_en,
                "description": description,
                "default_unit": "家",
                "default_period_type": "D",
                "category": "market_heat",
                "is_active": True,
                "extra": {
                    "governance_scope": "macro",
                    "governance_sync_supported": False,
                    "trading_behavior_component": True,
                    "series_semantics": "level",
                    "paired_indicator_code": "",
                    "chart_policy": "continuous_line",
                    "chart_reset_frequency": "",
                    "chart_segment_basis": "",
                    "regime_input_policy": "direct_allowed",
                    "pulse_input_policy": "direct_allowed",
                },
            },
        )
        IndicatorUnitRule.objects.update_or_create(
            indicator_code=code,
            source_type="",
            original_unit="",
            defaults={
                "dimension_key": "count",
                "storage_unit": "家",
                "display_unit": "家",
                "multiplier_to_storage": 1.0,
                "is_active": True,
                "priority": 0,
                "description": "A-share trading-behavior canonical count rule.",
            },
        )


def disable_a_share_behavior_indicators(apps: Any, schema_editor: Any) -> None:
    """Disable catalog entries while retaining already collected facts."""

    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorCatalog.objects.filter(code__in=[item[0] for item in INDICATORS]).update(
        is_active=False
    )


class Migration(migrations.Migration):
    dependencies = [("data_center", "0047_quarantine_weekly_proxy_facts")]

    operations = [
        migrations.RunPython(
            seed_a_share_behavior_indicators,
            disable_a_share_behavior_indicators,
        )
    ]
