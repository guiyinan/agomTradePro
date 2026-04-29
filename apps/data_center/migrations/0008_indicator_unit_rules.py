from decimal import Decimal

from django.db import migrations, models


CURRENCY_MULTIPLIERS = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
    "万亿元": Decimal("1000000000000"),
    "万美元": Decimal("10000"),
    "百万美元": Decimal("1000000"),
    "亿美元": Decimal("100000000"),
    "十亿美元": Decimal("1000000000"),
    "万亿美元": Decimal("10000000000000"),
}


def _classify_dimension(unit: str) -> str:
    if unit in CURRENCY_MULTIPLIERS:
        return "currency"
    if unit in {"%", "BP", "bps"}:
        return "rate"
    if unit in {"指数", "点"}:
        return "index"
    if "/" in unit:
        return "price"
    return "other"


def _storage_unit(unit: str) -> str:
    if unit in CURRENCY_MULTIPLIERS:
        return "元"
    return unit


def _multiplier(unit: str) -> Decimal:
    return CURRENCY_MULTIPLIERS.get(unit, Decimal("1"))


def _upsert_rule(Rule, *, indicator_code: str, source_type: str, original_unit: str, priority: int, description: str):
    unit = original_unit or ""
    Rule.objects.update_or_create(
        indicator_code=indicator_code,
        source_type=source_type,
        original_unit=unit,
        defaults={
            "dimension_key": _classify_dimension(unit),
            "storage_unit": _storage_unit(unit),
            "display_unit": unit,
            "multiplier_to_storage": _multiplier(unit),
            "is_active": True,
            "priority": priority,
            "description": description,
        },
    )


def seed_indicator_unit_rules(apps, schema_editor):
    Catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    Rule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    LegacyUnitConfig = apps.get_model("macro", "IndicatorUnitConfig")

    for catalog in Catalog.objects.filter(is_active=True).exclude(default_unit=""):
        _upsert_rule(
            Rule,
            indicator_code=catalog.code,
            source_type="",
            original_unit=catalog.default_unit,
            priority=0,
            description="Seeded from IndicatorCatalog.default_unit",
        )

    for legacy in LegacyUnitConfig.objects.filter(is_active=True):
        if not Catalog.objects.filter(code=legacy.indicator_code).exists():
            continue
        source_type = "" if legacy.source == "manual" else legacy.source
        _upsert_rule(
            Rule,
            indicator_code=legacy.indicator_code,
            source_type=source_type,
            original_unit=legacy.original_unit or "",
            priority=int(legacy.priority or 0),
            description=legacy.description or "Backfilled from legacy IndicatorUnitConfig",
        )


def unseed_indicator_unit_rules(apps, schema_editor):
    Rule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    Rule.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0017_normalize_monthly_period_type_and_rededupe"),
        ("data_center", "0007_expand_macro_indicator_catalog_coverage"),
    ]

    operations = [
        migrations.CreateModel(
            name="IndicatorUnitRuleModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("indicator_code", models.CharField(db_index=True, help_text="Matches IndicatorCatalogModel.code", max_length=50)),
                ("source_type", models.CharField(blank=True, default="", help_text="Logical provider source type (e.g. akshare, tushare); blank = default rule", max_length=20)),
                ("dimension_key", models.CharField(help_text="Dimension classification such as currency, rate, index, price", max_length=30)),
                ("original_unit", models.CharField(blank=True, default="", help_text="Provider raw unit before normalization", max_length=20)),
                ("storage_unit", models.CharField(help_text="Canonical storage unit persisted in MacroFactModel.unit", max_length=20)),
                ("display_unit", models.CharField(help_text="Frontend display unit returned by macro query APIs", max_length=20)),
                ("multiplier_to_storage", models.DecimalField(decimal_places=8, default=1, help_text="Multiply the raw value by this factor to get canonical storage value", max_digits=24)),
                ("is_active", models.BooleanField(default=True)),
                ("priority", models.IntegerField(default=0)),
                ("description", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_indicator_unit_rule",
                "ordering": ["indicator_code", "-priority", "source_type", "original_unit"],
                "verbose_name": "Indicator Unit Rule",
                "verbose_name_plural": "Indicator Unit Rules",
                "unique_together": {("indicator_code", "source_type", "original_unit")},
            },
        ),
        migrations.AddIndex(
            model_name="indicatorunitrulemodel",
            index=models.Index(fields=["indicator_code", "is_active"], name="data_center_indicator_code_02db84_idx"),
        ),
        migrations.AddIndex(
            model_name="indicatorunitrulemodel",
            index=models.Index(fields=["indicator_code", "source_type", "is_active"], name="data_center_indicator_code_4fdd70_idx"),
        ),
        migrations.RunPython(seed_indicator_unit_rules, reverse_code=unseed_indicator_unit_rules),
    ]
