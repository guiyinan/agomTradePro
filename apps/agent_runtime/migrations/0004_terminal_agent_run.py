import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create the dormant Terminal Agent dispatch ledger."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("agent_runtime", "0003_reproducible_execution_evidence"),
    ]

    operations = [
        migrations.CreateModel(
            name="TerminalAgentRunModel",
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
                ("run_id", models.CharField(max_length=128, unique=True)),
                ("client_request_id", models.CharField(max_length=128)),
                ("request_digest", models.CharField(max_length=64)),
                (
                    "runtime_mode",
                    models.CharField(
                        choices=[
                            ("web_queued", "WEB_QUEUED"),
                            ("local_cli", "LOCAL_CLI"),
                            ("legacy_inline", "LEGACY_INLINE"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "dispatch_status",
                    models.CharField(
                        choices=[
                            ("accepted", "ACCEPTED"),
                            ("queued", "QUEUED"),
                            ("claimed", "CLAIMED"),
                            ("running", "RUNNING"),
                            ("waiting_approval", "WAITING_APPROVAL"),
                            ("cancel_requested", "CANCEL_REQUESTED"),
                            ("cancelled", "CANCELLED"),
                            ("completed", "COMPLETED"),
                            ("failed", "FAILED"),
                            ("timed_out", "TIMED_OUT"),
                            ("orphaned", "ORPHANED"),
                        ],
                        default="queued",
                        max_length=32,
                    ),
                ),
                ("accepted_at", models.DateTimeField()),
                ("deadline_at", models.DateTimeField()),
                ("claimed_by", models.CharField(blank=True, max_length=128, null=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "actor_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="terminal_agent_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="terminal_agent_runs",
                        to="agent_runtime.agenttaskmodel",
                    ),
                ),
            ],
            options={
                "db_table": "agent_terminal_run",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="terminalagentrunmodel",
            constraint=models.UniqueConstraint(
                fields=("actor_user", "client_request_id"),
                name="agent_terminal_run_actor_client_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="terminalagentrunmodel",
            index=models.Index(
                fields=["actor_user", "created_at"],
                name="agent_term_actor_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="terminalagentrunmodel",
            index=models.Index(
                fields=["dispatch_status", "created_at"],
                name="agent_term_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="terminalagentrunmodel",
            index=models.Index(fields=["deadline_at"], name="agent_term_deadline_idx"),
        ),
    ]
