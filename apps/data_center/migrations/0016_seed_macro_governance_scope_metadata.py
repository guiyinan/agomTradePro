"""Seed macro governance scope metadata into IndicatorCatalog.extra."""

from django.db import migrations


GOVERNANCE_SCOPE = "macro_console"

GOVERNANCE_METADATA_UPDATES = {
    "CN_GDP": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_GDP_YOY": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_M2": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_M2_YOY": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_CPI": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_CPI_YOY": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": False},
    "CN_CPI_NATIONAL_YOY": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_PPI": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_PPI_YOY": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_RETAIL_SALES": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_RETAIL_SALES_YOY": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_VALUE_ADDED": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_FIXED_INVESTMENT": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_FAI_YOY": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_EXPORTS": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_EXPORT_YOY": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_IMPORTS": {"governance_scope": GOVERNANCE_SCOPE, "governance_sync_supported": True},
    "CN_IMPORT_YOY": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_FX_RESERVES": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_SOCIAL_FINANCING": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
    "CN_SOCIAL_FINANCING_YOY": {
        "governance_scope": GOVERNANCE_SCOPE,
        "governance_sync_supported": True,
    },
}


def apply_governance_scope_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, extra_updates in GOVERNANCE_METADATA_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.update(extra_updates)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


def revert_governance_scope_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, extra_updates in GOVERNANCE_METADATA_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        for key in extra_updates:
            extra.pop(key, None)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0015_seed_macro_runtime_config"),
    ]

    operations = [
        migrations.RunPython(
            apply_governance_scope_metadata,
            revert_governance_scope_metadata,
        ),
    ]
