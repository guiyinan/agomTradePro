"""Govern raw Tushare ETF size deltas and repair derived unit metadata."""

from __future__ import annotations

from django.db import migrations


def govern_etf_size_flow_unit(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    MacroFact = apps.get_model("data_center", "MacroFactModel")
    size_rule, _ = IndicatorUnitRule.objects.update_or_create(
        indicator_code="CN_A_ETF_SIZE_FLOW",
        source_type="tushare",
        original_unit="万元",
        defaults={
            "dimension_key": "currency",
            "storage_unit": "元",
            "display_unit": "元",
            "multiplier_to_storage": 10_000.0,
            "is_active": True,
            "priority": 100,
            "description": "Tushare ETF total_size deltas are published in ten-thousand CNY.",
        },
    )
    consensus_rule = IndicatorUnitRule.objects.get(
        indicator_code="CN_A_ETF_NET_FLOW",
        source_type="",
        original_unit="",
    )

    pending = []
    queryset = MacroFact.objects.filter(
        indicator_code__in=("CN_A_ETF_SIZE_FLOW", "CN_A_ETF_NET_FLOW"),
        unit="元",
    ).order_by("id")
    for fact in queryset.iterator(chunk_size=500):
        extra = dict(fact.extra or {})
        source_type = str(extra.get("source_type") or fact.source).strip().lower()
        if fact.indicator_code == "CN_A_ETF_SIZE_FLOW" and source_type == "tushare":
            if str(extra.get("original_unit") or "").strip() != "万元":
                continue
            rule = size_rule
            original_unit = "万元"
        elif (
            fact.indicator_code == "CN_A_ETF_NET_FLOW"
            and source_type == "data_center_consensus"
        ):
            rule = consensus_rule
            original_unit = "元"
        else:
            continue
        normalized_extra = {
            **extra,
            "original_unit": original_unit,
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


def remove_etf_size_flow_rule(apps, schema_editor):
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    IndicatorUnitRule.objects.filter(
        indicator_code="CN_A_ETF_SIZE_FLOW",
        source_type="tushare",
        original_unit="万元",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("data_center", "0037_backfill_investor_account_unit_metadata")]

    operations = [
        migrations.RunPython(
            govern_etf_size_flow_unit,
            remove_etf_size_flow_rule,
        )
    ]
