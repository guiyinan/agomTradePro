"""Persist the typed financial fact-to-artifact decision-evidence projection."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add a versioned JSON projection without synthesizing legacy evidence."""

    dependencies = [("data_center", "0081_sync_item_attempt_running_unique")]

    operations = [
        migrations.AddField(
            model_name="financialfactmodel",
            name="decision_evidence",
            field=models.JSONField(blank=True, default=dict),
        )
    ]
