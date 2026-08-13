"""Create the empty Portfolio benchmark trading-calendar definition ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed benchmark calendar persistence."""

    dependencies = [("portfolio", "0020_policy_benchmark_definition")]

    operations = [
        migrations.CreateModel(
            name="PortfolioPolicyBenchmarkTradingCalendarModel",
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
                ("market_calendar_code", models.CharField(max_length=192)),
                ("timezone_name", models.CharField(max_length=192)),
                ("coverage_start", models.DateField()),
                ("coverage_end", models.DateField()),
                ("day_count", models.PositiveIntegerField()),
                ("valuation_day_count", models.PositiveIntegerField()),
                ("membership_hash", models.CharField(max_length=64)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_policy_benchmark_trading_calendar",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["methodology_id", "methodology_version", "recorded_at"],
                        name="port_bench_cal_def_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("methodology_id", "methodology_version"),
                        name="portfolio_bench_cal_def_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "portfolio"))
                            & models.Q(("artifact_type", "trading_calendar_definition"))
                            & models.Q(("schema", "portfolio-policy-benchmark-trading-calendar.v1"))
                            & models.Q(("permission", "methodology_definition_only"))
                            & models.Q(("day_count__gt", 0))
                            & models.Q(("coverage_start__lte", models.F("coverage_end")))
                        ),
                        name="portfolio_bench_cal_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("recorded_at__lt", models.F("valid_until")))
                        ),
                        name="portfolio_bench_cal_clock_ck",
                    ),
                ],
            },
        )
    ]
