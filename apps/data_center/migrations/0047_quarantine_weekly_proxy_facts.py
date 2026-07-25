"""Disable semantically incompatible weekly proxy facts."""

from __future__ import annotations

from typing import Any

from django.db import migrations

MIGRATION_MARKER = "0047_quarantine_weekly_proxy_facts"
PRIOR_CATALOG_KEY = "catalog_before_weekly_proxy_quarantine"
PRIOR_QUALITY_KEY = "quality_before_weekly_proxy_quarantine"
DESCRIPTIONS = {
    "CN_POWER_GEN": ("当前无语义一致的公开数据源；全社会用电量不能作为发电量事实发布。"),
    "CN_BLAST_FURNACE": ("当前无语义一致的公开数据源；钢铁股票指数不能作为高炉开工率事实发布。"),
    "CN_CCFI": ("当前无语义一致的公开数据源；BDI 干散货指数不能作为 CCFI 事实发布。"),
    "CN_SCFI": ("当前无语义一致的公开数据源；BCI 干散货指数不能作为 SCFI 事实发布。"),
}
INDICATOR_CODES = tuple(DESCRIPTIONS)


def quarantine_weekly_proxy_facts(apps: Any, schema_editor: Any) -> None:
    """Disable proxy sync and quarantine existing mislabeled AKShare facts."""

    catalog_model = apps.get_model("data_center", "IndicatorCatalogModel")
    fact_model = apps.get_model("data_center", "MacroFactModel")

    for catalog in catalog_model._default_manager.filter(code__in=INDICATOR_CODES):
        extra = dict(catalog.extra or {})
        extra.setdefault(
            PRIOR_CATALOG_KEY,
            {
                "description": catalog.description,
                "sync_present": "governance_sync_supported" in extra,
                "sync_value": extra.get("governance_sync_supported"),
                "status_present": "governance_status" in extra,
                "status_value": extra.get("governance_status"),
            },
        )
        extra["governance_sync_supported"] = False
        extra["governance_status"] = "unsupported_proxy"
        catalog.description = DESCRIPTIONS[catalog.code]
        catalog.extra = extra
        catalog.save(update_fields=["description", "extra"])

    pending = []
    queryset = fact_model._default_manager.filter(
        indicator_code__in=INDICATOR_CODES,
        source__iexact="akshare",
    ).exclude(quality="error")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        extra.setdefault(PRIOR_QUALITY_KEY, fact.quality)
        extra["invalidated_by_migration"] = MIGRATION_MARKER
        extra["invalidated_reason"] = (
            "The published series was a semantically different proxy: electricity "
            "consumption, a steel equity index, BDI, or BCI."
        )
        fact.quality = "error"
        fact.extra = extra
        pending.append(fact)
    if pending:
        fact_model._default_manager.bulk_update(
            pending,
            ["quality", "extra"],
            batch_size=500,
        )


def restore_weekly_proxy_facts(apps: Any, schema_editor: Any) -> None:
    """Restore catalog metadata and fact qualities changed by this migration."""

    catalog_model = apps.get_model("data_center", "IndicatorCatalogModel")
    fact_model = apps.get_model("data_center", "MacroFactModel")

    for catalog in catalog_model._default_manager.filter(code__in=INDICATOR_CODES):
        extra = dict(catalog.extra or {})
        prior = extra.pop(PRIOR_CATALOG_KEY, {})
        catalog.description = str(prior.get("description", catalog.description))
        if prior.get("sync_present") is True:
            extra["governance_sync_supported"] = prior.get("sync_value")
        else:
            extra.pop("governance_sync_supported", None)
        if prior.get("status_present") is True:
            extra["governance_status"] = prior.get("status_value")
        else:
            extra.pop("governance_status", None)
        catalog.extra = extra
        catalog.save(update_fields=["description", "extra"])

    pending = []
    queryset = fact_model._default_manager.filter(
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
        fact_model._default_manager.bulk_update(
            pending,
            ["quality", "extra"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("data_center", "0046_govern_customs_trade_units")]

    operations = [
        migrations.RunPython(
            quarantine_weekly_proxy_facts,
            restore_weekly_proxy_facts,
        )
    ]
