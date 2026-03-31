import logging

from django.db import migrations

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "regime_tiers_json": [
        {"min_confidence": 0.6, "factor": 1.0},
        {"min_confidence": 0.4, "factor": 0.8},
        {"min_confidence": 0.0, "factor": 0.5},
    ],
    "pulse_tiers_json": [
        {"min_composite": 0.3, "max_composite": 99, "factor": 1.00},
        {"min_composite": -0.3, "max_composite": 0.3, "factor": 0.85},
        {"min_composite": -99, "max_composite": -0.3, "factor": 0.70},
    ],
    "warning_factor": 0.5,
    "drawdown_tiers_json": [
        {"min_drawdown": 0.15, "factor": 0.0},
        {"min_drawdown": 0.10, "factor": 0.5},
        {"min_drawdown": 0.05, "factor": 0.8},
        {"min_drawdown": 0.00, "factor": 1.0},
    ],
    "version": 1,
    "is_active": True,
    "description": "默认配置（系统初始化自动写入）",
}


def load_default_config(apps, schema_editor):
    MacroSizingConfigModel = apps.get_model("account", "MacroSizingConfigModel")
    if MacroSizingConfigModel.objects.filter(is_active=True, version=1).exists():
        return
    MacroSizingConfigModel.objects.create(**DEFAULT_CONFIG)
    logger.info("MacroSizingConfig default config loaded")


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0023_macrosizingconfigmodel"),
    ]
    operations = [
        migrations.RunPython(load_default_config),
    ]
