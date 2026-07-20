"""Align historical investor-account audit metadata with the exact unit rule."""

from __future__ import annotations

from django.db import migrations


def backfill_investor_account_unit_metadata(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    MacroFact = apps.get_model("data_center", "MacroFactModel")
    rule = IndicatorUnitRule.objects.get(
        indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
        source_type="akshare",
        original_unit="万户",
    )

    pending = []
    queryset = MacroFact.objects.filter(
        indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
        unit="户",
    ).order_by("id")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        if str(extra.get("source_type") or fact.source).strip().lower() != "akshare":
            continue
        if str(extra.get("original_unit") or "").strip() != "万户":
            continue
        normalized_extra = {
            **extra,
            "dimension_key": rule.dimension_key,
            "display_unit": rule.display_unit,
            "matched_rule_id": rule.id,
            "multiplier_to_storage": float(rule.multiplier_to_storage),
        }
        if normalized_extra == extra:
            continue
        fact.extra = normalized_extra
        pending.append(fact)

    if pending:
        MacroFact.objects.bulk_update(pending, ["extra"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("data_center", "0036_govern_investor_account_unit")]

    operations = [
        migrations.RunPython(
            backfill_investor_account_unit_metadata,
            migrations.RunPython.noop,
        )
    ]
