import django.db.models.deletion
from django.db import migrations, models


def populate_event_agents(apps, schema_editor):
    """Backfill the immutable Agent identity from each event's order."""

    Event = apps.get_model("broker_execution", "BrokerOrderEventModel")
    for event in Event.objects.select_related("order").iterator():
        event.agent_id = event.order.agent_id
        event.save(update_fields=["agent_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("broker_execution", "0002_brokeraccountbindingmodel_allowed_trading_windows_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="brokerordereventmodel",
            name="agent",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="broker_order_events",
                to="broker_execution.brokeragentmodel",
            ),
        ),
        migrations.RunPython(populate_event_agents, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="brokerordereventmodel",
            name="agent",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="broker_order_events",
                to="broker_execution.brokeragentmodel",
            ),
        ),
        migrations.AlterField(
            model_name="brokerordereventmodel",
            name="event_id",
            field=models.CharField(max_length=96),
        ),
        migrations.AddConstraint(
            model_name="brokerordereventmodel",
            constraint=models.UniqueConstraint(
                fields=("agent", "event_id"),
                name="uq_broker_exec_agent_event",
            ),
        ),
    ]
