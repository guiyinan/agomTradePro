# Generated manually as a schema-only R7 governance migration.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("research", "0004_r4_promotion_ledgers")]

    operations = [
        migrations.CreateModel(
            name="R7SamplePolicyApprovalReceiptModel",
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
                ("authorization_id", models.CharField(max_length=192)),
                ("authorization_version", models.CharField(max_length=192)),
                ("owner_record_id", models.CharField(max_length=192)),
                ("owner_record_version", models.CharField(max_length=192)),
                ("owner_record_hash", models.CharField(max_length=64)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("scope_content_hash", models.CharField(db_index=True, max_length=64)),
                ("policy_definition_hash", models.CharField(max_length=64)),
                ("approved_by", models.CharField(max_length=192)),
                ("issued_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("authorization_content_hash", models.CharField(max_length=64, unique=True)),
                ("record_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_r7_sample_policy_approval",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("authorization_id", "authorization_version"),
                        name="res_r7_auth_identity_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("owner_record_id", "owner_record_version"),
                        name="res_r7_auth_owner_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("policy_id", "policy_version"),
                        name="res_r7_auth_policy_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("issued_at__lte", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="res_r7_auth_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R7SamplePolicyModel",
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
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("scope_content_hash", models.CharField(db_index=True, max_length=64)),
                ("policy_content_hash", models.CharField(max_length=64, unique=True)),
                ("authorization_content_hash", models.CharField(max_length=64)),
                ("activated_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("sample_window_start", models.DateTimeField()),
                ("sample_window_end", models.DateTimeField()),
                (
                    "forecast_horizon_seconds",
                    models.DecimalField(decimal_places=6, max_digits=30),
                ),
                (
                    "censoring_lag_seconds",
                    models.DecimalField(decimal_places=6, max_digits=30),
                ),
                ("censoring_rule_version", models.CharField(max_length=192)),
                ("minimum_forecasts_per_revision", models.PositiveIntegerField()),
                (
                    "minimum_resolved_outcomes_per_revision",
                    models.PositiveIntegerField(),
                ),
                ("minimum_binary_class_observations", models.PositiveIntegerField()),
                ("minimum_multiclass_groups", models.PositiveIntegerField()),
                (
                    "minimum_multiclass_class_observations",
                    models.PositiveIntegerField(),
                ),
                ("minimum_historical_analogies", models.PositiveIntegerField()),
                (
                    "minimum_path_probability_observations",
                    models.PositiveIntegerField(),
                ),
                ("path_horizon_periods", models.PositiveIntegerField()),
                ("require_all_path_initial_states", models.BooleanField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "approval",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_policy",
                        to="research.r7samplepolicyapprovalreceiptmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_r7_sample_policy",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["scope_content_hash", "recorded_at"],
                        name="res_r7_policy_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("policy_id", "policy_version"),
                        name="res_r7_policy_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(recorded_at__lte=models.F("activated_at"))
                            & models.Q(activated_at__lt=models.F("valid_until"))
                            & models.Q(
                                sample_window_start__lt=models.F("sample_window_end")
                            )
                        ),
                        name="res_r7_policy_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("must_not_execute", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="res_r7_policy_safety_ck",
                    ),
                ],
            },
        ),
    ]
