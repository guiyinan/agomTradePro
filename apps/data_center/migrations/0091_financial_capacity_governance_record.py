# Created for independently recorded financial capacity governance ceilings.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0090_financial_publication_capacity_workflow"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialCapacityGovernanceRecordModel",
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
                ("approval_id", models.CharField(max_length=300, unique=True)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("qualification", "Isolated qualification"),
                            ("capacity_rehearsal", "Isolated full-scope capacity rehearsal"),
                            ("production", "Formal production"),
                        ],
                        max_length=32,
                    ),
                ),
                ("record", models.JSONField()),
                ("created_by", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "data_center_financial_capacity_governance_record",
            },
        ),
    ]
