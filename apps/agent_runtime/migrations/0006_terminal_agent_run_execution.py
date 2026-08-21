import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Persist queued run execution checkpoints and replayable events."""

    dependencies = [
        ("agent_runtime", "0005_terminal_agent_run_lifecycle"),
    ]

    operations = [
        migrations.CreateModel(
            name="TerminalAgentRunExecutionModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_requested_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=128, null=True)),
                ("result_ref", models.CharField(blank=True, max_length=128, null=True)),
                ("result_payload", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_checkpoint",
                        to="agent_runtime.terminalagentrunmodel",
                    ),
                ),
            ],
            options={
                "db_table": "agent_terminal_run_execution",
            },
        ),
        migrations.AddIndex(
            model_name="terminalagentrunexecutionmodel",
            index=models.Index(fields=["heartbeat_at"], name="agent_term_exec_heartbeat_idx"),
        ),
        migrations.AddIndex(
            model_name="terminalagentrunexecutionmodel",
            index=models.Index(fields=["finished_at"], name="agent_term_exec_finished_idx"),
        ),
        migrations.CreateModel(
            name="TerminalAgentRunEventModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_id", models.CharField(max_length=128, unique=True)),
                ("sequence", models.PositiveIntegerField()),
                ("event_type", models.CharField(max_length=64)),
                ("occurred_at", models.DateTimeField()),
                ("data", models.JSONField(default=dict)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_events",
                        to="agent_runtime.terminalagentrunmodel",
                    ),
                ),
            ],
            options={
                "db_table": "agent_terminal_run_event",
            },
        ),
        migrations.AddConstraint(
            model_name="terminalagentruneventmodel",
            constraint=models.UniqueConstraint(
                fields=("run", "sequence"),
                name="agent_term_event_run_sequence_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="terminalagentruneventmodel",
            index=models.Index(fields=["run", "sequence"], name="agent_term_event_run_seq_idx"),
        ),
        migrations.AddIndex(
            model_name="terminalagentruneventmodel",
            index=models.Index(fields=["run", "occurred_at"], name="agent_term_event_run_time_idx"),
        ),
    ]
