"""Persist reset-cycle chart metadata for cumulative macro indicators."""

from __future__ import annotations

from django.db import migrations

from apps.data_center.infrastructure.seed_data.macro_indicator_governance import (
    merge_governance_extra,
)


def apply_reset_chart_runtime_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

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
        ("data_center", "0026_seed_remaining_macro_indicator_semantics"),
    ]

    operations = [
        migrations.RunPython(
            apply_reset_chart_runtime_metadata,
            migrations.RunPython.noop,
        ),
    ]
