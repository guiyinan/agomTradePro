"""Create the empty Portfolio benchmark cost/tax methodology ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed benchmark cost/tax persistence."""

    dependencies = [
        ("portfolio", "0025_policy_benchmark_corporate_action"),
    ]

    operations = [
        migrations.CreateModel(
            name="PortfolioPolicyBenchmarkCostTaxModel",
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
                ("source_count", models.PositiveIntegerField()),
                ("fee_source_count", models.PositiveIntegerField()),
                ("tax_source_count", models.PositiveIntegerField()),
                ("sources_hash", models.CharField(max_length=64)),
                ("charge_rule_count", models.PositiveIntegerField()),
                ("fee_rule_count", models.PositiveIntegerField()),
                ("tax_rule_count", models.PositiveIntegerField()),
                ("charge_rules_hash", models.CharField(max_length=64)),
                ("business_date_policy", models.CharField(max_length=64)),
                ("currency_basis_policy", models.CharField(max_length=64)),
                ("currency_conversion_policy", models.CharField(max_length=64)),
                ("missing_fx_policy", models.CharField(max_length=32)),
                ("unknown_asset_policy", models.CharField(max_length=32)),
                ("unknown_fee_policy", models.CharField(max_length=32)),
                ("unknown_tax_policy", models.CharField(max_length=32)),
                ("missing_source_policy", models.CharField(max_length=32)),
                ("source_failure_policy", models.CharField(max_length=32)),
                ("estimation_policy", models.CharField(max_length=32)),
                ("silent_zero_policy", models.CharField(max_length=32)),
                ("duplicate_charge_policy", models.CharField(max_length=32)),
                ("cash_dividend_charge_policy", models.CharField(max_length=32)),
                ("cash_dividend_payment_policy", models.CharField(max_length=48)),
                ("corporate_action_charge_policy", models.CharField(max_length=32)),
                ("already_net_amount_policy", models.CharField(max_length=32)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_policy_benchmark_cost_tax",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["methodology_id", "methodology_version", "recorded_at"],
                        name="port_bench_costtax_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("methodology_id", "methodology_version"),
                        name="port_bench_costtax_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("owner", "portfolio"),
                            ("artifact_type", "cost_tax_methodology"),
                            ("schema", "portfolio-policy-benchmark-cost-tax.v1"),
                            ("permission", "methodology_definition_only"),
                            ("business_date_policy", "benchmark_trading_calendar_date"),
                            ("currency_basis_policy", "event_gross_currency"),
                            ("currency_conversion_policy", "exact_benchmark_fx_fixing_only"),
                            ("missing_fx_policy", "fail_closed"),
                            ("unknown_asset_policy", "fail_closed"),
                            ("unknown_fee_policy", "fail_closed"),
                            ("unknown_tax_policy", "fail_closed"),
                            ("missing_source_policy", "fail_closed"),
                            ("source_failure_policy", "block"),
                            ("estimation_policy", "prohibited"),
                            ("silent_zero_policy", "prohibited"),
                            ("duplicate_charge_policy", "block"),
                            ("cash_dividend_charge_policy", "entitlement_once"),
                            ("cash_dividend_payment_policy", "settlement_only_no_second_charge"),
                            ("corporate_action_charge_policy", "exact_event_once"),
                            ("already_net_amount_policy", "block"),
                        ),
                        name="port_bench_costtax_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source_count__gte", 2),
                            ("fee_source_count__gt", 0),
                            ("tax_source_count__gt", 0),
                            ("source_count", models.F("charge_rule_count")),
                            ("fee_source_count", models.F("fee_rule_count")),
                            ("tax_source_count", models.F("tax_rule_count")),
                        ),
                        name="port_bench_costtax_shape_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("persisted_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="port_bench_costtax_clock_ck",
                    ),
                ],
            },
        ),
    ]
