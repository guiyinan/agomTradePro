"""Allow execution records for standalone approved capabilities."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Make the execution-record task link optional."""

    dependencies = [
        ("agent_runtime", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentexecutionrecordmodel",
            name="task",
            field=models.ForeignKey(
                blank=True,
                help_text="Linked task (optional for standalone approved capabilities)",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="execution_records",
                to="agent_runtime.agenttaskmodel",
            ),
        ),
    ]
