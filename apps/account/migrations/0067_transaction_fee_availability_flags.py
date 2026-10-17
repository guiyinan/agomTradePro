"""Add nullable availability state for the four account transaction fees."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("account", "0066_account_authority_generation_lock")]

    operations = [
        migrations.AddField(
            model_name="transactionmodel",
            name="commission_known",
            field=models.BooleanField(
                blank=True, default=None, null=True, verbose_name="手续费已采集"
            ),
        ),
        migrations.AddField(
            model_name="transactionmodel",
            name="slippage_known",
            field=models.BooleanField(
                blank=True, default=None, null=True, verbose_name="滑点已采集"
            ),
        ),
        migrations.AddField(
            model_name="transactionmodel",
            name="stamp_duty_known",
            field=models.BooleanField(
                blank=True, default=None, null=True, verbose_name="印花税已采集"
            ),
        ),
        migrations.AddField(
            model_name="transactionmodel",
            name="transfer_fee_known",
            field=models.BooleanField(
                blank=True, default=None, null=True, verbose_name="过户费已采集"
            ),
        ),
    ]
