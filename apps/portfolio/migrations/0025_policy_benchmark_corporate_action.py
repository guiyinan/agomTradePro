"""Create the empty Portfolio benchmark corporate-action methodology ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed corporate-action methodology persistence."""

    dependencies = [("portfolio", "0024_align_transition_approval_persistence_clock")]
    operations = [
        migrations.CreateModel(
            name="PortfolioPolicyBenchmarkCorporateActionModel",
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
                ("methodology_id", models.CharField(max_length=192)),
                ("methodology_version", models.CharField(max_length=192)),
                ("security_identifier_namespace", models.CharField(max_length=192)),
                ("timezone_name", models.CharField(max_length=192)),
                ("business_date_cutoff_local", models.CharField(max_length=32)),
                ("business_date_policy", models.CharField(max_length=64)),
                ("non_business_date_policy", models.CharField(max_length=32)),
                ("source_count", models.PositiveIntegerField()),
                ("sources_hash", models.CharField(max_length=64)),
                ("event_rule_count", models.PositiveIntegerField()),
                ("event_rules_hash", models.CharField(max_length=64)),
                ("source_failure_policy", models.CharField(max_length=32)),
                ("missing_action_policy", models.CharField(max_length=32)),
                ("unknown_event_type_policy", models.CharField(max_length=32)),
                ("price_input_adjustment_basis", models.CharField(max_length=32)),
                ("adjustment_application_policy", models.CharField(max_length=32)),
                ("duplicate_event_policy", models.CharField(max_length=32)),
                ("pre_adjusted_input_policy", models.CharField(max_length=32)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_policy_benchmark_corporate_action",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["methodology_id", "methodology_version", "recorded_at"],
                        name="port_bench_corpact_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("methodology_id", "methodology_version"),
                        name="portfolio_bench_corpact_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "portfolio"))
                            & models.Q(("artifact_type", "corporate_action_methodology"))
                            & models.Q(
                                (
                                    "schema",
                                    "portfolio-policy-benchmark-corporate-action.v1",
                                )
                            )
                            & models.Q(("permission", "methodology_definition_only"))
                            & models.Q(("business_date_policy", "issuer_market_local_date"))
                            & models.Q(("non_business_date_policy", "block"))
                            & models.Q(("source_count__gt", 0))
                            & models.Q(("event_rule_count", 5))
                            & models.Q(("source_failure_policy", "block"))
                            & models.Q(("missing_action_policy", "fail_closed"))
                            & models.Q(("unknown_event_type_policy", "fail_closed"))
                            & models.Q(("price_input_adjustment_basis", "unadjusted"))
                            & models.Q(("adjustment_application_policy", "exact_event_once"))
                            & models.Q(("duplicate_event_policy", "block"))
                            & models.Q(("pre_adjusted_input_policy", "block"))
                        ),
                        name="portfolio_bench_corpact_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("recorded_at__lt", models.F("valid_until")))
                        ),
                        name="portfolio_bench_corpact_clock_ck",
                    ),
                ],
            },
        )
    ]
