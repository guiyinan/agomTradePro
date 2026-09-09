"""Persist regional egress rules and redacted transport audit evidence."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    """Create Data Center egress routing tables."""

    dependencies = [("data_center", "0074_qmtbridgebindingmodel_qmtbridgebatchmodel_and_more")]

    operations = [
        migrations.CreateModel(
            name="EgressRoutingRuleModel",
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
                ("provider_id", models.PositiveBigIntegerField(db_index=True)),
                ("dataset_key", models.CharField(max_length=120)),
                ("domain_pattern", models.CharField(max_length=253)),
                ("deployment_region", models.CharField(max_length=40)),
                (
                    "strategy",
                    models.CharField(
                        choices=[
                            ("direct", "Direct"),
                            ("fixed", "Fixed egress"),
                            ("direct_fallback", "Direct then fixed egress"),
                        ],
                        max_length=24,
                    ),
                ),
                ("fixed_egress_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("priority", models.PositiveIntegerField(db_index=True, default=100)),
                ("enabled", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_egress_routing_rule",
                "ordering": ("priority", "id"),
            },
        ),
        migrations.CreateModel(
            name="EgressRequestAuditModel",
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
                (
                    "request_id",
                    models.UUIDField(db_index=True, default=uuid.uuid4),
                ),
                (
                    "provider_id",
                    models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
                ),
                ("dataset_key", models.CharField(blank=True, default="", max_length=120)),
                ("target_host", models.CharField(blank=True, default="", max_length=253)),
                (
                    "deployment_region",
                    models.CharField(blank=True, default="", max_length=40),
                ),
                ("rule_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("egress_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("attempt", models.PositiveSmallIntegerField(default=1)),
                ("outcome", models.CharField(max_length=24)),
                ("error_code", models.CharField(blank=True, default="", max_length=80)),
                ("latency_ms", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "data_center_egress_request_audit",
                "indexes": [
                    models.Index(
                        fields=("target_host", "created_at"), name="dc_egress_audit_host_idx"
                    ),
                    models.Index(
                        fields=("egress_id", "created_at"), name="dc_egress_audit_exit_idx"
                    ),
                ],
            },
        ),
    ]
