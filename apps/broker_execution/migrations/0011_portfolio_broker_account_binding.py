"""Create the empty Broker/Portfolio account namespace binding ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed account namespace binding persistence."""

    dependencies = [("broker_execution", "0010_broker_account_identity_snapshot")]

    operations = [
        migrations.CreateModel(
            name="BrokerPortfolioAccountBindingModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("binding_id", models.CharField(max_length=192)),
                ("binding_version", models.CharField(max_length=64)),
                ("permission", models.CharField(max_length=16)),
                ("blocker_codes", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("broker_account_namespace", models.CharField(max_length=192)),
                ("broker_account_id", models.PositiveBigIntegerField()),
                ("portfolio_account_namespace", models.CharField(max_length=192)),
                ("portfolio_account_id", models.CharField(max_length=192)),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("account_type", models.CharField(max_length=16)),
                ("source_accounts_active", models.BooleanField()),
                ("broker_source_owner", models.CharField(max_length=32)),
                ("broker_source_artifact_type", models.CharField(max_length=64)),
                ("broker_source_id", models.CharField(max_length=192)),
                ("broker_source_version", models.CharField(max_length=192)),
                ("broker_source_content_hash", models.CharField(max_length=64)),
                ("portfolio_source_owner", models.CharField(max_length=32)),
                ("portfolio_source_artifact_type", models.CharField(max_length=64)),
                ("portfolio_source_id", models.CharField(max_length=192)),
                ("portfolio_source_version", models.CharField(max_length=192)),
                ("portfolio_source_content_hash", models.CharField(max_length=64)),
                ("actor_id", models.CharField(max_length=192)),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("actor_role", models.CharField(max_length=192)),
                ("actor_kind", models.CharField(max_length=16)),
                ("actor_is_staff", models.BooleanField()),
                ("issued_at", models.DateTimeField()),
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
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "broker_execution_portfolio_account_binding",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["broker_account_namespace", "broker_account_id", "recorded_at"],
                        name="broker_portfolio_bind_chain_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("binding_id", "binding_version"), name="broker_portfolio_bind_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("account_type", "real"),
                            ("actor_is_staff", True),
                            ("actor_kind", "human"),
                            ("binding_version", "broker-portfolio-account-namespace-binding.v1"),
                            ("broker_source_artifact_type", "broker_account_identity_snapshot"),
                            ("broker_source_owner", "broker_execution"),
                            ("owner", "broker_execution"),
                            ("permission", "inactive"),
                            ("portfolio_source_artifact_type", "account_identity_snapshot"),
                            ("portfolio_source_owner", "account"),
                            ("source_accounts_active", True),
                        ),
                        name="broker_portfolio_bind_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("issued_at__lte", models.F("recorded_at")),
                            ("persisted_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="broker_portfolio_bind_clock_ck",
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
                        name="broker_portfolio_bind_link_ck",
                    ),
                ],
            },
        )
    ]
