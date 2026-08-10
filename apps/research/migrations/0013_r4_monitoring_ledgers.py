import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0012_r6_activation_ledgers"),
    ]

    operations = [
        migrations.CreateModel(
            name="R4MonitoringAuditSnapshotModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("snapshot_id", models.CharField(max_length=192)),
                ("snapshot_version", models.CharField(max_length=192)),
                ("as_of", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(db_index=True)),
                ("entry_count", models.PositiveIntegerField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64)),
                ("internal_audit_only", models.BooleanField(default=True)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_publish_current", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_r4_monitoring_audit_snapshot",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(fields=["as_of", "created_at"], name="res_r4_mon_snap_pit_ix")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot_id", "snapshot_version"), name="res_r4_mon_snap_ident_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("as_of__lte", models.F("created_at"))),
                        name="res_r4_mon_snap_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("internal_audit_only", True),
                            ("must_not_execute", True),
                            ("must_not_publish_current", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="res_r4_mon_snap_safe_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R4MonitoringAssessmentLedgerModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("assessment_id", models.CharField(max_length=192, unique=True)),
                ("active_decision_stable_id", models.CharField(max_length=192)),
                ("active_decision_version", models.CharField(max_length=192)),
                ("active_decision_hash", models.CharField(max_length=64)),
                ("requested_policy_id", models.CharField(max_length=192)),
                ("requested_policy_version", models.CharField(max_length=192)),
                ("expected_policy_hash", models.CharField(max_length=64)),
                ("policy_hash", models.CharField(max_length=64)),
                ("period_calendar_id", models.CharField(max_length=192)),
                ("period_calendar_version", models.CharField(max_length=192)),
                ("period_calendar_hash", models.CharField(max_length=64)),
                ("portfolio_record_content_hash", models.CharField(max_length=64)),
                ("r3_attestation_content_hash", models.CharField(max_length=64)),
                ("evaluated_at", models.DateTimeField()),
                ("active_decision_owner_recorded_at", models.DateTimeField()),
                ("portfolio_owner_recorded_at", models.DateTimeField()),
                ("r3_owner_known_at", models.DateTimeField()),
                ("policy_owner_recorded_at", models.DateTimeField()),
                ("calendar_owner_recorded_at", models.DateTimeField()),
                ("latest_observation_owner_recorded_at", models.DateTimeField()),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("ledger_header_hash", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=48)),
                ("observation_count", models.PositiveIntegerField()),
                ("metric_result_count", models.PositiveIntegerField()),
                ("observation_hashes", models.JSONField()),
                ("blockers", models.JSONField()),
                ("review_reason_codes", models.JSONField()),
                ("active_decision_payload", models.JSONField()),
                ("portfolio_result_payload", models.JSONField()),
                ("r3_attestation_payload", models.JSONField()),
                ("policy_payload", models.JSONField()),
                ("period_calendar_payload", models.JSONField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("label_drift_detected", models.BooleanField()),
                ("data_drift_detected", models.BooleanField()),
                ("retirement_review_required", models.BooleanField()),
                ("automatic_retirement", models.BooleanField(default=False)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_publish_current", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "active_decision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="monitoring_assessment_ledgers",
                        to="research.r4promotiondecisionbundlemodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r4_monitoring_assessment",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["active_decision", "expected_policy_hash", "ledger_recorded_at"],
                        name="res_r4_mon_asmt_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "active_decision_stable_id",
                            "active_decision_version",
                            "expected_policy_hash",
                            "evaluated_at",
                        ),
                        name="res_r4_mon_asmt_cmd_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("active_decision_owner_recorded_at__lte", models.F("evaluated_at")),
                            ("portfolio_owner_recorded_at__lte", models.F("evaluated_at")),
                            ("r3_owner_known_at__lte", models.F("evaluated_at")),
                            ("policy_owner_recorded_at__lte", models.F("evaluated_at")),
                            ("calendar_owner_recorded_at__lte", models.F("evaluated_at")),
                            ("latest_observation_owner_recorded_at__lte", models.F("evaluated_at")),
                            ("evaluated_at__lte", models.F("ledger_recorded_at")),
                        ),
                        name="res_r4_mon_asmt_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "status__in",
                                (
                                    "healthy",
                                    "breached",
                                    "retirement_review_required",
                                    "blocked",
                                ),
                            )
                        ),
                        name="res_r4_mon_asmt_status_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("automatic_retirement", False),
                            ("must_not_execute", True),
                            ("must_not_publish_current", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="res_r4_mon_asmt_safe_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R4MonitoringObservationLedgerModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("observation_id", models.CharField(max_length=192)),
                ("observation_version", models.CharField(max_length=192)),
                ("active_decision_stable_id", models.CharField(max_length=192)),
                ("active_decision_version", models.CharField(max_length=192)),
                ("active_decision_hash", models.CharField(max_length=64)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("policy_hash", models.CharField(max_length=64)),
                ("period_calendar_id", models.CharField(max_length=192)),
                ("period_calendar_version", models.CharField(max_length=192)),
                ("period_calendar_hash", models.CharField(max_length=64)),
                ("period_id", models.CharField(max_length=64)),
                ("period_start", models.DateTimeField()),
                ("period_end", models.DateTimeField()),
                ("source_owner", models.CharField(max_length=192)),
                ("portfolio_record_id", models.CharField(max_length=192)),
                ("portfolio_record_hash", models.CharField(max_length=64)),
                ("portfolio_record_content_hash", models.CharField(max_length=64)),
                ("r3_attestation_content_hash", models.CharField(max_length=64)),
                ("observed_at", models.DateTimeField()),
                ("available_at", models.DateTimeField()),
                ("owner_recorded_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("pit_manifest_id", models.CharField(max_length=192)),
                ("pit_manifest_hash", models.CharField(max_length=64)),
                ("evidence_ref", models.CharField(max_length=300)),
                ("label_protocol_version", models.CharField(max_length=192)),
                ("observed_label_set_hash", models.CharField(max_length=64)),
                ("observed_data_schema_hash", models.CharField(max_length=64)),
                ("metric_count", models.PositiveIntegerField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("ledger_header_hash", models.CharField(max_length=64)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_publish_current", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "active_decision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="monitoring_observation_ledgers",
                        to="research.r4promotiondecisionbundlemodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r4_monitoring_observation",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["active_decision", "policy_hash", "ledger_recorded_at"],
                        name="res_r4_mon_obs_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("observation_id", "observation_version"),
                        name="res_r4_mon_obs_ident_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("active_decision", "policy_hash", "period_id"),
                        name="res_r4_mon_obs_period_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("period_start__lt", models.F("period_end")),
                            ("period_end__lte", models.F("observed_at")),
                            ("observed_at__lte", models.F("available_at")),
                            ("available_at__lte", models.F("owner_recorded_at")),
                            ("owner_recorded_at__lt", models.F("valid_until")),
                            ("owner_recorded_at__lte", models.F("ledger_recorded_at")),
                        ),
                        name="res_r4_mon_obs_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("must_not_execute", True),
                            ("must_not_publish_current", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="res_r4_mon_obs_safe_ck",
                    ),
                ],
            },
        ),
    ]
