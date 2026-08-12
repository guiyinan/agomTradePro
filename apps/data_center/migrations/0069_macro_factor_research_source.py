# Generated manually for the schema-only R3 canonical source boundary.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0068_evaluation_actual_ledgers"),
    ]

    operations = [
        migrations.CreateModel(
            name="MacroFactorResearchSourceDefinitionModel",
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
                (
                    "manifest_calendar_version",
                    models.CharField(max_length=64, unique=True),
                ),
                ("owner", models.CharField(default="data_center", max_length=32)),
                ("target_code", models.CharField(db_index=True, max_length=192)),
                ("candidate_asset_codes", models.JSONField()),
                ("calendar_id", models.CharField(max_length=192)),
                ("calendar_version", models.CharField(max_length=192)),
                ("calendar_content_hash", models.CharField(max_length=64)),
                ("source_contract_id", models.CharField(max_length=192)),
                ("source_contract_version", models.CharField(max_length=192)),
                ("source_contract_hash", models.CharField(max_length=64)),
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
                "db_table": "data_center_macro_factor_source",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["source_id", "source_version", "ledger_recorded_at"],
                        name="dc_mfsrc_pit_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"),
                        name="dc_mfsrc_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "data_center"))
                            & models.Q(("knowledge_scope", "public"))
                            & models.Q(("registered_at__lte", models.F("ledger_recorded_at")))
                            & models.Q(("ledger_recorded_at__lt", models.F("valid_until")))
                            & models.Q(("minimum_coverage_ratio__gte", 0))
                            & models.Q(("minimum_coverage_ratio__lte", 1))
                        ),
                        name="dc_mfsrc_sem_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("must_not_execute", True),
                            ("must_not_publish_current", True),
                            ("must_not_use_for_decision", True),
                            ("research_only", True),
                        ),
                        name="dc_mfsrc_safe_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MacroFactorResearchCalendarPeriodModel",
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
                ("row_id", models.CharField(max_length=192)),
                ("period_id", models.CharField(max_length=192)),
                ("kind", models.CharField(max_length=32)),
                ("observation_date", models.DateField()),
                ("target_period_start", models.DateField()),
                ("target_period_end", models.DateField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="macro_factor_calendar_periods",
                        to="data_center.macrofactorresearchsourcedefinitionmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_macro_factor_calendar_period",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_definition", "row_id"),
                        name="dc_mfsrc_period_row_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("source_definition", "period_id"),
                        name="dc_mfsrc_period_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("kind__in", ["historical", "inference"]))
                            & models.Q(
                                (
                                    "target_period_start__lte",
                                    models.F("target_period_end"),
                                )
                            )
                            & models.Q(("observation_date__lte", models.F("target_period_end")))
                        ),
                        name="dc_mfsrc_period_sem_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MacroFactorResearchMemberRuleModel",
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
                ("row_id", models.CharField(max_length=192)),
                ("role", models.CharField(max_length=32)),
                ("member_code", models.CharField(max_length=192)),
                ("dataset_key", models.CharField(db_index=True, max_length=64)),
                ("business_key", models.CharField(db_index=True, max_length=255)),
                ("value_field", models.CharField(max_length=192)),
                ("unit_field", models.CharField(max_length=192)),
                ("expected_unit", models.CharField(max_length=192)),
                ("value_encoding", models.CharField(max_length=32)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "period",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="macro_factor_member_rules",
                        to="data_center.macrofactorresearchcalendarperiodmodel",
                    ),
                ),
                (
                    "source_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="macro_factor_member_rules",
                        to="data_center.macrofactorresearchsourcedefinitionmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_macro_factor_member_rule",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["source_definition", "row_id"],
                        name="dc_mfsrc_member_row_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "source_definition",
                            "row_id",
                            "role",
                            "member_code",
                        ),
                        name="dc_mfsrc_member_sem_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("source_definition", "dataset_key", "business_key"),
                        name="dc_mfsrc_member_fact_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("role__in", ["target", "proxy"]))
                            & models.Q(
                                (
                                    "value_encoding__in",
                                    ["decimal_text.v1", "json_number.v1"],
                                )
                            )
                        ),
                        name="dc_mfsrc_member_sem_ck",
                    ),
                ],
            },
        ),
    ]
