"""Govern AKShare customs units and derived monthly trade-balance semantics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations

AMOUNT_CODES = ("CN_EXPORTS", "CN_IMPORTS", "CN_TRADE_BALANCE")
BALANCE_CODE = "CN_TRADE_BALANCE"
MIGRATION_MARKER = "0046_govern_customs_trade_units"
PRIOR_RULE_KEY = "akshare_thousand_usd_rule_before_trade_unit_governance"
PRIOR_BALANCE_CATALOG_KEY = "catalog_before_trade_balance_derivation"
PRIOR_QUALITY_KEY = "quality_before_trade_balance_derivation"
RULE_DESCRIPTION = "AKShare customs amount in thousand USD; governed by 0046."


def govern_customs_trade_units(apps: Any, schema_editor: Any) -> None:
    """Create source-unit rules and quarantine date-misaligned balance facts."""

    catalog_model = apps.get_model("data_center", "IndicatorCatalogModel")
    rule_model = apps.get_model("data_center", "IndicatorUnitRuleModel")
    fact_model = apps.get_model("data_center", "MacroFactModel")

    for code in AMOUNT_CODES:
        catalog = catalog_model._default_manager.filter(code=code).first()
        if catalog is None:
            continue
        extra = dict(catalog.extra or {})
        existing_rule = rule_model._default_manager.filter(
            indicator_code=code,
            source_type="akshare",
            original_unit="千美元",
        ).first()
        if existing_rule is None:
            extra[PRIOR_RULE_KEY] = {"existed": False}
        else:
            extra[PRIOR_RULE_KEY] = {
                "existed": True,
                "dimension_key": existing_rule.dimension_key,
                "storage_unit": existing_rule.storage_unit,
                "display_unit": existing_rule.display_unit,
                "multiplier_to_storage": str(existing_rule.multiplier_to_storage),
                "is_active": existing_rule.is_active,
                "priority": existing_rule.priority,
                "description": existing_rule.description,
            }
        catalog.extra = extra
        catalog.save(update_fields=["extra"])

        rule_model._default_manager.update_or_create(
            indicator_code=code,
            source_type="akshare",
            original_unit="千美元",
            defaults={
                "dimension_key": "currency",
                "storage_unit": "元",
                "display_unit": "亿美元",
                "multiplier_to_storage": Decimal("1000"),
                "is_active": True,
                "priority": 100,
                "description": RULE_DESCRIPTION,
            },
        )

    balance = catalog_model._default_manager.filter(code=BALANCE_CODE).first()
    if balance is not None:
        extra = dict(balance.extra or {})
        extra.setdefault(
            PRIOR_BALANCE_CATALOG_KEY,
            {
                "description": balance.description,
                "derivation_method_present": "derivation_method" in extra,
                "derivation_method": extra.get("derivation_method"),
                "upstream_present": "upstream_indicator_codes" in extra,
                "upstream_indicator_codes": extra.get("upstream_indicator_codes"),
            },
        )
        extra.update(
            {
                "derivation_method": (
                    "AKShare 当月出口额-金额 minus 当月进口额-金额 on the same month"
                ),
                "upstream_indicator_codes": ["CN_EXPORTS", "CN_IMPORTS"],
            }
        )
        balance.description = "同月海关出口额减进口额的月度贸易差额，基础金额原始单位为千美元。"
        balance.extra = extra
        balance.save(update_fields=["description", "extra"])

    pending = []
    queryset = fact_model._default_manager.filter(
        indicator_code=BALANCE_CODE,
        source__iexact="akshare",
    ).exclude(quality="error")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        extra.setdefault(PRIOR_QUALITY_KEY, fact.quality)
        extra["invalidated_by_migration"] = MIGRATION_MARKER
        extra["invalidated_reason"] = (
            "Legacy facts used the Jin10 release date as reporting_period instead "
            "of deriving balance from same-month customs exports and imports."
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


def restore_customs_trade_units(apps: Any, schema_editor: Any) -> None:
    """Restore source rules, balance catalog metadata, and fact qualities."""

    catalog_model = apps.get_model("data_center", "IndicatorCatalogModel")
    rule_model = apps.get_model("data_center", "IndicatorUnitRuleModel")
    fact_model = apps.get_model("data_center", "MacroFactModel")

    for code in AMOUNT_CODES:
        catalog = catalog_model._default_manager.filter(code=code).first()
        if catalog is None:
            continue
        extra = dict(catalog.extra or {})
        prior_rule = extra.pop(PRIOR_RULE_KEY, {"existed": False})
        rule = rule_model._default_manager.filter(
            indicator_code=code,
            source_type="akshare",
            original_unit="千美元",
        ).first()
        if isinstance(prior_rule, dict) and prior_rule.get("existed") is True:
            if rule is not None:
                rule.dimension_key = str(prior_rule["dimension_key"])
                rule.storage_unit = str(prior_rule["storage_unit"])
                rule.display_unit = str(prior_rule["display_unit"])
                rule.multiplier_to_storage = Decimal(str(prior_rule["multiplier_to_storage"]))
                rule.is_active = bool(prior_rule["is_active"])
                rule.priority = int(prior_rule["priority"])
                rule.description = str(prior_rule["description"])
                rule.save(
                    update_fields=[
                        "dimension_key",
                        "storage_unit",
                        "display_unit",
                        "multiplier_to_storage",
                        "is_active",
                        "priority",
                        "description",
                    ]
                )
        elif rule is not None and rule.description == RULE_DESCRIPTION:
            rule.delete()
        catalog.extra = extra
        catalog.save(update_fields=["extra"])

    balance = catalog_model._default_manager.filter(code=BALANCE_CODE).first()
    if balance is not None:
        extra = dict(balance.extra or {})
        prior = extra.pop(PRIOR_BALANCE_CATALOG_KEY, {})
        balance.description = str(prior.get("description", balance.description))
        if prior.get("derivation_method_present") is True:
            extra["derivation_method"] = prior.get("derivation_method")
        else:
            extra.pop("derivation_method", None)
        if prior.get("upstream_present") is True:
            extra["upstream_indicator_codes"] = prior.get("upstream_indicator_codes")
        else:
            extra.pop("upstream_indicator_codes", None)
        balance.extra = extra
        balance.save(update_fields=["description", "extra"])

    pending = []
    queryset = fact_model._default_manager.filter(
        indicator_code=BALANCE_CODE,
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
    dependencies = [("data_center", "0045_correct_other_macro_fact_semantics")]

    operations = [
        migrations.RunPython(
            govern_customs_trade_units,
            restore_customs_trade_units,
        )
    ]
