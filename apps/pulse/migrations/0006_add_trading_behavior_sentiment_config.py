"""Add A-share trading-behavior readings to the Pulse sentiment dimension."""

from __future__ import annotations

from typing import Any

from django.db import migrations

INDICATORS = (
    ("CN_A_ADVANCE_COUNT", "A股上涨家数", 0.4),
    ("CN_A_DECLINE_COUNT", "A股下跌家数", -0.4),
    ("CN_A_LIMIT_UP_COUNT", "A股涨停家数", 0.4),
    ("CN_A_LIMIT_DOWN_COUNT", "A股跌停家数", -0.4),
)


def seed_trading_behavior_configs(apps: Any, schema_editor: Any) -> None:
    """Create reversible Pulse configs for the governed behavior facts."""

    PulseIndicatorConfig = apps.get_model("pulse", "PulseIndicatorConfigModel")
    for indicator_code, indicator_name, signal_multiplier in INDICATORS:
        PulseIndicatorConfig.objects.update_or_create(
            indicator_code=indicator_code,
            defaults={
                "indicator_name": indicator_name,
                "dimension": "sentiment",
                "frequency": "daily",
                "weight": 1.0,
                "signal_type": "zscore",
                "bullish_threshold": 1.0,
                "bearish_threshold": -1.0,
                "neutral_band": 0.5,
                "signal_multiplier": signal_multiplier,
                "is_active": True,
            },
        )


def remove_trading_behavior_configs(apps: Any, schema_editor: Any) -> None:
    """Remove only the configs introduced by this migration."""

    PulseIndicatorConfig = apps.get_model("pulse", "PulseIndicatorConfigModel")
    PulseIndicatorConfig.objects.filter(
        indicator_code__in=[item[0] for item in INDICATORS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("pulse", "0005_expand_sentiment_indicator_config")]

    operations = [
        migrations.RunPython(
            seed_trading_behavior_configs,
            remove_trading_behavior_configs,
        )
    ]
