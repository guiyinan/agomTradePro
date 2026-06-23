from django.db import migrations


def _fix_pulse_indicator_units(apps, schema_editor):
    PulseIndicatorConfig = apps.get_model("pulse", "PulseIndicatorConfigModel")
    PulseIndicatorWeight = apps.get_model("pulse", "PulseIndicatorWeight")

    PulseIndicatorConfig.objects.filter(indicator_code="CN_NEW_CREDIT").update(
        bullish_threshold=3.0e12,
        bearish_threshold=1.0e12,
    )

    new_m2_config = PulseIndicatorConfig.objects.filter(indicator_code="CN_M2_YOY")
    old_m2_configs = PulseIndicatorConfig.objects.filter(indicator_code="CN_M2")
    m2_defaults = {
        "indicator_name": "M2增速",
        "dimension": "liquidity",
        "frequency": "monthly",
        "signal_type": "level",
        "bullish_threshold": 8.0,
        "bearish_threshold": 6.0,
        "neutral_band": 0.5,
        "signal_multiplier": 0.4,
        "is_active": True,
    }
    if new_m2_config.exists():
        new_m2_config.update(**m2_defaults)
        old_m2_configs.update(is_active=False)
    elif old_m2_configs.exists():
        old_m2_configs.update(
            indicator_code="CN_M2_YOY",
            **m2_defaults,
        )
    else:
        PulseIndicatorConfig.objects.get_or_create(
            indicator_code="CN_M2_YOY",
            defaults={
                "weight": 1.0,
                **m2_defaults,
            },
        )

    PulseIndicatorWeight.objects.filter(indicator_code="CN_M2").update(
        indicator_code="CN_M2_YOY",
        dimension="liquidity",
    )


def _reverse_fix_pulse_indicator_units(apps, schema_editor):
    PulseIndicatorConfig = apps.get_model("pulse", "PulseIndicatorConfigModel")
    PulseIndicatorWeight = apps.get_model("pulse", "PulseIndicatorWeight")

    PulseIndicatorConfig.objects.filter(indicator_code="CN_NEW_CREDIT").update(
        bullish_threshold=8.0e15,
        bearish_threshold=3.0e15,
    )
    old_m2_config = PulseIndicatorConfig.objects.filter(indicator_code="CN_M2")
    new_m2_configs = PulseIndicatorConfig.objects.filter(indicator_code="CN_M2_YOY")
    reverse_defaults = {
        "indicator_name": "M2增速",
        "dimension": "liquidity",
        "frequency": "monthly",
        "signal_type": "zscore",
        "bullish_threshold": 0.5,
        "bearish_threshold": -0.5,
        "neutral_band": 0.5,
        "signal_multiplier": 0.3,
        "is_active": True,
    }
    if old_m2_config.exists():
        old_m2_config.update(**reverse_defaults)
        new_m2_configs.update(is_active=False)
    else:
        new_m2_configs.update(
            indicator_code="CN_M2",
            **reverse_defaults,
        )
    PulseIndicatorWeight.objects.filter(indicator_code="CN_M2_YOY").update(
        indicator_code="CN_M2",
        dimension="liquidity",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("pulse", "0003_enforce_unique_pulselog_observed_at"),
    ]

    operations = [
        migrations.RunPython(
            _fix_pulse_indicator_units,
            _reverse_fix_pulse_indicator_units,
        ),
    ]
