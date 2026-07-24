from django.db import migrations, models


class Migration(migrations.Migration):
    """Require every new fee configuration to declare its minimum commission."""

    dependencies = [
        (
            "simulated_trading",
            "0018_rename_acct_bm_account_active_idx_account_ben_account_855253_idx_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="feeconfigmodel",
            name="min_commission",
            field=models.FloatField(help_text="不足按此收取", verbose_name="最低手续费(元)"),
        ),
    ]
