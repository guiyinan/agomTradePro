# Generated manually for schema-only R7 result Promotion/retirement ledgers.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0009_r2_market_structure_promotion_ledgers"),
    ]

    operations = [
        migrations.CreateModel(
            name="R7ResultLifecycleAuthorizationModel",
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
                ("result_key", models.CharField(max_length=192)),
                ("result_version", models.CharField(max_length=192)),
                ("result_content_hash", models.CharField(max_length=64)),
                ("authorization_id", models.CharField(max_length=192)),
                ("authorization_version", models.CharField(max_length=192)),
                ("event_id", models.CharField(max_length=192)),
                ("event_version", models.CharField(max_length=192)),
                ("action", models.CharField(max_length=16)),
                ("expected_sequence", models.PositiveIntegerField()),
                ("owner", models.CharField(max_length=96)),
                ("issued_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField()),
                ("reason_codes", models.JSONField()),
                ("evidence_ref", models.CharField(max_length=300)),
                ("canonical_payload", models.JSONField()),
                ("research_only", models.BooleanField(default=True)),
                (
                    "promotes_internal_research_record_only",
                    models.BooleanField(default=True),
                ),
                ("publishes_model_probability", models.BooleanField(default=False)),
                ("produces_decision", models.BooleanField(default=False)),
                ("executes_orders", models.BooleanField(default=False)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lifecycle_authorizations",
                        to="research.r7researchresultmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r7_result_lifecycle_authorization",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["result_key", "result_version", "recorded_at"],
                        name="res_r7_lc_auth_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("authorization_id", "authorization_version"),
                        name="res_r7_lc_auth_ident_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("event_id", "event_version"),
                        name="res_r7_lc_auth_event_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("issued_at__lte", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="res_r7_lc_auth_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("executes_orders", False),
                            ("must_not_execute", True),
                            ("must_not_use_for_decision", True),
                            ("owner", "research"),
                            ("produces_decision", False),
                            ("promotes_internal_research_record_only", True),
                            ("publishes_model_probability", False),
                            ("research_only", True),
                        ),
                        name="res_r7_lc_auth_safe_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R7ResultLifecycleEventModel",
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
                ("result_key", models.CharField(max_length=192)),
                ("result_version", models.CharField(max_length=192)),
                ("result_content_hash", models.CharField(max_length=64)),
                ("event_id", models.CharField(max_length=192)),
                ("event_version", models.CharField(max_length=192)),
                ("authorization_id", models.CharField(max_length=192)),
                ("authorization_version", models.CharField(max_length=192)),
                ("authorization_hash", models.CharField(max_length=64)),
                ("action", models.CharField(max_length=16)),
                ("sequence", models.PositiveIntegerField()),
                ("occurred_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("previous_event_hash", models.CharField(max_length=64, null=True)),
                ("reason_codes", models.JSONField()),
                ("canonical_payload", models.JSONField()),
                ("research_only", models.BooleanField(default=True)),
                (
                    "promotes_internal_research_record_only",
                    models.BooleanField(default=True),
                ),
                ("publishes_model_probability", models.BooleanField(default=False)),
                ("produces_decision", models.BooleanField(default=False)),
                ("executes_orders", models.BooleanField(default=False)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "authorization_record",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lifecycle_event",
                        to="research.r7resultlifecycleauthorizationmodel",
                    ),
                ),
                (
                    "result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lifecycle_events",
                        to="research.r7researchresultmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r7_result_lifecycle_event",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["result_key", "result_version", "recorded_at"],
                        name="res_r7_lc_event_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event_id", "event_version"),
                        name="res_r7_lc_event_ident_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("result", "sequence"),
                        name="res_r7_lc_event_seq_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("occurred_at__lte", models.F("recorded_at"))),
                        name="res_r7_lc_event_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("previous_event_hash__isnull", True), ("sequence", 1))
                        | models.Q(
                            ("previous_event_hash__isnull", False),
                            ("sequence__gt", 1),
                        ),
                        name="res_r7_lc_event_chain_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("executes_orders", False),
                            ("must_not_execute", True),
                            ("must_not_use_for_decision", True),
                            ("produces_decision", False),
                            ("promotes_internal_research_record_only", True),
                            ("publishes_model_probability", False),
                            ("research_only", True),
                        ),
                        name="res_r7_lc_event_safe_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R7ResearchResultAuditSnapshotModel",
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
                ("snapshot_id", models.CharField(max_length=192)),
                ("snapshot_version", models.CharField(max_length=192)),
                ("as_of", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(db_index=True)),
                ("entry_count", models.PositiveIntegerField()),
                ("canonical_payload", models.JSONField()),
                ("internal_audit_only", models.BooleanField(default=True)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_r7_result_audit_snapshot",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["as_of", "created_at"],
                        name="res_r7_audit_snap_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot_id", "snapshot_version"),
                        name="res_r7_audit_snap_ident_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("as_of__lte", models.F("created_at"))),
                        name="res_r7_audit_snap_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("internal_audit_only", True),
                            ("must_not_execute", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="res_r7_audit_snap_safe_ck",
                    ),
                ],
            },
        ),
    ]
