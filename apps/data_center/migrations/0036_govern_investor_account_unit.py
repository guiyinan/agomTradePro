"""Normalize AKShare investor-account counts from ten-thousand households."""

from django.db import migrations


def add_akshare_investor_account_rule(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    IndicatorUnitRule.objects.update_or_create(
        indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
        source_type="akshare",
        original_unit="万户",
        defaults={
            "dimension_key": "count",
            "storage_unit": "户",
            "display_unit": "户",
            "multiplier_to_storage": 10_000.0,
            "is_active": True,
            "priority": 100,
            "description": "AKShare investor account counts are published in ten-thousand households.",
        },
    )


def remove_akshare_investor_account_rule(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    IndicatorUnitRule.objects.filter(
        indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
        source_type="akshare",
        original_unit="万户",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("data_center", "0035_govern_tushare_turnover_unit")]

    operations = [
        migrations.RunPython(
            add_akshare_investor_account_rule,
            remove_akshare_investor_account_rule,
        )
    ]
