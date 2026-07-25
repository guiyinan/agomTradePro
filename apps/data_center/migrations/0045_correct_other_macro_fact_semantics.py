"""Correct employment, Beijing housing, and refined-oil fact semantics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations

HOUSE_CODE = "CN_NEW_HOUSE_PRICE"
OIL_CODE = "CN_OIL_PRICE"
UNEMPLOYMENT_CODE = "CN_UNEMPLOYMENT"
MIGRATION_MARKER = "0045_correct_other_macro_fact_semantics"
LEGACY_OIL_DIVISOR = Decimal("1360")
PRIOR_CATALOG_KEY = "catalog_before_other_macro_semantics_correction"
PRIOR_QUALITY_KEY = "quality_before_other_macro_semantics_correction"


def correct_other_fact_semantics(apps: Any, schema_editor: Any) -> None:
    """Publish exact catalog semantics and repair or quarantine legacy facts."""

    catalog_model = apps.get_model("data_center", "IndicatorCatalogModel")
    rule_model = apps.get_model("data_center", "IndicatorUnitRuleModel")
    fact_model = apps.get_model("data_center", "MacroFactModel")

    house = catalog_model._default_manager.filter(code=HOUSE_CODE).first()
    if house is not None:
        extra = dict(house.extra or {})
        extra.setdefault(
            PRIOR_CATALOG_KEY,
            {
                "name_cn": house.name_cn,
                "description": house.description,
                "default_unit": house.default_unit,
            },
        )
        extra.update({"geographic_scope": "city", "city": "北京"})
        house.name_cn = "北京新建商品住宅价格同比变动"
        house.description = (
            "北京市新建商品住宅价格同比指数减 100 后的月度变动幅度；"
            "属于北京单城市序列，不代表全国房价。"
        )
        house.extra = extra
        house.save(update_fields=["name_cn", "description", "extra"])

    oil = catalog_model._default_manager.filter(code=OIL_CODE).first()
    if oil is not None:
        extra = dict(oil.extra or {})
        extra.setdefault(
            PRIOR_CATALOG_KEY,
            {
                "name_cn": oil.name_cn,
                "description": oil.description,
                "default_unit": oil.default_unit,
            },
        )
        oil.name_cn = "汽油最高零售价格"
        oil.description = "国家发改委调价时点汽油最高零售价格，按数据源原始元/吨口径发布。"
        oil.default_unit = "元/吨"
        oil.extra = extra
        oil.save(update_fields=["name_cn", "description", "default_unit", "extra"])

    oil_rule = rule_model._default_manager.filter(
        indicator_code=OIL_CODE,
        source_type="",
        original_unit="元/升",
    ).first()
    if oil_rule is not None:
        oil_rule.original_unit = "元/吨"
        oil_rule.storage_unit = "元/吨"
        oil_rule.display_unit = "元/吨"
        oil_rule.multiplier_to_storage = Decimal("1")
        oil_rule.description = "Corrected to the AKShare source unit; no density assumption."
        oil_rule.save(
            update_fields=[
                "original_unit",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
                "description",
            ]
        )

    pending_oil = []
    oil_facts = fact_model._default_manager.filter(
        indicator_code=OIL_CODE,
        source__iexact="akshare",
        unit="元/升",
    )
    for fact in oil_facts.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        extra["corrected_by_migration"] = MIGRATION_MARKER
        extra["value_before_unit_correction"] = str(fact.value)
        extra["unit_before_unit_correction"] = fact.unit
        extra["legacy_runtime_divisor"] = str(LEGACY_OIL_DIVISOR)
        extra["original_unit"] = "元/吨"
        fact.value = fact.value * LEGACY_OIL_DIVISOR
        fact.unit = "元/吨"
        fact.extra = extra
        pending_oil.append(fact)
    if pending_oil:
        fact_model._default_manager.bulk_update(
            pending_oil,
            ["value", "unit", "extra"],
            batch_size=500,
        )

    pending_unemployment = []
    unemployment_facts = fact_model._default_manager.filter(
        indicator_code=UNEMPLOYMENT_CODE,
        source__iexact="akshare",
        value=Decimal("0"),
    ).exclude(quality="error")
    for fact in unemployment_facts.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        extra.setdefault(PRIOR_QUALITY_KEY, fact.quality)
        extra["invalidated_by_migration"] = MIGRATION_MARKER
        extra["invalidated_reason"] = (
            "Legacy fetcher selected the AKShare item-name column and converted "
            "parse failures to a fabricated 0% unemployment rate."
        )
        fact.quality = "error"
        fact.extra = extra
        pending_unemployment.append(fact)
    if pending_unemployment:
        fact_model._default_manager.bulk_update(
            pending_unemployment,
            ["quality", "extra"],
            batch_size=500,
        )


def restore_other_fact_semantics(apps: Any, schema_editor: Any) -> None:
    """Restore catalog, rule, and fact values changed by this migration."""

    catalog_model = apps.get_model("data_center", "IndicatorCatalogModel")
    rule_model = apps.get_model("data_center", "IndicatorUnitRuleModel")
    fact_model = apps.get_model("data_center", "MacroFactModel")

    for catalog in catalog_model._default_manager.filter(code__in=(HOUSE_CODE, OIL_CODE)):
        extra = dict(catalog.extra or {})
        prior = extra.pop(PRIOR_CATALOG_KEY, {})
        catalog.name_cn = str(prior.get("name_cn", catalog.name_cn))
        catalog.description = str(prior.get("description", catalog.description))
        catalog.default_unit = str(prior.get("default_unit", catalog.default_unit))
        if catalog.code == HOUSE_CODE:
            extra.pop("geographic_scope", None)
            extra.pop("city", None)
        catalog.extra = extra
        catalog.save(update_fields=["name_cn", "description", "default_unit", "extra"])

    oil_rule = rule_model._default_manager.filter(
        indicator_code=OIL_CODE,
        source_type="",
        original_unit="元/吨",
        description="Corrected to the AKShare source unit; no density assumption.",
    ).first()
    if oil_rule is not None:
        oil_rule.original_unit = "元/升"
        oil_rule.storage_unit = "元/升"
        oil_rule.display_unit = "元/升"
        oil_rule.multiplier_to_storage = Decimal("1")
        oil_rule.description = "Seeded from IndicatorCatalog.default_unit"
        oil_rule.save(
            update_fields=[
                "original_unit",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
                "description",
            ]
        )

    pending_oil = []
    oil_facts = fact_model._default_manager.filter(
        indicator_code=OIL_CODE,
        source__iexact="akshare",
        extra__corrected_by_migration=MIGRATION_MARKER,
    )
    for fact in oil_facts.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        prior_value = Decimal(str(extra.pop("value_before_unit_correction")))
        prior_unit = str(extra.pop("unit_before_unit_correction", "元/升"))
        extra.pop("corrected_by_migration", None)
        extra.pop("legacy_runtime_divisor", None)
        extra.pop("original_unit", None)
        fact.value = prior_value
        fact.unit = prior_unit
        fact.extra = extra
        pending_oil.append(fact)
    if pending_oil:
        fact_model._default_manager.bulk_update(
            pending_oil,
            ["value", "unit", "extra"],
            batch_size=500,
        )

    pending_unemployment = []
    unemployment_facts = fact_model._default_manager.filter(
        indicator_code=UNEMPLOYMENT_CODE,
        source__iexact="akshare",
        extra__invalidated_by_migration=MIGRATION_MARKER,
    )
    valid_qualities = {"valid", "stale", "estimated", "error", "missing"}
    for fact in unemployment_facts.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        prior_quality = str(extra.pop(PRIOR_QUALITY_KEY, "valid"))
        extra.pop("invalidated_by_migration", None)
        extra.pop("invalidated_reason", None)
        fact.quality = prior_quality if prior_quality in valid_qualities else "valid"
        fact.extra = extra
        pending_unemployment.append(fact)
    if pending_unemployment:
        fact_model._default_manager.bulk_update(
            pending_unemployment,
            ["quality", "extra"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("data_center", "0044_quarantine_mislabeled_high_frequency_facts")]

    operations = [
        migrations.RunPython(
            correct_other_fact_semantics,
            restore_other_fact_semantics,
        )
    ]
