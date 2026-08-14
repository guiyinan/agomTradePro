"""Create the empty Portfolio planning-policy definition ledger."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed planning-policy definition persistence."""

    dependencies = [("portfolio", "0017_transition_plan_inactive_approvals")]

    operations = [
        migrations.CreateModel(
            name="PortfolioPlanningPolicyDefinitionModel",
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
                ("schema", models.CharField(max_length=64)),
                ("permission", models.CharField(max_length=32)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("buy_lot_size", models.PositiveIntegerField()),
                ("fee_rate", models.CharField(max_length=192)),
                ("slippage_rate", models.CharField(max_length=192)),
                ("min_rebalance_value", models.CharField(max_length=192)),
                ("max_asset_weight", models.CharField(max_length=192)),
                ("max_volume_participation", models.CharField(max_length=192)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_planning_policy_definition",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["policy_id", "policy_version", "recorded_at"],
                        name="portfolio_plan_pol_def_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("policy_id", "policy_version"),
                        name="portfolio_plan_pol_def_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("artifact_type", "planning_policy_definition"),
                            ("owner", "portfolio"),
                            ("permission", "definition_only"),
                            ("schema", "portfolio-planning-policy-definition.v1"),
                        ),
                        name="portfolio_plan_pol_def_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("persisted_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="portfolio_plan_pol_def_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("buy_lot_size__gt", 0)),
                        name="portfolio_plan_pol_def_lot_ck",
                    ),
                ],
            },
        )
    ]
