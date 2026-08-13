"""Create the empty Portfolio benchmark FX-fixing definition ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed FX-fixing persistence."""

    dependencies = [("portfolio", "0022_policy_benchmark_price_fixing")]
    operations = [
        migrations.CreateModel(
            name="PortfolioPolicyBenchmarkFxFixingModel",
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
                ("base_currency", models.CharField(max_length=3)),
                ("quote_currency", models.CharField(max_length=3)),
                ("currency_pair", models.CharField(max_length=7)),
                ("fixing_convention", models.CharField(max_length=32)),
                ("inverse_rate_allowed", models.BooleanField()),
                ("timezone_name", models.CharField(max_length=192)),
                ("valuation_cutoff_local", models.CharField(max_length=32)),
                ("source_count", models.PositiveIntegerField()),
                ("sources_hash", models.CharField(max_length=64)),
                ("stale_after_seconds", models.PositiveIntegerField()),
                ("triangulation_policy", models.CharField(max_length=32)),
                ("triangulation_currency", models.CharField(blank=True, max_length=3, null=True)),
                ("source_failure_policy", models.CharField(max_length=32)),
                ("missing_fx_policy", models.CharField(max_length=32)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_policy_benchmark_fx_fixing",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["methodology_id", "methodology_version", "recorded_at"],
                        name="port_bench_fx_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("methodology_id", "methodology_version"),
                        name="portfolio_bench_fx_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "portfolio"))
                            & models.Q(("artifact_type", "fx_fixing_methodology"))
                            & models.Q(("schema", "portfolio-policy-benchmark-fx-fixing.v1"))
                            & models.Q(("permission", "methodology_definition_only"))
                            & models.Q(("source_count__gt", 0))
                            & models.Q(("stale_after_seconds__gt", 0))
                            & models.Q(("triangulation_policy", "prohibited"))
                            & models.Q(("triangulation_currency__isnull", True))
                            & models.Q(("source_failure_policy", "block"))
                            & models.Q(("missing_fx_policy", "fail_closed"))
                        ),
                        name="portfolio_bench_fx_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("recorded_at__lt", models.F("valid_until")))
                        ),
                        name="portfolio_bench_fx_clock_ck",
                    ),
                ],
            },
        )
    ]
