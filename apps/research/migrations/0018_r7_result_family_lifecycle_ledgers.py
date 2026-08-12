import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0017_r7_post_promotion_monitoring_ledgers"),
    ]

    operations = [
        migrations.CreateModel(
            name="R7FamilyLifecycleAuditSnapshotModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("snapshot_id", models.CharField(max_length=192)),
                ("snapshot_version", models.CharField(max_length=96)),
                ("family_id", models.CharField(max_length=192)),
                ("family_version", models.CharField(max_length=192)),
                ("family_hash", models.CharField(max_length=64)),
                ("as_of", models.DateTimeField()),
                ("total_count", models.PositiveIntegerField()),
                ("manifest_hash", models.CharField(max_length=64)),
                ("payload_schema_version", models.CharField(max_length=96)),
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField()),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "research_r7_family_lifecycle_audit_snapshot",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot_id", "snapshot_version"), name="res_r7_fam_audit_ident_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("as_of__lte", models.F("created_at")),
                            ("created_at__lte", models.F("ledger_recorded_at")),
                        ),
                        name="res_r7_fam_audit_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R7FamilyLifecycleAuthorizationModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("authorization_id", models.CharField(max_length=192)),
                ("authorization_version", models.CharField(max_length=192)),
                ("family_id", models.CharField(max_length=192)),
                ("family_version", models.CharField(max_length=192)),
                ("family_hash", models.CharField(max_length=64)),
                ("event_id", models.CharField(max_length=192)),
                ("event_version", models.CharField(max_length=192)),
                ("action", models.CharField(max_length=16)),
                ("expected_sequence", models.PositiveIntegerField()),
                ("expected_previous_event_id", models.CharField(max_length=192, null=True)),
                ("expected_previous_event_version", models.CharField(max_length=192, null=True)),
                ("expected_previous_event_hash", models.CharField(max_length=64, null=True)),
                ("subject_result_id_value", models.CharField(max_length=192)),
                ("subject_result_version", models.CharField(max_length=192)),
                ("subject_result_hash", models.CharField(max_length=64)),
                ("subject_owner_attestation_hash", models.CharField(max_length=64)),
                ("rollback_target_result_id_value", models.CharField(max_length=192, null=True)),
                ("rollback_target_result_version", models.CharField(max_length=192, null=True)),
                ("rollback_target_result_hash", models.CharField(max_length=64, null=True)),
                (
                    "rollback_target_owner_attestation_hash",
                    models.CharField(max_length=64, null=True),
                ),
                ("owner", models.CharField(max_length=64)),
                ("issued_at", models.DateTimeField()),
                ("owner_recorded_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("payload_schema_version", models.CharField(max_length=96)),
                ("payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("row_hash", models.CharField(max_length=64, unique=True)),
                (
                    "rollback_target_local_lifecycle_head",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7resultlifecycleeventmodel",
                    ),
                ),
                (
                    "rollback_target_result",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7researchresultmodel",
                    ),
                ),
                (
                    "subject_local_lifecycle_head",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7resultlifecycleeventmodel",
                    ),
                ),
                (
                    "subject_result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7researchresultmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r7_family_lifecycle_authorization",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="R7FamilyLifecycleEventModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("family_id", models.CharField(max_length=192)),
                ("family_version", models.CharField(max_length=192)),
                ("family_hash", models.CharField(max_length=64)),
                ("event_id", models.CharField(max_length=192)),
                ("event_version", models.CharField(max_length=192)),
                ("action", models.CharField(max_length=16)),
                ("sequence", models.PositiveIntegerField()),
                ("occurred_at", models.DateTimeField()),
                ("owner_recorded_at", models.DateTimeField()),
                ("previous_event_hash", models.CharField(max_length=64, null=True)),
                ("payload_schema_version", models.CharField(max_length=96)),
                ("payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("row_hash", models.CharField(max_length=64, unique=True)),
                (
                    "authorization_row",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7familylifecycleauthorizationmodel",
                    ),
                ),
                (
                    "rollback_target_local_lifecycle_head",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7resultlifecycleeventmodel",
                    ),
                ),
                (
                    "rollback_target_result",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7researchresultmodel",
                    ),
                ),
                (
                    "subject_local_lifecycle_head",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7resultlifecycleeventmodel",
                    ),
                ),
                (
                    "subject_result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7researchresultmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r7_family_lifecycle_event",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="R7FamilyLifecycleStreamCommitModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("family_id", models.CharField(max_length=192)),
                ("family_version", models.CharField(max_length=192)),
                ("family_hash", models.CharField(max_length=64)),
                ("sequence", models.PositiveIntegerField()),
                ("authorization_id", models.CharField(max_length=192)),
                ("authorization_version", models.CharField(max_length=192)),
                ("authorization_hash", models.CharField(max_length=64)),
                ("event_id", models.CharField(max_length=192)),
                ("event_version", models.CharField(max_length=192)),
                ("event_hash", models.CharField(max_length=64)),
                ("subject_result_hash", models.CharField(max_length=64)),
                ("subject_local_lifecycle_head_hash", models.CharField(max_length=64)),
                ("rollback_target_result_hash", models.CharField(max_length=64, null=True)),
                (
                    "rollback_target_local_lifecycle_head_hash",
                    models.CharField(max_length=64, null=True),
                ),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                (
                    "authorization_row",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7familylifecycleauthorizationmodel",
                    ),
                ),
                (
                    "event_row",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="research.r7familylifecycleeventmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r7_family_lifecycle_stream_commit",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AddIndex(
            model_name="r7familylifecycleauthorizationmodel",
            index=models.Index(
                fields=["family_id", "family_version", "ledger_recorded_at"],
                name="res_r7_fam_auth_pit_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleauthorizationmodel",
            constraint=models.UniqueConstraint(
                fields=("authorization_id", "authorization_version"),
                name="res_r7_fam_auth_ident_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleauthorizationmodel",
            constraint=models.UniqueConstraint(
                fields=("event_id", "event_version"), name="res_r7_fam_auth_event_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleauthorizationmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("issued_at__lte", models.F("owner_recorded_at")),
                    ("owner_recorded_at__lt", models.F("valid_until")),
                    ("owner_recorded_at__lte", models.F("ledger_recorded_at")),
                ),
                name="res_r7_fam_auth_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleauthorizationmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("expected_previous_event_hash__isnull", True),
                        ("expected_previous_event_id__isnull", True),
                        ("expected_previous_event_version__isnull", True),
                        ("expected_sequence", 1),
                    ),
                    models.Q(
                        ("expected_previous_event_hash__isnull", False),
                        ("expected_previous_event_id__isnull", False),
                        ("expected_previous_event_version__isnull", False),
                        ("expected_sequence__gt", 1),
                    ),
                    _connector="OR",
                ),
                name="res_r7_fam_auth_prev_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleauthorizationmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("action", "rollback"),
                        ("rollback_target_local_lifecycle_head__isnull", False),
                        ("rollback_target_owner_attestation_hash__isnull", False),
                        ("rollback_target_result__isnull", False),
                        ("rollback_target_result_hash__isnull", False),
                        ("rollback_target_result_id_value__isnull", False),
                        ("rollback_target_result_version__isnull", False),
                    ),
                    models.Q(
                        ("action__in", ("promote", "retire")),
                        ("rollback_target_local_lifecycle_head__isnull", True),
                        ("rollback_target_owner_attestation_hash__isnull", True),
                        ("rollback_target_result__isnull", True),
                        ("rollback_target_result_hash__isnull", True),
                        ("rollback_target_result_id_value__isnull", True),
                        ("rollback_target_result_version__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="res_r7_fam_auth_target_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="r7familylifecycleeventmodel",
            index=models.Index(
                fields=["family_id", "family_version", "ledger_recorded_at"],
                name="res_r7_fam_evt_pit_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleeventmodel",
            constraint=models.UniqueConstraint(
                fields=("event_id", "event_version"), name="res_r7_fam_evt_ident_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleeventmodel",
            constraint=models.UniqueConstraint(
                fields=("family_id", "family_version", "sequence"), name="res_r7_fam_evt_id_seq_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleeventmodel",
            constraint=models.UniqueConstraint(
                fields=("family_hash", "sequence"), name="res_r7_fam_evt_hash_seq_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleeventmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("occurred_at__lte", models.F("owner_recorded_at")),
                    ("owner_recorded_at__lte", models.F("ledger_recorded_at")),
                ),
                name="res_r7_fam_evt_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleeventmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("previous_event_hash__isnull", True), ("sequence", 1)),
                    models.Q(("previous_event_hash__isnull", False), ("sequence__gt", 1)),
                    _connector="OR",
                ),
                name="res_r7_fam_evt_prev_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecycleeventmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("action", "rollback"),
                        ("rollback_target_local_lifecycle_head__isnull", False),
                        ("rollback_target_result__isnull", False),
                    ),
                    models.Q(
                        ("action__in", ("promote", "retire")),
                        ("rollback_target_local_lifecycle_head__isnull", True),
                        ("rollback_target_result__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="res_r7_fam_evt_target_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecyclestreamcommitmodel",
            constraint=models.UniqueConstraint(
                fields=("family_id", "family_version", "sequence"), name="res_r7_fam_com_id_seq_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecyclestreamcommitmodel",
            constraint=models.UniqueConstraint(
                fields=("family_hash", "sequence"), name="res_r7_fam_com_hash_seq_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecyclestreamcommitmodel",
            constraint=models.UniqueConstraint(
                fields=("authorization_id", "authorization_version"), name="res_r7_fam_com_auth_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="r7familylifecyclestreamcommitmodel",
            constraint=models.UniqueConstraint(
                fields=("event_id", "event_version"), name="res_r7_fam_com_event_uq"
            ),
        ),
    ]
