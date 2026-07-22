from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0003_transfer_order_intent_state")]

    operations = [
        migrations.CreateModel(
            name="PortfolioPlanningPolicyModel",
            fields=[
                (
                    "policy_id",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("version", models.CharField(max_length=64, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("retired", "Retired"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("buy_lot_size", models.PositiveIntegerField()),
                ("fee_rate", models.DecimalField(decimal_places=8, max_digits=12)),
                ("slippage_rate", models.DecimalField(decimal_places=8, max_digits=12)),
                (
                    "min_rebalance_value",
                    models.DecimalField(decimal_places=4, max_digits=24),
                ),
                (
                    "max_asset_weight",
                    models.DecimalField(decimal_places=8, max_digits=10),
                ),
                (
                    "max_volume_participation",
                    models.DecimalField(decimal_places=8, max_digits=10),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "portfolio_planning_policy",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "active")),
                        fields=("status",),
                        name="portfolio_one_active_planning_policy",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("buy_lot_size__gt", 0)),
                        name="portfolio_policy_positive_lot",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("fee_rate__gte", 0), ("fee_rate__lt", 1)),
                        name="portfolio_policy_fee_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("slippage_rate__gte", 0), ("slippage_rate__lt", 1)),
                        name="portfolio_policy_slippage_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("min_rebalance_value__gte", 0)),
                        name="portfolio_policy_min_rebalance_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("max_asset_weight__gt", 0),
                            ("max_asset_weight__lte", 1),
                        ),
                        name="portfolio_policy_asset_weight_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("max_volume_participation__gte", 0),
                            ("max_volume_participation__lte", 1),
                        ),
                        name="portfolio_policy_participation_range",
                    ),
                ],
            },
        )
    ]
