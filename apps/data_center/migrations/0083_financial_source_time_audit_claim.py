"""Add one durable first-writer claim per financial source-time capture."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0082_financial_fact_decision_evidence"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialSourceTimeAuditClaimModel",
            fields=[
                (
                    "capture_id",
                    models.UUIDField(editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="financial_source_time_claim",
                        to="data_center.rawauditmodel",
                    ),
                ),
            ],
            options={
                "verbose_name": "Financial Source-Time Audit Claim",
                "verbose_name_plural": "Financial Source-Time Audit Claims",
                "db_table": "data_center_financial_source_time_audit_claim",
            },
        ),
    ]
