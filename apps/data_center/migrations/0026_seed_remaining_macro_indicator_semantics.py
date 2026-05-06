"""Seed explicit semantics metadata for remaining macro indicators."""

from __future__ import annotations

from django.db import migrations

from apps.data_center.infrastructure.seed_data.macro_indicator_governance import (
    INDICATOR_METADATA_UPDATES,
    merge_governance_extra,
)


def apply_indicator_governance(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for code, payload in INDICATOR_METADATA_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue

        indicator.name_cn = payload["name_cn"]
        indicator.description = payload["description"]
        indicator.extra = merge_governance_extra(indicator.extra, payload["extra"])
        indicator.save(update_fields=["name_cn", "description", "extra"])

    for indicator in IndicatorCatalog.objects.filter(is_active=True):
        extra = dict(indicator.extra or {})
        if not extra.get("series_semantics"):
            continue
        merged_extra = merge_governance_extra(extra, {})
        if indicator.extra == merged_extra:
            continue
        indicator.extra = merged_extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0025_seed_semantics_driven_chart_policies"),
    ]

    operations = [
        migrations.RunPython(apply_indicator_governance, migrations.RunPython.noop),
    ]
