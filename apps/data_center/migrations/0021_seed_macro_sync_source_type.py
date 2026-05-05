"""Seed governance sync source metadata for governed macro indicators."""

from django.db import migrations


DEFAULT_SYNC_SOURCE_TYPE = "akshare"
GOVERNANCE_SCOPE = "macro_console"


def apply_sync_source_type(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for indicator in IndicatorCatalog.objects.filter(is_active=True):
        extra = dict(indicator.extra or {})
        if str(extra.get("governance_scope") or "").strip() != GOVERNANCE_SCOPE:
            continue
        if extra.get("governance_sync_supported") is not True:
            continue
        extra["governance_sync_source_type"] = DEFAULT_SYNC_SOURCE_TYPE
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


def revert_sync_source_type(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for indicator in IndicatorCatalog.objects.filter(is_active=True):
        extra = dict(indicator.extra or {})
        if str(extra.get("governance_scope") or "").strip() != GOVERNANCE_SCOPE:
            continue
        if extra.get("governance_sync_source_type") != DEFAULT_SYNC_SOURCE_TYPE:
            continue
        extra.pop("governance_sync_source_type", None)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0020_enable_dr007_macro_sync_supported"),
    ]

    operations = [
        migrations.RunPython(
            apply_sync_source_type,
            revert_sync_source_type,
        ),
    ]
