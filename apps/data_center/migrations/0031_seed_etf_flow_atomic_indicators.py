"""Seed atomic ETF flow indicators used by market thermometer consensus."""

from django.db import migrations

ATOMIC_INDICATORS = [
    {
        "code": "CN_A_ETF_NET_FLOW_MAIN",
        "name_cn": "A股ETF主力资金净流入",
        "name_en": "China A-share ETF Main-force Net Flow",
        "description": "ETF main-force net inflow aggregated from ETF spot flow fields.",
    },
    {
        "code": "CN_A_ETF_SIZE_FLOW",
        "name_cn": "A股ETF规模变化资金流",
        "name_en": "China A-share ETF Size Delta Flow",
        "description": "ETF size-delta proxy flow derived from daily ETF total size.",
    },
]


def seed_etf_flow_atomic_indicators(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")

    for item in ATOMIC_INDICATORS:
        IndicatorCatalog.objects.update_or_create(
            code=item["code"],
            defaults={
                "name_cn": item["name_cn"],
                "name_en": item["name_en"],
                "description": item["description"],
                "default_unit": "元",
                "default_period_type": "D",
                "category": "market_heat",
                "is_active": True,
                "extra": {
                    "governance_scope": "macro",
                    "governance_sync_supported": False,
                    "thermometer_atomic_input": True,
                    "series_semantics": "flow_level",
                    "chart_policy": "period_bar",
                    "canonical_indicator": "CN_A_ETF_NET_FLOW",
                    "regime_input_policy": "direct_allowed",
                    "pulse_input_policy": "direct_allowed",
                },
            },
        )
        IndicatorUnitRule.objects.update_or_create(
            indicator_code=item["code"],
            source_type="",
            original_unit="",
            defaults={
                "dimension_key": "currency",
                "storage_unit": "元",
                "display_unit": "元",
                "multiplier_to_storage": 1.0,
                "is_active": True,
                "priority": 0,
                "description": "ETF flow atomic indicator canonical unit rule.",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0030_seed_market_thermometer_inputs"),
    ]

    operations = [
        migrations.RunPython(
            seed_etf_flow_atomic_indicators,
            migrations.RunPython.noop,
        ),
    ]
