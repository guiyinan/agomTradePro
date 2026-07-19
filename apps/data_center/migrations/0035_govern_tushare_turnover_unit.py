"""Route Tushare turnover conversion through the canonical unit-rule table."""

from django.db import migrations


def add_tushare_turnover_rule(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    IndicatorUnitRule.objects.update_or_create(
        indicator_code="CN_A_TOTAL_TURNOVER",
        source_type="tushare",
        original_unit="千元",
        defaults={
            "dimension_key": "currency",
            "storage_unit": "元",
            "display_unit": "元",
            "multiplier_to_storage": 1000.0,
            "is_active": True,
            "priority": 100,
            "description": "Tushare A-share daily amount is published in thousand CNY.",
        },
    )


def remove_tushare_turnover_rule(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    IndicatorUnitRule.objects.filter(
        indicator_code="CN_A_TOTAL_TURNOVER",
        source_type="tushare",
        original_unit="千元",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("data_center", "0034_govern_turnover_decision_source")]

    operations = [migrations.RunPython(add_tushare_turnover_rule, remove_tushare_turnover_rule)]
