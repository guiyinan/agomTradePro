from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("broker_execution", "0005_agent_credential_account_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="brokerexecutionauditmodel",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="broker_execution_audits_owned",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
