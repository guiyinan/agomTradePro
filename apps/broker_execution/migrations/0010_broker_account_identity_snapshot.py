"""Create the empty Broker account identity snapshot ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Broker account identity persistence."""

    dependencies = [("broker_execution", "0009_pre_risk_execution_scope")]

    operations = [
        migrations.CreateModel(
            name="BrokerAccountIdentitySnapshotModel",
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
                ("authority_scope", models.CharField(max_length=32)),
                ("permission", models.CharField(max_length=16)),
                ("snapshot_id", models.CharField(max_length=192)),
                ("snapshot_version", models.CharField(max_length=192)),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("broker_account_namespace", models.CharField(max_length=192)),
                ("broker_account_id", models.PositiveBigIntegerField()),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("account_source_owner", models.CharField(max_length=32)),
                ("account_source_artifact_type", models.CharField(max_length=64)),
                ("account_source_id", models.CharField(max_length=192)),
                ("account_source_version", models.CharField(max_length=192)),
                ("account_source_content_hash", models.CharField(max_length=64)),
                ("account_namespace", models.CharField(max_length=192)),
                ("account_id", models.CharField(max_length=192)),
                ("account_source_owner_user_id", models.PositiveBigIntegerField()),
                ("account_type", models.CharField(max_length=16)),
                ("is_active", models.BooleanField()),
                ("account_source_recorded_at", models.DateTimeField()),
                ("account_source_valid_until", models.DateTimeField()),
                ("binding_revision", models.PositiveBigIntegerField()),
                ("binding_owner_user_id", models.PositiveBigIntegerField()),
                ("binding_content_hash", models.CharField(max_length=64)),
                ("agent_id", models.CharField(max_length=192)),
                ("agent_version", models.CharField(max_length=192)),
                ("agent_owner_user_id", models.PositiveBigIntegerField()),
                ("agent_content_hash", models.CharField(max_length=64)),
                ("qmt_digest_algorithm", models.CharField(max_length=32)),
                ("qmt_digest_key_id", models.CharField(max_length=192)),
                ("qmt_digest", models.CharField(max_length=64)),
                ("broker_account_category", models.CharField(max_length=192)),
                ("issued_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("ttl_valid_until", models.DateTimeField()),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "supersedes_snapshot_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("actor_id", models.CharField(max_length=192)),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("actor_kind", models.CharField(max_length=16)),
                ("actor_is_staff", models.BooleanField()),
                ("canonical_payload", models.JSONField()),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "broker_execution_account_identity_snapshot",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=[
                            "broker_account_namespace",
                            "broker_account_id",
                            "recorded_at",
                        ],
                        name="broker_acct_identity_chain_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot_id", "snapshot_version"),
                        name="broker_acct_identity_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("account_source_artifact_type", "account_identity_snapshot"),
                            ("account_source_owner", "account"),
                            ("account_type", "real"),
                            ("actor_is_staff", True),
                            ("actor_kind", "human"),
                            ("artifact_type", "broker_account_identity_snapshot"),
                            ("authority_scope", "identity_evidence_only"),
                            ("is_active", True),
                            ("owner", "broker_execution"),
                            ("permission", "inactive"),
                            ("schema", "broker-account-identity-snapshot.v1"),
                        ),
                        name="broker_acct_identity_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("issued_at__lte", models.F("recorded_at")),
                                ("persisted_at", models.F("recorded_at")),
                                ("recorded_at__lt", models.F("valid_until")),
                                ("valid_until__lte", models.F("ttl_valid_until")),
                            )
                            & models.Q(
                                (
                                    "valid_until__lte",
                                    models.F("account_source_valid_until"),
                                )
                            )
                        ),
                        name="broker_acct_identity_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("root_claim_hash__isnull", False),
                                ("supersedes_snapshot_hash__isnull", True),
                            )
                            | models.Q(
                                ("root_claim_hash__isnull", True),
                                ("supersedes_snapshot_hash__isnull", False),
                            )
                        ),
                        name="broker_acct_identity_link_ck",
                    ),
                ],
            },
        )
    ]
