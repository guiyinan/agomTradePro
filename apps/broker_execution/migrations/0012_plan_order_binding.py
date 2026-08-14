"""Create the empty Broker Plan-to-Order binding ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Plan-to-Order binding persistence."""

    dependencies = [("broker_execution", "0011_portfolio_broker_account_binding")]

    operations = [
        migrations.CreateModel(
            name="BrokerPlanOrderBindingModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=64)),
                ("permission", models.CharField(max_length=16)),
                ("blocker_codes", models.JSONField()),
                ("binding_id", models.CharField(max_length=192)),
                ("binding_version", models.CharField(max_length=64)),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("portfolio_plan_owner", models.CharField(max_length=32)),
                ("portfolio_plan_artifact_type", models.CharField(max_length=64)),
                ("portfolio_plan_id", models.CharField(max_length=192)),
                ("portfolio_plan_version", models.PositiveBigIntegerField()),
                ("portfolio_plan_content_hash", models.CharField(max_length=64)),
                ("portfolio_plan_valid_until", models.DateTimeField()),
                ("portfolio_account_id", models.CharField(max_length=192)),
                ("portfolio_receipt_owner", models.CharField(max_length=32)),
                ("portfolio_receipt_capability", models.CharField(max_length=64)),
                ("portfolio_receipt_id", models.CharField(max_length=192)),
                ("portfolio_receipt_version", models.CharField(max_length=192)),
                ("portfolio_receipt_content_hash", models.CharField(max_length=64)),
                ("portfolio_receipt_valid_until", models.DateTimeField()),
                ("portfolio_subject_id", models.CharField(max_length=192)),
                ("portfolio_subject_version", models.CharField(max_length=192)),
                ("portfolio_subject_content_hash", models.CharField(max_length=64)),
                ("plan_order_ordinal", models.PositiveBigIntegerField()),
                ("plan_order_payload_json", models.TextField()),
                ("plan_order_content_hash", models.CharField(max_length=64)),
                ("broker_account_id", models.PositiveBigIntegerField()),
                ("order_artifact_owner", models.CharField(max_length=32)),
                ("order_artifact_type", models.CharField(max_length=64)),
                ("order_artifact_id", models.UUIDField()),
                ("order_artifact_version", models.CharField(max_length=192)),
                ("order_artifact_identity_hash", models.CharField(max_length=64)),
                ("order_artifact_content_hash", models.CharField(max_length=64)),
                ("order_artifact_valid_until", models.DateTimeField()),
                ("order_approval_digest", models.CharField(max_length=64)),
                ("order_version", models.PositiveBigIntegerField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "supersedes_binding_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("canonical_payload", models.JSONField()),
                ("canonical_row_byte_hash", models.CharField(max_length=64)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "broker_execution_plan_order_binding",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=[
                            "portfolio_plan_id",
                            "portfolio_plan_version",
                            "plan_order_ordinal",
                            "order_artifact_id",
                            "recorded_at",
                        ],
                        name="broker_plan_order_chain_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("binding_id", "binding_version"), name="broker_plan_order_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("artifact_type", "plan_order_binding"),
                            ("binding_version", "broker-plan-order-binding.v1"),
                            ("order_artifact_owner", "broker_execution"),
                            ("order_artifact_type", "live_order_approval_snapshot"),
                            ("owner", "broker_execution"),
                            ("permission", "inactive"),
                            ("portfolio_plan_artifact_type", "transition_plan_definition"),
                            ("portfolio_plan_owner", "portfolio"),
                            ("portfolio_receipt_capability", "transition_plan_inactive_approval"),
                            ("portfolio_receipt_owner", "portfolio"),
                            ("schema", "broker-plan-order-binding.v1"),
                        ),
                        name="broker_plan_order_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("persisted_at", models.F("recorded_at")),
                                ("recorded_at__lt", models.F("valid_until")),
                                ("valid_until__lte", models.F("portfolio_plan_valid_until")),
                            )
                            & models.Q(
                                ("valid_until__lte", models.F("portfolio_receipt_valid_until"))
                            )
                            & models.Q(("valid_until__lte", models.F("order_artifact_valid_until")))
                        ),
                        name="broker_plan_order_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("root_claim_hash__isnull", False),
                                ("supersedes_binding_hash__isnull", True),
                            )
                            | models.Q(
                                ("root_claim_hash__isnull", True),
                                ("supersedes_binding_hash__isnull", False),
                            )
                        ),
                        name="broker_plan_order_link_ck",
                    ),
                ],
            },
        )
    ]
