"""Seed chart governance metadata for macro indicators with special display rules."""

from django.db import migrations

CHART_POLICY_METADATA = {
    "CN_GDP": {"chart_policy": "yearly_segmented"},
    "CN_FIXED_INVESTMENT": {"chart_policy": "yearly_segmented"},
}


def apply_chart_policies(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for code, extra_fields in CHART_POLICY_METADATA.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue

        merged_extra = dict(indicator.extra or {})
        merged_extra.update(extra_fields)
        indicator.extra = merged_extra
        indicator.save(update_fields=["extra"])


def revert_chart_policies(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for code, extra_fields in CHART_POLICY_METADATA.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue

        reverted_extra = dict(indicator.extra or {})
        for key in extra_fields:
            reverted_extra.pop(key, None)
        indicator.extra = reverted_extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0023_create_publisher_catalog"),
    ]

    operations = [
        migrations.RunPython(apply_chart_policies, revert_chart_policies),
    ]
