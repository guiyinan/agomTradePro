# Add append-only revocation and separate owner-auth event records for financial ceilings.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0091_financial_capacity_governance_record"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialCapacityGovernanceRevocationModel",
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
                ("revoked_by", models.CharField(max_length=150)),
                ("revoked_at", models.DateTimeField(auto_now_add=True)),
                (
                    "governance_record",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revocation",
                        to="data_center.financialcapacitygovernancerecordmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_financial_capacity_governance_revocation",
            },
        ),
        migrations.CreateModel(
            name="FinancialCapacityOwnerApprovalEventModel",
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
                ("event_id", models.CharField(max_length=300, unique=True)),
                ("approved_by", models.CharField(max_length=150)),
                ("approved_at", models.DateTimeField()),
                ("approval_receipt_sha256", models.CharField(max_length=64)),
                ("record_sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "governance_record",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="owner_approval_event",
                        to="data_center.financialcapacitygovernancerecordmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_financial_capacity_owner_approval_event",
            },
        ),
    ]
