"""Create the empty Broker order approval artifact ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed order approval artifact persistence."""

    dependencies = [("broker_execution", "0007_r8_monitoring_reconciliation_receipt")]

    operations = [
        migrations.CreateModel(
            name="BrokerOrderApprovalArtifactModel",
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
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=64)),
                ("artifact_id", models.UUIDField()),
                ("artifact_version", models.CharField(max_length=128)),
                ("client_order_id", models.UUIDField()),
                ("account_id", models.PositiveBigIntegerField()),
                ("order_version", models.PositiveIntegerField()),
                ("approval_digest", models.CharField(max_length=64)),
                ("approved_actor_id", models.CharField(max_length=192)),
                ("approved_actor_user_id", models.PositiveBigIntegerField()),
                ("approved_actor_role", models.CharField(max_length=192)),
                ("approved_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "broker_execution_order_approval_artifact",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["client_order_id", "order_version", "recorded_at"],
                        name="broker_ord_ap_art_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("artifact_id", "artifact_version"),
                        name="broker_ord_ap_art_id_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("client_order_id", "order_version"),
                        name="broker_ord_ap_art_order_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("artifact_type", "live_order_approval_snapshot"),
                            ("owner", "broker_execution"),
                            ("schema", "broker-live-order-approval-artifact.v1"),
                        ),
                        name="broker_ord_ap_art_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("approved_at__lte", models.F("recorded_at")),
                            ("persisted_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="broker_ord_ap_art_clock_ck",
                    ),
                ],
            },
        )
    ]
