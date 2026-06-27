from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0031_transactionmodel_broker_name_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stoplossconfigmodel",
            name="stop_loss_pct",
            field=models.FloatField(help_text="如 0.10 表示 10% 止损", verbose_name="止损百分比"),
        ),
        migrations.AlterField(
            model_name="stoplossconfigmodel",
            name="trailing_stop_pct",
            field=models.FloatField(
                blank=True,
                help_text="移动止损时使用，如 0.10",
                null=True,
                verbose_name="移动止损百分比",
            ),
        ),
    ]
