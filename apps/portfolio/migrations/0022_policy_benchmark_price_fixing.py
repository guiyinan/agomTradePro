"""Create the empty Portfolio benchmark price-fixing definition ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed benchmark price-fixing persistence."""

    dependencies = [("portfolio", "0021_policy_benchmark_trading_calendar")]
    operations = [
        migrations.CreateModel(
            name="PortfolioPolicyBenchmarkPriceFixingModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=32)),
                ("methodology_id", models.CharField(max_length=192)),
                ("methodology_version", models.CharField(max_length=192)),
                ("price_identifier_namespace", models.CharField(max_length=192)),
                ("price_field", models.CharField(max_length=16)),
                ("adjustment_basis", models.CharField(max_length=32)),
                ("venue", models.CharField(max_length=192)),
                ("timezone_name", models.CharField(max_length=192)),
                ("valuation_cutoff_local", models.CharField(max_length=32)),
                ("source_count", models.PositiveIntegerField()),
                ("sources_hash", models.CharField(max_length=64)),
                ("stale_after_seconds", models.PositiveIntegerField()),
                ("missing_price_policy", models.CharField(max_length=32)),
                ("source_failure_policy", models.CharField(max_length=32)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_policy_benchmark_price_fixing",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["methodology_id", "methodology_version", "recorded_at"],
                        name="port_bench_price_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("methodology_id", "methodology_version"),
                        name="portfolio_bench_price_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "portfolio"))
                            & models.Q(("artifact_type", "price_fixing_methodology"))
                            & models.Q(("schema", "portfolio-policy-benchmark-price-fixing.v1"))
                            & models.Q(("permission", "methodology_definition_only"))
                            & models.Q(("adjustment_basis", "unadjusted"))
                            & models.Q(("source_count__gt", 0))
                            & models.Q(("stale_after_seconds__gt", 0))
                            & models.Q(("missing_price_policy", "fail_closed"))
                            & models.Q(("source_failure_policy", "block"))
                        ),
                        name="portfolio_bench_price_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("recorded_at__lt", models.F("valid_until")))
                        ),
                        name="portfolio_bench_price_clock_ck",
                    ),
                ],
            },
        )
    ]
