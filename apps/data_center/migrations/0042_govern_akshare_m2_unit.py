"""Govern the raw AKShare M2 balance unit without fetcher-side scaling."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations


def govern_akshare_m2_unit(apps: Any, schema_editor: Any) -> None:
    """Register the source's 亿元 payload and canonical storage conversion."""

    indicator_unit_rule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    indicator_unit_rule._default_manager.update_or_create(
        indicator_code="CN_M2",
        source_type="akshare",
        original_unit="亿元",
        defaults={
            "dimension_key": "currency",
            "storage_unit": "元",
            "display_unit": "万亿元",
            "multiplier_to_storage": Decimal("100000000"),
            "is_active": True,
            "priority": 100,
            "description": (
                "AKShare 货币和准货币(M2)-数量(亿元) raw payload; "
                "normalize to canonical CNY storage."
            ),
        },
    )


def remove_akshare_m2_unit(apps: Any, schema_editor: Any) -> None:
    """Remove only the provider-specific rule introduced by this migration."""

    indicator_unit_rule = apps.get_model("data_center", "IndicatorUnitRuleModel")
    indicator_unit_rule._default_manager.filter(
        indicator_code="CN_M2",
        source_type="akshare",
        original_unit="亿元",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("data_center", "0041_correct_rmb_deposit_semantics")]

    operations = [
        migrations.RunPython(
            govern_akshare_m2_unit,
            remove_akshare_m2_unit,
        )
    ]
