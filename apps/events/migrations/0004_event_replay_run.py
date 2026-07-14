import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0003_add_failed_event_model"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EventReplayRunModel",
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
                ("target_key", models.CharField(db_index=True, max_length=128)),
                ("normalized_request", models.JSONField(default=dict)),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("idempotency_key", models.CharField(max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "运行中"),
                            ("completed", "已完成"),
                            ("partial", "部分完成"),
                            ("failed", "失败"),
                        ],
                        default="running",
                        max_length=16,
                    ),
                ),
                ("attempted", models.PositiveIntegerField(default=0)),
                ("succeeded", models.PositiveIntegerField(default=0)),
                ("skipped", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("failures", models.JSONField(default=list)),
                ("result", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "requester",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="event_replay_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "event_replay_run",
                "indexes": [
                    models.Index(
                        fields=["requester", "-created_at"],
                        name="evt_replay_req_created_idx",
                    ),
                    models.Index(
                        fields=["target_key", "status"],
                        name="evt_replay_target_status_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("requester", "idempotency_key"),
                        name="evt_replay_requester_idem_uniq",
                    )
                ],
            },
        )
    ]
