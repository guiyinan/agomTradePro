from django.db import migrations, models


class Migration(migrations.Migration):
    """Add durable lifecycle timestamps for the dormant run ledger."""

    dependencies = [
        ("agent_runtime", "0004_terminal_agent_run"),
    ]

    operations = [
        migrations.AddField(
            model_name="terminalagentrunmodel",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="terminalagentrunmodel",
            name="cancel_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="terminalagentrunmodel",
            index=models.Index(
                fields=["dispatch_status", "heartbeat_at"],
                name="agent_term_status_hb_idx",
            ),
        ),
    ]
