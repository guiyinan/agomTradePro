"""Label Pulse price-limit indicators with their non-ST market scope."""

from __future__ import annotations

from typing import Any

from django.db import migrations

CURRENT_NAMES: dict[str, str] = {
    "CN_A_LIMIT_UP_COUNT": "A股涨停家数（不含 ST）",
    "CN_A_LIMIT_DOWN_COUNT": "A股跌停家数（不含 ST）",
}

PREVIOUS_NAMES: dict[str, str] = {
    "CN_A_LIMIT_UP_COUNT": "A股涨停家数",
    "CN_A_LIMIT_DOWN_COUNT": "A股跌停家数",
}


def apply_non_st_scope_labels(apps: Any, schema_editor: Any) -> None:
    """Update existing Pulse indicator names with the explicit non-ST scope."""

    indicator_config = apps.get_model("pulse", "PulseIndicatorConfigModel")
    for indicator_code, indicator_name in CURRENT_NAMES.items():
        indicator_config.objects.filter(indicator_code=indicator_code).update(
            indicator_name=indicator_name
        )


def restore_previous_scope_labels(apps: Any, schema_editor: Any) -> None:
    """Restore the prior Pulse indicator names."""

    indicator_config = apps.get_model("pulse", "PulseIndicatorConfigModel")
    for indicator_code, indicator_name in PREVIOUS_NAMES.items():
        indicator_config.objects.filter(indicator_code=indicator_code).update(
            indicator_name=indicator_name
        )


class Migration(migrations.Migration):
    dependencies = [
        ("pulse", "0006_add_trading_behavior_sentiment_config"),
    ]

    operations = [
        migrations.RunPython(
            apply_non_st_scope_labels,
            restore_previous_scope_labels,
        ),
    ]
