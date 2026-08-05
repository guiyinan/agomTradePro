from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="FixedIncomeResearchResultModel",
            fields=[
                (
                    "result_id",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("bond_id", models.CharField(db_index=True, max_length=64)),
                ("valuation_at", models.DateTimeField(db_index=True)),
                ("settlement_date", models.DateField()),
                ("method_version", models.CharField(db_index=True, max_length=64)),
                ("input_hash", models.CharField(db_index=True, max_length=64)),
                ("output_hash", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[("available", "available"), ("blocked", "blocked")],
                        max_length=16,
                    ),
                ),
                ("payload", models.JSONField()),
                ("publication_ids", models.JSONField()),
                ("blocked_reasons", models.JSONField(blank=True)),
                (
                    "research_only",
                    models.BooleanField(default=True, editable=False),
                ),
                (
                    "must_not_execute",
                    models.BooleanField(default=True, editable=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "fixed_income_research_result",
                "indexes": [
                    models.Index(
                        fields=["bond_id", "-valuation_at"],
                        name="fixed_income_bond_val_idx",
                    ),
                    models.Index(
                        fields=["method_version", "status"],
                        name="fixed_income_method_stat_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("research_only", True)),
                        name="fixed_income_result_research_only",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("must_not_execute", True)),
                        name="fixed_income_result_no_execute",
                    ),
                ],
            },
        ),
    ]
