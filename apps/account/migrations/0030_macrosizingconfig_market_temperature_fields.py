from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0029_useraccesstokenmodel_access_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="macrosizingconfigmodel",
            name="block_new_position_on_extreme",
            field=models.BooleanField(
                default=True,
                help_text="当市场温度进入 extreme 时是否阻断新增仓位建议。",
            ),
        ),
        migrations.AddField(
            model_name="macrosizingconfigmodel",
            name="market_temperature_cold_factor",
            field=models.FloatField(
                default=1.0,
                help_text="市场温度 cold 分段对应的仓位系数。",
            ),
        ),
        migrations.AddField(
            model_name="macrosizingconfigmodel",
            name="market_temperature_extreme_factor",
            field=models.FloatField(
                default=0.35,
                help_text="市场温度 extreme 分段对应的仓位系数。",
            ),
        ),
        migrations.AddField(
            model_name="macrosizingconfigmodel",
            name="market_temperature_hot_factor",
            field=models.FloatField(
                default=0.9,
                help_text="市场温度 hot 分段对应的仓位系数。",
            ),
        ),
        migrations.AddField(
            model_name="macrosizingconfigmodel",
            name="market_temperature_overheat_factor",
            field=models.FloatField(
                default=0.75,
                help_text="市场温度 overheat 分段对应的仓位系数。",
            ),
        ),
        migrations.AddField(
            model_name="macrosizingconfigmodel",
            name="market_temperature_warm_factor",
            field=models.FloatField(
                default=1.0,
                help_text="市场温度 warm 分段对应的仓位系数。",
            ),
        ),
    ]
