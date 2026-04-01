from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0022_systemsettingsmodel_market_color_convention"),
    ]

    operations = [
        migrations.CreateModel(
            name="MacroSizingConfigModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "regime_tiers_json",
                    models.JSONField(
                        help_text='格式：[{"min_confidence": 0.6, "factor": 1.0}, ...]，按 min_confidence 降序'
                    ),
                ),
                (
                    "pulse_tiers_json",
                    models.JSONField(
                        help_text='格式：[{"min_composite": 0.3, "max_composite": 99, "factor": 1.0}, ...]'
                    ),
                ),
                (
                    "warning_factor",
                    models.FloatField(
                        default=0.5,
                        help_text="Pulse 转折预警时的系数覆盖值（0.0-1.0），优先于 pulse_tiers",
                    ),
                ),
                (
                    "drawdown_tiers_json",
                    models.JSONField(
                        help_text='格式：[{"min_drawdown": 0.15, "factor": 0.0}, ...]，按 min_drawdown 降序'
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("is_active", models.BooleanField(default=True)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "宏观仓位系数配置",
                "verbose_name_plural": "宏观仓位系数配置",
                "ordering": ["-version"],
            },
        ),
    ]
