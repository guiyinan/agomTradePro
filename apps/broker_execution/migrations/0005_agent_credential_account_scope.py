from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("broker_execution", "0004_unique_system_account_binding"),
    ]

    operations = [
        migrations.AddField(
            model_name="brokeragentcredentialmodel",
            name="allowed_account_ids",
            field=models.JSONField(default=list),
        ),
    ]
