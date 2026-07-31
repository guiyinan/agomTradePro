"""Seed the governed Pulse sentiment input portfolio."""

from __future__ import annotations

from typing import Any

from django.db import migrations

SENTIMENT_INDICATOR_DEFAULTS = (
    {
        "indicator_code": "000300.SH",
        "indicator_name": "沪深300",
        "signal_type": "pct_change",
        "bullish_threshold": 3.0,
        "bearish_threshold": -3.0,
        "signal_multiplier": 0.1,
    },
    {
        "indicator_code": "CN_A_TOTAL_TURNOVER",
        "indicator_name": "A股全市场成交额",
        "signal_type": "pct_change",
        "bullish_threshold": 20.0,
        "bearish_threshold": -20.0,
        "signal_multiplier": 0.025,
    },
    {
        "indicator_code": "CN_A_MARGIN_BALANCE",
        "indicator_name": "A股融资余额",
        "signal_type": "pct_change",
        "bullish_threshold": 3.0,
        "bearish_threshold": -3.0,
        "signal_multiplier": 0.1,
    },
    {
        "indicator_code": "CN_A_MARKET_NEWS_SENTIMENT",
        "indicator_name": "A股市场新闻情绪均值",
        "signal_type": "level",
        "bullish_threshold": 0.2,
        "bearish_threshold": -0.2,
        "signal_multiplier": 1.0,
    },
    {
        "indicator_code": "CN_A_ETF_NET_FLOW",
        "indicator_name": "A股ETF资金净流入",
        "signal_type": "zscore",
        "bullish_threshold": 1.0,
        "bearish_threshold": -1.0,
        "signal_multiplier": 0.4,
    },
    {
        "indicator_code": "SENTIMENT_DAILY_INDEX",
        "indicator_name": "文本情绪指数",
        "signal_type": "level",
        "bullish_threshold": 0.3,
        "bearish_threshold": -0.3,
        "signal_multiplier": 1.0,
    },
)


def _seed_sentiment_indicator_config(apps: Any, schema_editor: Any) -> None:
    PulseIndicatorConfig = apps.get_model("pulse", "PulseIndicatorConfigModel")

    for item in SENTIMENT_INDICATOR_DEFAULTS:
        indicator_code = item["indicator_code"]
        defaults = {
            "indicator_name": item["indicator_name"],
            "dimension": "sentiment",
            "frequency": "daily",
            "weight": 1.0,
            "signal_type": item["signal_type"],
            "bullish_threshold": item["bullish_threshold"],
            "bearish_threshold": item["bearish_threshold"],
            "neutral_band": 0.5,
            "signal_multiplier": item["signal_multiplier"],
            "is_active": True,
        }
        PulseIndicatorConfig.objects.update_or_create(
            indicator_code=indicator_code,
            defaults=defaults,
        )


def _remove_added_sentiment_indicator_config(apps: Any, schema_editor: Any) -> None:
    PulseIndicatorConfig = apps.get_model("pulse", "PulseIndicatorConfigModel")
    added_codes = [
        item["indicator_code"]
        for item in SENTIMENT_INDICATOR_DEFAULTS
        if item["indicator_code"] != "000300.SH"
    ]
    PulseIndicatorConfig.objects.filter(indicator_code__in=added_codes).delete()


class Migration(migrations.Migration):
    dependencies = [("pulse", "0004_fix_pulse_indicator_units")]

    operations = [
        migrations.RunPython(
            _seed_sentiment_indicator_config,
            _remove_added_sentiment_indicator_config,
        ),
    ]
