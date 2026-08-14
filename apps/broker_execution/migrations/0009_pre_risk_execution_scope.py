"""Create the empty Broker pre-Risk execution scope ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed pre-Risk scope persistence."""

    dependencies = [("broker_execution", "0008_order_approval_artifact")]

    operations = [
        migrations.CreateModel(
            name="BrokerPreRiskExecutionScopeModel",
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
                ("scope_id", models.CharField(max_length=192)),
                ("scope_version", models.CharField(max_length=64)),
                ("permission", models.CharField(max_length=16)),
                ("broker_account_id", models.PositiveBigIntegerField()),
                ("portfolio_account_id", models.CharField(max_length=192)),
                ("plan_id", models.CharField(max_length=192)),
                ("plan_version", models.PositiveIntegerField()),
                ("plan_content_hash", models.CharField(max_length=64)),
                ("portfolio_receipt_id", models.CharField(max_length=192)),
                ("portfolio_receipt_version", models.CharField(max_length=192)),
                ("portfolio_receipt_content_hash", models.CharField(max_length=64)),
                ("order_artifact_id", models.UUIDField()),
                ("order_artifact_version", models.CharField(max_length=192)),
                ("order_artifact_content_hash", models.CharField(max_length=64)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "supersedes_scope_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "broker_execution_pre_risk_scope",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=[
                            "broker_account_id",
                            "order_artifact_id",
                            "recorded_at",
                        ],
                        name="broker_pre_risk_chain_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scope_id", "scope_version"),
                        name="broker_pre_risk_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("owner", "broker_execution"),
                            ("permission", "inactive"),
                            (
                                "scope_version",
                                "broker-pre-risk-execution-scope.v1",
                            ),
                        ),
                        name="broker_pre_risk_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("persisted_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="broker_pre_risk_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("root_claim_hash__isnull", False),
                                ("supersedes_scope_hash__isnull", True),
                            )
                            | models.Q(
                                ("root_claim_hash__isnull", True),
                                ("supersedes_scope_hash__isnull", False),
                            )
                        ),
                        name="broker_pre_risk_link_ck",
                    ),
                ],
            },
        )
    ]
