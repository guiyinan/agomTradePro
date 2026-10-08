# Created for durable, revision-checked financial capacity checkpoints.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0089_candidate_raw_audit_manifest"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialPublicationCapacityWorkflowModel",
            fields=[
                (
                    "workflow_id",
                    models.CharField(max_length=300, primary_key=True, serialize=False),
                ),
                ("approval_id", models.CharField(max_length=300, null=True, unique=True)),
                ("stage", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("checkpoint", models.JSONField()),
                ("started_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_financial_publication_capacity_workflow",
            },
        ),
        migrations.AddField(
            model_name="financialpublicationcapacityworkflowmodel",
            name="receipt_sha256",
            field=models.CharField(max_length=64, null=True, unique=True),
        ),
        migrations.AddIndex(
            model_name="financialpublicationcapacityworkflowmodel",
            index=models.Index(fields=["stage", "status"], name="data_center_stage_bef870_idx"),
        ),
    ]
