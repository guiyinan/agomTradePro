"""Quarantine high-frequency facts published under incorrect indicator semantics."""

from __future__ import annotations

from typing import Any

from django.db import migrations

INDICATOR_CODES = ("CN_NHCI", "CN_FX_CENTER")
MIGRATION_MARKER = "0044_quarantine_mislabeled_high_frequency_facts"
PRIOR_QUALITY_KEY = "quality_before_high_frequency_semantics_correction"
PRIOR_SYNC_KEY = "sync_supported_before_high_frequency_semantics_correction"


def quarantine_mislabeled_facts(apps: Any, schema_editor: Any) -> None:
    """Disable unsupported sync and quarantine facts from incompatible AKShare series."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    macro_fact = apps.get_model("data_center", "MacroFactModel")

    for catalog in indicator_catalog._default_manager.filter(code__in=INDICATOR_CODES):
        extra = dict(catalog.extra or {})
        extra.setdefault(
            PRIOR_SYNC_KEY,
            {
                "present": "governance_sync_supported" in extra,
                "value": extra.get("governance_sync_supported"),
            },
        )
        extra["governance_sync_supported"] = False
        extra["sync_disabled_by_migration"] = MIGRATION_MARKER
        extra["sync_disabled_reason"] = (
            "The configured AKShare endpoint does not publish the indicator semantics "
            "declared by this catalog entry."
        )
        catalog.extra = extra
        catalog.save(update_fields=["extra"])

    pending = []
    queryset = macro_fact._default_manager.filter(
        indicator_code__in=INDICATOR_CODES,
        source__iexact="akshare",
    ).exclude(quality="error")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        extra.setdefault(PRIOR_QUALITY_KEY, fact.quality)
        extra["invalidated_by_migration"] = MIGRATION_MARKER
        extra["invalidated_reason"] = (
            "CN_NHCI was sourced from a different commodity index or CN_FX_CENTER "
            "was sourced from a spot bid quote rather than central parity."
        )
        fact.quality = "error"
        fact.extra = extra
        pending.append(fact)
    if pending:
        macro_fact._default_manager.bulk_update(
            pending,
            ["quality", "extra"],
            batch_size=500,
        )


def restore_mislabeled_facts(apps: Any, schema_editor: Any) -> None:
    """Restore catalog flags and fact qualities changed by this migration."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    macro_fact = apps.get_model("data_center", "MacroFactModel")

    for catalog in indicator_catalog._default_manager.filter(code__in=INDICATOR_CODES):
        extra = dict(catalog.extra or {})
        extra.pop("sync_disabled_by_migration", None)
        extra.pop("sync_disabled_reason", None)
        prior_sync = extra.pop(PRIOR_SYNC_KEY, None)
        if isinstance(prior_sync, dict) and prior_sync.get("present") is True:
            extra["governance_sync_supported"] = prior_sync.get("value")
        else:
            extra.pop("governance_sync_supported", None)
        catalog.extra = extra
        catalog.save(update_fields=["extra"])

    pending = []
    queryset = macro_fact._default_manager.filter(
        indicator_code__in=INDICATOR_CODES,
        source__iexact="akshare",
        extra__invalidated_by_migration=MIGRATION_MARKER,
    )
    valid_qualities = {"valid", "stale", "estimated", "error", "missing"}
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        prior_quality = str(extra.pop(PRIOR_QUALITY_KEY, "valid"))
        extra.pop("invalidated_by_migration", None)
        extra.pop("invalidated_reason", None)
        fact.quality = prior_quality if prior_quality in valid_qualities else "valid"
        fact.extra = extra
        pending.append(fact)
    if pending:
        macro_fact._default_manager.bulk_update(
            pending,
            ["quality", "extra"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("data_center", "0043_govern_manual_pmi_subitem_provenance")]

    operations = [
        migrations.RunPython(
            quarantine_mislabeled_facts,
            restore_mislabeled_facts,
        )
    ]
