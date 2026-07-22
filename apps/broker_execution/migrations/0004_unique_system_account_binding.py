from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("broker_execution", "0003_broker_order_event_agent_scope"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="brokeraccountbindingmodel",
            constraint=models.UniqueConstraint(
                fields=("account_id",),
                name="uq_broker_exec_account_binding",
            ),
        ),
    ]
