"""Seed market-thermometer indicator catalog and unit rules."""

from __future__ import annotations

from django.db import migrations


CHART_POLICY_BY_SEMANTICS = {
    "balance_level": "continuous_line",
    "flow_level": "period_bar",
    "index_level": "continuous_line",
    "monthly_level": "period_bar",
    "rate": "continuous_line",
}


MARKET_INDICATORS = [
    {
        "code": "CN_A_NEW_INVESTOR_ACCOUNTS",
        "name_cn": "A股新增投资者账户数",
        "name_en": "China A-share New Investor Accounts",
        "default_unit": "户",
        "default_period_type": "M",
        "category": "market_heat",
        "series_semantics": "monthly_level",
    },
    {
        "code": "CN_A_TOTAL_TURNOVER",
        "name_cn": "A股全市场成交额",
        "name_en": "China A-share Total Turnover",
        "default_unit": "元",
        "default_period_type": "D",
        "category": "market_heat",
        "series_semantics": "flow_level",
    },
    {
        "code": "CN_A_MARGIN_BALANCE",
        "name_cn": "A股融资余额",
        "name_en": "China A-share Margin Balance",
        "default_unit": "元",
        "default_period_type": "D",
        "category": "market_heat",
        "series_semantics": "balance_level",
    },
    {
        "code": "CN_A_ETF_NET_FLOW",
        "name_cn": "A股ETF资金净流入",
        "name_en": "China A-share ETF Net Flow",
        "default_unit": "元",
        "default_period_type": "D",
        "category": "market_heat",
        "series_semantics": "flow_level",
    },
    {
        "code": "CN_A_MARKET_NEWS_COUNT",
        "name_cn": "A股市场新闻热度",
        "name_en": "China A-share Market News Count",
        "default_unit": "篇",
        "default_period_type": "D",
        "category": "market_heat",
        "series_semantics": "flow_level",
    },
    {
        "code": "CN_A_MARKET_NEWS_SENTIMENT",
        "name_cn": "A股市场新闻情绪均值",
        "name_en": "China A-share Market News Sentiment",
        "default_unit": "score",
        "default_period_type": "D",
        "category": "market_heat",
        "series_semantics": "index_level",
    },
    {
        "code": "CN_A_MARKET_NEWS_POSITIVE_RATIO",
        "name_cn": "A股市场新闻正向占比",
        "name_en": "China A-share Market News Positive Ratio",
        "default_unit": "ratio",
        "default_period_type": "D",
        "category": "market_heat",
        "series_semantics": "rate",
    },
]


UNIT_RULES = [
    {
        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
        "dimension_key": "count",
        "storage_unit": "户",
        "display_unit": "户",
    },
    {
        "indicator_code": "CN_A_TOTAL_TURNOVER",
        "dimension_key": "currency",
        "storage_unit": "元",
        "display_unit": "元",
    },
    {
        "indicator_code": "CN_A_MARGIN_BALANCE",
        "dimension_key": "currency",
        "storage_unit": "元",
        "display_unit": "元",
    },
    {
        "indicator_code": "CN_A_ETF_NET_FLOW",
        "dimension_key": "currency",
        "storage_unit": "元",
        "display_unit": "元",
    },
    {
        "indicator_code": "CN_A_MARKET_NEWS_COUNT",
        "dimension_key": "count",
        "storage_unit": "篇",
        "display_unit": "篇",
    },
    {
        "indicator_code": "CN_A_MARKET_NEWS_SENTIMENT",
        "dimension_key": "score",
        "storage_unit": "score",
        "display_unit": "score",
    },
    {
        "indicator_code": "CN_A_MARKET_NEWS_POSITIVE_RATIO",
        "dimension_key": "ratio",
        "storage_unit": "ratio",
        "display_unit": "ratio",
    },
]


def seed_market_thermometer_inputs(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")

    for item in MARKET_INDICATORS:
        series_semantics = item["series_semantics"]
        indicator, _ = IndicatorCatalog.objects.update_or_create(
            code=item["code"],
            defaults={
                "name_cn": item["name_cn"],
                "name_en": item["name_en"],
                "description": "Market thermometer governed input.",
                "default_unit": item["default_unit"],
                "default_period_type": item["default_period_type"],
                "category": item["category"],
                "is_active": True,
                "extra": {
                    "governance_scope": "macro",
                    "governance_sync_supported": False,
                    "thermometer_component": True,
                    "series_semantics": series_semantics,
                    "chart_policy": CHART_POLICY_BY_SEMANTICS[series_semantics],
                    "chart_reset_frequency": "",
                    "chart_segment_basis": "",
                    "regime_input_policy": "direct_allowed",
                    "pulse_input_policy": "direct_allowed",
                },
            },
        )
        indicator.save()

    for rule in UNIT_RULES:
        IndicatorUnitRule.objects.update_or_create(
            indicator_code=rule["indicator_code"],
            source_type="",
            original_unit="",
            defaults={
                "dimension_key": rule["dimension_key"],
                "storage_unit": rule["storage_unit"],
                "display_unit": rule["display_unit"],
                "multiplier_to_storage": 1.0,
                "is_active": True,
                "priority": 0,
                "description": "Market thermometer canonical unit rule.",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0029_marketthermometerconfigmodel_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_market_thermometer_inputs,
            migrations.RunPython.noop,
        ),
    ]
