from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0024_macros_sizing_config_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="alpha_pool_mode",
            field=models.CharField(
                choices=[
                    ("strict_valuation", "严格估值覆盖池"),
                    ("market", "市场可交易池"),
                    ("price_covered", "价格覆盖池"),
                ],
                default="strict_valuation",
                help_text="控制首页 Alpha 和实时推理默认使用哪个候选股票集合",
                max_length=32,
                verbose_name="Alpha 默认股票池模式",
            ),
        ),
    ]
