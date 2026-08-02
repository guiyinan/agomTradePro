import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("config_center", "0005_systemsettings_decision_runtime_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="RuntimeConfigDefinitionModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("key", models.CharField(db_index=True, max_length=180, unique=True)),
                ("namespace", models.CharField(db_index=True, max_length=80)),
                ("owner_app", models.CharField(db_index=True, max_length=100)),
                (
                    "value_type",
                    models.CharField(
                        choices=[
                            ("bool", "bool"),
                            ("int", "int"),
                            ("decimal", "decimal"),
                            ("string", "string"),
                            ("duration", "duration"),
                            ("bytes", "bytes"),
                            ("percentage", "percentage"),
                            ("enum", "enum"),
                            ("typed_json", "typed_json"),
                        ],
                        max_length=24,
                    ),
                ),
                ("unit", models.CharField(blank=True, max_length=40)),
                ("constraints", models.JSONField(blank=True, default=dict)),
                (
                    "criticality",
                    models.CharField(
                        choices=[
                            ("bootstrap", "bootstrap"),
                            ("critical", "critical"),
                            ("normal", "normal"),
                            ("experimental", "experimental"),
                        ],
                        db_index=True,
                        default="normal",
                        max_length=20,
                    ),
                ),
                ("secret", models.BooleanField(default=False)),
                (
                    "reload_mode",
                    models.CharField(
                        choices=[
                            ("immediate", "immediate"),
                            ("next_task", "next_task"),
                            ("restart_required", "restart_required"),
                        ],
                        default="next_task",
                        max_length=24,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("user_impact", models.TextField(blank=True)),
                ("is_deprecated", models.BooleanField(default=False)),
                ("replacement_key", models.CharField(blank=True, max_length=180)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "config_center_runtime_config_definition",
                "ordering": ["namespace", "key"],
                "indexes": [
                    models.Index(
                        fields=["owner_app", "criticality"], name="config_cent_owner_a_7e809e_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RuntimeConfigProfileModel",
            fields=[
                (
                    "profile_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("profile_key", models.CharField(db_index=True, max_length=120)),
                ("environment", models.CharField(db_index=True, max_length=40)),
                ("version", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "draft"),
                            ("validating", "validating"),
                            ("active", "active"),
                            ("superseded", "superseded"),
                            ("rejected", "rejected"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("based_on_profile", models.CharField(blank=True, max_length=120)),
                ("content_hash", models.CharField(blank=True, db_index=True, max_length=128)),
                ("created_by", models.CharField(default="system", max_length=150)),
                ("activated_by", models.CharField(blank=True, max_length=150)),
                (
                    "created_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("change_reason", models.TextField(blank=True)),
                ("release_ref", models.CharField(blank=True, max_length=100)),
            ],
            options={
                "db_table": "config_center_runtime_config_profile",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["environment", "status"], name="config_cent_environ_4c18d8_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile_key", "version"),
                        name="config_center_runtime_profile_version_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RuntimeConfigRevisionModel",
            fields=[
                (
                    "revision_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("profile_id", models.UUIDField(db_index=True)),
                ("before_hash", models.CharField(blank=True, max_length=128)),
                ("after_hash", models.CharField(max_length=128)),
                ("changed_keys", models.JSONField(default=list)),
                ("before_projection", models.JSONField(default=dict)),
                ("after_projection", models.JSONField(default=dict)),
                ("actor", models.CharField(max_length=150)),
                ("reason", models.TextField()),
                (
                    "changed_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("release_ref", models.CharField(blank=True, max_length=100)),
                ("validation_evidence", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "db_table": "config_center_runtime_config_revision",
                "ordering": ["-changed_at"],
                "indexes": [
                    models.Index(
                        fields=["profile_id", "changed_at"], name="config_cent_profile_f972ab_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RuntimeConfigSnapshotModel",
            fields=[
                (
                    "snapshot_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("profile_id", models.UUIDField(db_index=True)),
                ("profile_key", models.CharField(db_index=True, max_length=120)),
                ("profile_version", models.PositiveIntegerField()),
                ("snapshot_hash", models.CharField(db_index=True, max_length=128)),
                ("resolved_values", models.JSONField(default=dict)),
                (
                    "generated_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("effective_from", models.DateTimeField(blank=True, null=True)),
                ("validation_report", models.JSONField(blank=True, default=dict)),
                ("consumer_acknowledgement", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "db_table": "config_center_runtime_config_snapshot",
                "ordering": ["-generated_at"],
                "indexes": [
                    models.Index(
                        fields=["profile_key", "profile_version", "generated_at"],
                        name="config_cent_profile_27b69d_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile_id", "snapshot_hash"),
                        name="config_center_runtime_snapshot_hash_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RuntimeConfigValueModel",
            fields=[
                (
                    "value_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("profile_id", models.UUIDField(db_index=True)),
                ("definition_key", models.CharField(db_index=True, max_length=180)),
                ("value_json", models.JSONField(blank=True, null=True)),
                ("secret_ref", models.CharField(blank=True, max_length=300)),
                ("source", models.CharField(default="admin", max_length=40)),
                (
                    "validation_status",
                    models.CharField(db_index=True, default="valid", max_length=20),
                ),
                ("validation_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "config_center_runtime_config_value",
                "indexes": [
                    models.Index(
                        fields=["profile_id", "validation_status"],
                        name="config_cent_profile_53f84d_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile_id", "definition_key"),
                        name="config_center_runtime_value_profile_key_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="StorageBudgetPolicyModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("policy_key", models.CharField(db_index=True, max_length=100, unique=True)),
                ("version", models.PositiveIntegerField()),
                ("configured_capacity_bytes", models.PositiveBigIntegerField()),
                ("raw_budget_ratio", models.FloatField()),
                ("quarantine_budget_ratio", models.FloatField()),
                ("database_budget_ratio", models.FloatField()),
                ("logs_budget_ratio", models.FloatField()),
                ("emergency_reserve_ratio", models.FloatField()),
                ("warning_ratio", models.FloatField()),
                ("critical_ratio", models.FloatField()),
                ("active", models.BooleanField(db_index=True, default=False)),
                ("created_by", models.CharField(default="system", max_length=150)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("change_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "config_center_storage_budget_policy",
                "ordering": ["-active", "-version"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("policy_key", "version"),
                        name="config_center_storage_policy_version_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("configured_capacity_bytes__gt", 0)),
                        name="config_center_storage_capacity_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("warning_ratio__lt", models.F("critical_ratio"))),
                        name="config_center_storage_warning_lt_critical",
                    ),
                ],
            },
        ),
    ]
