"""Make StorageBudget policies truly versioned with one active row."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0010_configcentersecretmodel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="storagebudgetpolicymodel",
            name="policy_key",
            field=models.CharField(db_index=True, max_length=100),
        ),
        migrations.AddConstraint(
            model_name="storagebudgetpolicymodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(active=True),
                fields=("active",),
                name="config_center_one_active_storage_policy",
            ),
        ),
    ]
