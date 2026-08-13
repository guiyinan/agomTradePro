"""Create the empty Account identity snapshot append-only ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Account identity snapshot persistence."""

    dependencies = [
        ("account", "0036_assetcategorymodel_account_asset_category_level_positive_and_more")
    ]

    operations = [
        migrations.CreateModel(
            name="AccountIdentitySnapshotModel",
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
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
                ("account_namespace", models.CharField(max_length=192)),
                ("account_id", models.CharField(max_length=192)),
                ("underlying_unified_account_namespace", models.CharField(max_length=192)),
                ("underlying_unified_account_id", models.PositiveBigIntegerField()),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("account_type", models.CharField(max_length=16)),
                ("is_active", models.BooleanField()),
                ("provenance_kind", models.CharField(max_length=32)),
                ("legacy_default_user_assignment", models.BooleanField()),
                ("underlying_source_id", models.CharField(max_length=192)),
                ("underlying_source_version", models.CharField(max_length=192)),
                ("underlying_source_content_hash", models.CharField(max_length=64)),
                ("underlying_source_recorded_at", models.DateTimeField()),
                ("underlying_source_valid_until", models.DateTimeField()),
                ("ttl_valid_until", models.DateTimeField()),
                ("issued_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "reclaim_receipt_owner",
                    models.CharField(blank=True, max_length=32, null=True),
                ),
                (
                    "reclaim_receipt_artifact_type",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "reclaim_receipt_id",
                    models.CharField(blank=True, max_length=192, null=True),
                ),
                (
                    "reclaim_receipt_version",
                    models.CharField(blank=True, max_length=192, null=True),
                ),
                (
                    "reclaim_receipt_content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("blocker_codes", models.JSONField()),
                ("issued_actor_id", models.CharField(max_length=192)),
                ("issued_actor_user_id", models.PositiveBigIntegerField()),
                ("issued_actor_role", models.CharField(max_length=192)),
                ("issued_actor_kind", models.CharField(max_length=16)),
                ("issued_actor_is_staff", models.BooleanField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("actor_binding_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_identity_snapshot_ledger",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["account_namespace", "account_id", "recorded_at"],
                        name="account_id_snap_chain_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"),
                        name="account_id_snap_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            owner="account",
                            artifact_type="account_identity_snapshot",
                            schema="account-identity-snapshot.v1",
                            permission="identity_evidence_only",
                            status="inactive",
                            account_type="real",
                            is_active=True,
                            issued_actor_kind="human",
                            issued_actor_is_staff=True,
                        ),
                        name="account_id_snap_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                underlying_source_recorded_at__lte=models.F("issued_at"),
                                issued_at__lte=models.F("recorded_at"),
                                recorded_at__lt=models.F("valid_until"),
                                valid_until__lte=models.F("underlying_source_valid_until"),
                                persisted_at=models.F("recorded_at"),
                            )
                            & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                        ),
                        name="account_id_snap_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                supersedes_content_hash__isnull=True,
                                root_claim_hash__isnull=False,
                            )
                            | models.Q(
                                supersedes_content_hash__isnull=False,
                                root_claim_hash__isnull=True,
                            )
                        ),
                        name="account_id_snap_link_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                provenance_kind="authoritative",
                                legacy_default_user_assignment=False,
                                reclaim_receipt_owner__isnull=True,
                                reclaim_receipt_artifact_type__isnull=True,
                                reclaim_receipt_id__isnull=True,
                                reclaim_receipt_version__isnull=True,
                                reclaim_receipt_content_hash__isnull=True,
                            )
                            | models.Q(
                                provenance_kind="manual_reclaim",
                                legacy_default_user_assignment=True,
                                reclaim_receipt_owner="account",
                                reclaim_receipt_artifact_type="account_owner_reclaim_receipt",
                                reclaim_receipt_id__isnull=False,
                                reclaim_receipt_version__isnull=False,
                                reclaim_receipt_content_hash__isnull=False,
                            )
                        ),
                        name="account_id_snap_prov_ck",
                    ),
                ],
            },
        )
    ]
