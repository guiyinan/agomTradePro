"""Create the empty Portfolio policy-benchmark definition ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed policy-benchmark definition persistence."""

    dependencies = [("portfolio", "0019_planning_policy_activation")]

    operations = [
        migrations.CreateModel(
            name="PortfolioPolicyBenchmarkDefinitionModel",
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
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=32)),
                ("definition_id", models.CharField(max_length=192)),
                ("definition_version", models.CharField(max_length=192)),
                ("base_currency", models.CharField(max_length=3)),
                ("constituent_count", models.PositiveIntegerField()),
                ("constituents_hash", models.CharField(max_length=64)),
                ("methodology_refs_hash", models.CharField(max_length=64)),
                ("valuation_timezone", models.CharField(max_length=192)),
                ("valuation_cutoff", models.CharField(max_length=192)),
                ("evaluation_window_days", models.PositiveIntegerField()),
                ("max_price_age_seconds", models.PositiveIntegerField()),
                ("max_fx_age_seconds", models.PositiveIntegerField()),
                ("missing_price_policy", models.CharField(max_length=32)),
                ("missing_fx_policy", models.CharField(max_length=32)),
                ("blocker_codes_hash", models.CharField(max_length=64)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_policy_benchmark_definition",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["definition_id", "definition_version", "recorded_at"],
                        name="port_pol_bench_def_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("definition_id", "definition_version"),
                        name="portfolio_pol_bench_def_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "portfolio"))
                            & models.Q(("artifact_type", "policy_benchmark_definition"))
                            & models.Q(("schema", "portfolio-policy-benchmark-definition.v1"))
                            & models.Q(("permission", "definition_only"))
                            & models.Q(("missing_price_policy", "fail_closed"))
                            & models.Q(("missing_fx_policy", "fail_closed"))
                            & models.Q(("constituent_count__gt", 0))
                            & models.Q(("evaluation_window_days__gt", 0))
                            & models.Q(("max_price_age_seconds__gt", 0))
                            & models.Q(("max_fx_age_seconds__gt", 0))
                        ),
                        name="portfolio_pol_bench_def_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("recorded_at__lt", models.F("valid_until")))
                        ),
                        name="portfolio_pol_bench_def_clock_ck",
                    ),
                ],
            },
        )
    ]
