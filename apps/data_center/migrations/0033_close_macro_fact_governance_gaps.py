"""Close macro governance seed ordering and historical metadata gaps."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db import migrations

ETF_FLOW_CODES = (
    "CN_A_ETF_NET_FLOW_MAIN",
    "CN_A_ETF_SIZE_FLOW",
)
TERM_SPREAD_CODES = (
    "CN_TERM_SPREAD_10Y1Y",
    "CN_TERM_SPREAD_10Y2Y",
)


def _repair_etf_chart_metadata(IndicatorCatalog) -> None:
    for indicator in IndicatorCatalog.objects.filter(code__in=ETF_FLOW_CODES):
        extra = dict(indicator.extra or {})
        extra.update(
            {
                "chart_policy": "period_bar",
                "chart_reset_frequency": "",
                "chart_segment_basis": "",
                "regime_input_policy": "direct_allowed",
                "pulse_input_policy": "direct_allowed",
            }
        )
        if indicator.extra != extra:
            indicator.extra = extra
            indicator.save(update_fields=["extra"])


def _repair_term_spread_rules(IndicatorCatalog, IndicatorUnitRule) -> None:
    IndicatorCatalog.objects.filter(code__in=TERM_SPREAD_CODES).update(default_unit="BP")
    for code in TERM_SPREAD_CODES:
        rules_by_source = defaultdict(list)
        for rule in IndicatorUnitRule.objects.filter(indicator_code=code).order_by(
            "source_type", "-priority", "id"
        ):
            rules_by_source[rule.source_type].append(rule)
        if "" not in rules_by_source:
            rules_by_source[""] = []

        for source_type, rules in rules_by_source.items():
            keeper = next((rule for rule in rules if rule.original_unit == "BP"), None)
            if keeper is None and rules:
                keeper = rules[0]
            if keeper is None:
                keeper = IndicatorUnitRule.objects.create(
                    indicator_code=code,
                    source_type=source_type,
                    original_unit="BP",
                    dimension_key="rate",
                    storage_unit="BP",
                    display_unit="BP",
                    multiplier_to_storage=Decimal("1"),
                    is_active=True,
                    priority=0,
                    description="Canonical term-spread basis-point rule.",
                )
                continue

            for duplicate in rules:
                if duplicate.pk != keeper.pk:
                    duplicate.delete()
            keeper.original_unit = "BP"
            keeper.dimension_key = "rate"
            keeper.storage_unit = "BP"
            keeper.display_unit = "BP"
            keeper.multiplier_to_storage = Decimal("1")
            keeper.is_active = True
            keeper.description = "Canonical term-spread basis-point rule."
            keeper.save(
                update_fields=[
                    "original_unit",
                    "dimension_key",
                    "storage_unit",
                    "display_unit",
                    "multiplier_to_storage",
                    "is_active",
                    "description",
                ]
            )


def _resolve_rule(rules, *, source_type: str, original_unit: str):
    exact = [rule for rule in rules if rule.original_unit == original_unit]
    for candidates in (exact, rules):
        scoped = [rule for rule in candidates if source_type and rule.source_type == source_type]
        if scoped:
            return sorted(scoped, key=lambda rule: (-rule.priority, rule.id))[0]
        fallback = [rule for rule in candidates if rule.source_type == ""]
        if fallback:
            return sorted(fallback, key=lambda rule: (-rule.priority, rule.id))[0]
    return None


def _backfill_fact_metadata(IndicatorCatalog, IndicatorUnitRule, MacroFact) -> None:
    catalogs = {
        row.code: row
        for row in IndicatorCatalog.objects.filter(is_active=True).only(
            "code", "default_period_type"
        )
    }
    rules_by_code = defaultdict(list)
    for rule in IndicatorUnitRule.objects.filter(is_active=True).only(
        "id",
        "indicator_code",
        "source_type",
        "dimension_key",
        "original_unit",
        "storage_unit",
        "display_unit",
        "multiplier_to_storage",
        "priority",
    ):
        rules_by_code[rule.indicator_code].append(rule)

    pending = []
    queryset = MacroFact.objects.order_by("indicator_code", "reporting_period", "id")
    for fact in queryset.iterator(chunk_size=1000):
        catalog = catalogs.get(fact.indicator_code)
        if catalog is None:
            continue
        extra = dict(fact.extra or {})
        source_type = str(extra.get("source_type") or fact.source or "").strip()
        raw_unit = str(extra.get("original_unit") or fact.unit or "")
        rule = _resolve_rule(
            rules_by_code.get(fact.indicator_code, []),
            source_type=source_type,
            original_unit=raw_unit,
        )
        if rule is None or fact.unit != rule.storage_unit:
            continue

        normalized_extra = {
            **extra,
            "source_type": source_type,
            "original_unit": rule.original_unit or raw_unit,
            "display_unit": rule.display_unit,
            "dimension_key": rule.dimension_key,
            "multiplier_to_storage": float(rule.multiplier_to_storage),
            "matched_rule_id": rule.id,
            "period_type": str(extra.get("period_type") or catalog.default_period_type),
        }
        if fact.published_at is not None:
            normalized_extra["publication_lag_days"] = max(
                0,
                (fact.published_at - fact.reporting_period).days,
            )
        if normalized_extra == extra:
            continue
        fact.extra = normalized_extra
        pending.append(fact)
        if len(pending) >= 500:
            MacroFact.objects.bulk_update(pending, ["extra"], batch_size=500)
            pending.clear()
    if pending:
        MacroFact.objects.bulk_update(pending, ["extra"], batch_size=500)


def close_macro_fact_governance_gaps(apps, schema_editor) -> None:
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    MacroFact = apps.get_model("data_center", "MacroFactModel")

    _repair_etf_chart_metadata(IndicatorCatalog)
    _repair_term_spread_rules(IndicatorCatalog, IndicatorUnitRule)
    # The fetcher has always emitted basis-point values; legacy catalog metadata
    # mislabeled some rows as percent. Correct the label without changing values.
    MacroFact.objects.filter(
        indicator_code__in=TERM_SPREAD_CODES,
        unit="%",
    ).update(unit="BP")
    _backfill_fact_metadata(IndicatorCatalog, IndicatorUnitRule, MacroFact)


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0032_productioncoverageuniverseconfigmodel"),
    ]

    operations = [
        migrations.RunPython(
            close_macro_fact_governance_gaps,
            migrations.RunPython.noop,
        ),
    ]
