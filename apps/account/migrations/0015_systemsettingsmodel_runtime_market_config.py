from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0014_portfolioobservergrantmodel"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="asset_proxy_code_map",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="资产类别到实际交易/价格代理代码的映射",
                verbose_name="资产代理代码映射",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="benchmark_code_map",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="系统运行时使用的基准/默认指数代码映射",
                verbose_name="基准代码映射",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="macro_index_catalog",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="宏观模块使用的指数代码、名称、单位和发布时间配置",
                verbose_name="宏观指数目录",
            ),
        ),
    ]
