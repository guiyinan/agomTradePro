# Generated manually for the schema-only R1 evaluation actual evidence boundary.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0067_move_provider_credentials_to_config_center"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluationActualSourceDefinitionModel",
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
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
                ("source_content_hash", models.CharField(max_length=64, unique=True)),
                ("owner", models.CharField(default="data_center", max_length=32)),
                ("dataset", models.CharField(db_index=True, max_length=192)),
                ("subject_code", models.CharField(db_index=True, max_length=192)),
                ("industry_code", models.CharField(db_index=True, max_length=192)),
                ("calendar_id", models.CharField(max_length=192)),
                ("calendar_version", models.CharField(max_length=192)),
                ("calendar_content_hash", models.CharField(max_length=64)),
                ("knowledge_scope", models.CharField(max_length=32)),
                ("require_verified", models.BooleanField()),
                (
                    "minimum_coverage_ratio",
                    models.DecimalField(decimal_places=12, max_digits=20),
                ),
                ("maximum_missing_count", models.PositiveIntegerField()),
                ("maximum_estimated_count", models.PositiveIntegerField()),
                ("maximum_unknown_count", models.PositiveIntegerField()),
                ("registered_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("record_hash", models.CharField(max_length=64, unique=True)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_publish_current", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "data_center_evaluation_actual_source",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["source_id", "source_version", "ledger_recorded_at"],
                        name="dc_evact_source_pit_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"),
                        name="dc_evact_source_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "data_center"))
                            & models.Q(("registered_at__lte", models.F("ledger_recorded_at")))
                            & models.Q(("ledger_recorded_at__lt", models.F("valid_until")))
                            & models.Q(("minimum_coverage_ratio__gte", 0))
                            & models.Q(("minimum_coverage_ratio__lte", 1))
                        ),
                        name="dc_evact_source_sem_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("must_not_execute", True),
                            ("must_not_publish_current", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="dc_evact_source_safe_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvaluationActualManifestReceiptModel",
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
                ("manifest_id", models.CharField(max_length=192)),
                ("manifest_version", models.CharField(max_length=192)),
                ("manifest_content_hash", models.CharField(max_length=64, unique=True)),
                ("owner", models.CharField(default="data_center", max_length=32)),
                ("dataset", models.CharField(db_index=True, max_length=192)),
                ("subject_code", models.CharField(db_index=True, max_length=192)),
                ("industry_code", models.CharField(db_index=True, max_length=192)),
                ("as_of_time", models.DateTimeField(db_index=True)),
                ("produced_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField()),
                ("knowledge_scope", models.CharField(max_length=32)),
                ("is_verified", models.BooleanField()),
                (
                    "coverage_ratio",
                    models.DecimalField(decimal_places=12, max_digits=20),
                ),
                ("missing_count", models.PositiveIntegerField()),
                ("estimated_count", models.PositiveIntegerField()),
                ("unknown_count", models.PositiveIntegerField()),
                ("selected_versions_hash", models.CharField(max_length=64)),
                ("canonical_payload", models.JSONField()),
                ("receipt_hash", models.CharField(max_length=64, unique=True)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_publish_current", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="evaluation_actual_manifest_receipts",
                        to="data_center.evaluationactualsourcedefinitionmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_evaluation_actual_manifest",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["manifest_id", "manifest_version", "produced_at"],
                        name="dc_evact_manifest_pit_idx",
                    ),
                    models.Index(
                        fields=["source_definition", "as_of_time"],
                        name="dc_evact_manifest_src_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("manifest_id", "manifest_version"),
                        name="dc_evact_manifest_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "data_center"))
                            & models.Q(("as_of_time__lte", models.F("produced_at")))
                            & models.Q(("produced_at__lt", models.F("valid_until")))
                            & models.Q(("coverage_ratio__gte", 0))
                            & models.Q(("coverage_ratio__lte", 1))
                        ),
                        name="dc_evact_manifest_sem_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("must_not_execute", True),
                            ("must_not_publish_current", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="dc_evact_manifest_safe_ck",
                    ),
                ],
            },
        ),
    ]
