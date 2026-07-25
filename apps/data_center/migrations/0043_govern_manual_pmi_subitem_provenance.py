"""Govern manual PMI sub-item provenance and repair legacy source labels."""

from __future__ import annotations

from typing import Any

from django.db import migrations

INDICATOR_CODES = (
    "CN_PMI_NEW_ORDER",
    "CN_PMI_INVENTORY",
    "CN_PMI_RAW_MAT",
    "CN_PMI_PURCHASE",
    "CN_PMI_PRODUCTION",
    "CN_PMI_EMPLOYMENT",
)
MANUAL_SOURCE = "manual_pmi_subitems"
MIGRATION_MARKER = "0043_govern_manual_pmi_subitem_provenance"


def govern_manual_pmi_provenance(apps: Any, schema_editor: Any) -> None:
    """Declare official manual-file provenance and repair mislabeled facts."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    macro_fact = apps.get_model("data_center", "MacroFactModel")

    for catalog in indicator_catalog._default_manager.filter(code__in=INDICATOR_CODES):
        extra = dict(catalog.extra or {})
        extra.update(
            {
                "provenance_class": "official",
                "publisher": "国家统计局",
                "publisher_code": "NBS",
                "publisher_codes": ["NBS"],
                "access_channel": "manual_file",
            }
        )
        catalog.extra = extra
        catalog.save(update_fields=["extra"])

    pending = []
    queryset = macro_fact._default_manager.filter(
        indicator_code__in=INDICATOR_CODES,
        source="akshare",
    ).order_by("id")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        conflict_exists = macro_fact._default_manager.filter(
            indicator_code=fact.indicator_code,
            reporting_period=fact.reporting_period,
            source=MANUAL_SOURCE,
            revision_number=fact.revision_number,
        ).exists()
        extra["provenance_repaired_by_migration"] = MIGRATION_MARKER
        extra["source_before_provenance_repair"] = fact.source
        extra["quality_before_provenance_repair"] = fact.quality
        extra["source_type"] = "manual"
        extra["access_channel"] = "manual_file"
        if conflict_exists:
            fact.quality = "error"
            extra["provenance_repair_conflict"] = True
            extra["provenance_repair_reason"] = (
                "A canonical manual PMI fact already exists for this natural key."
            )
        else:
            fact.source = MANUAL_SOURCE
        fact.extra = extra
        pending.append(fact)
    if pending:
        macro_fact._default_manager.bulk_update(
            pending,
            ["source", "quality", "extra"],
            batch_size=500,
        )


def restore_manual_pmi_provenance(apps: Any, schema_editor: Any) -> None:
    """Restore catalog metadata and facts changed by this migration."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    macro_fact = apps.get_model("data_center", "MacroFactModel")

    for catalog in indicator_catalog._default_manager.filter(code__in=INDICATOR_CODES):
        extra = dict(catalog.extra or {})
        for key in (
            "provenance_class",
            "publisher",
            "publisher_code",
            "publisher_codes",
            "access_channel",
        ):
            extra.pop(key, None)
        catalog.extra = extra
        catalog.save(update_fields=["extra"])

    pending = []
    queryset = macro_fact._default_manager.filter(
        indicator_code__in=INDICATOR_CODES,
        extra__provenance_repaired_by_migration=MIGRATION_MARKER,
    ).order_by("id")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        prior_source = str(extra.pop("source_before_provenance_repair", "akshare"))
        prior_quality = str(extra.pop("quality_before_provenance_repair", "valid"))
        had_conflict = bool(extra.pop("provenance_repair_conflict", False))
        extra.pop("provenance_repair_reason", None)
        extra.pop("provenance_repaired_by_migration", None)
        extra.pop("source_type", None)
        extra.pop("access_channel", None)
        if not had_conflict:
            fact.source = prior_source
        else:
            fact.quality = prior_quality
        fact.extra = extra
        pending.append(fact)
    if pending:
        macro_fact._default_manager.bulk_update(
            pending,
            ["source", "quality", "extra"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("data_center", "0042_govern_akshare_m2_unit")]

    operations = [
        migrations.RunPython(
            govern_manual_pmi_provenance,
            restore_manual_pmi_provenance,
        )
    ]
