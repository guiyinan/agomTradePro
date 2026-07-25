"""Correct RMB deposit semantics and quarantine previously misclassified facts."""

from __future__ import annotations

from typing import Any

from django.db import migrations

INDICATOR_CODE = "CN_RMB_DEPOSIT"
MIGRATION_MARKER = "0041_correct_rmb_deposit_semantics"
PRIOR_QUALITY_KEY = "quality_before_rmb_deposit_semantics_correction"


def correct_rmb_deposit_semantics(apps: Any, schema_editor: Any) -> None:
    """Publish flow semantics and quarantine AKShare household-subset history."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    macro_fact = apps.get_model("data_center", "MacroFactModel")

    catalog = indicator_catalog._default_manager.filter(code=INDICATOR_CODE).first()
    if catalog is not None:
        extra = dict(catalog.extra or {})
        extra.update(
            {
                "series_semantics": "flow_level",
                "chart_policy": "period_bar",
                "chart_reset_frequency": "",
                "chart_segment_basis": "",
                "regime_input_policy": "direct_allowed",
                "pulse_input_policy": "direct_allowed",
            }
        )
        catalog.name_cn = "新增人民币存款"
        catalog.description = "月度新增人民币存款总额口径，属于当期流量值，不应与存款余额混用。"
        catalog.extra = extra
        catalog.save(update_fields=["name_cn", "description", "extra"])

    pending = []
    queryset = macro_fact._default_manager.filter(
        indicator_code=INDICATOR_CODE,
        source__iexact="akshare",
    ).exclude(quality="error")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        extra.setdefault(PRIOR_QUALITY_KEY, fact.quality)
        extra["invalidated_by_migration"] = MIGRATION_MARKER
        extra["invalidated_reason"] = (
            "Legacy AKShare fetch selected the household-savings subset while the "
            "indicator was labeled as total RMB deposit balance; resync is required."
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


def restore_rmb_deposit_semantics(apps: Any, schema_editor: Any) -> None:
    """Restore the prior catalog semantics and quarantined fact qualities."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    macro_fact = apps.get_model("data_center", "MacroFactModel")

    catalog = indicator_catalog._default_manager.filter(code=INDICATOR_CODE).first()
    if catalog is not None:
        extra = dict(catalog.extra or {})
        extra.update(
            {
                "series_semantics": "balance_level",
                "chart_policy": "continuous_line",
                "chart_reset_frequency": "",
                "chart_segment_basis": "",
                "regime_input_policy": "direct_allowed",
                "pulse_input_policy": "direct_allowed",
            }
        )
        catalog.name_cn = "人民币存款余额"
        catalog.description = "月度人民币存款余额口径，属于存量序列，不应按当期流量值理解。"
        catalog.extra = extra
        catalog.save(update_fields=["name_cn", "description", "extra"])

    pending = []
    queryset = macro_fact._default_manager.filter(
        indicator_code=INDICATOR_CODE,
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
    dependencies = [("data_center", "0040_enforce_executable_price_facts")]

    operations = [
        migrations.RunPython(
            correct_rmb_deposit_semantics,
            restore_rmb_deposit_semantics,
        )
    ]
