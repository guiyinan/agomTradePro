from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0013_r8_monitoring_calendar_registry")]

    operations = [
        migrations.CreateModel(
            name="PortfolioR5MonitoringRawFactReceiptModel",
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
                ("fact_id", models.CharField(max_length=192)),
                ("fact_version", models.CharField(max_length=192)),
                ("fact_hash", models.CharField(max_length=64, unique=True)),
                ("definition_hash", models.CharField(max_length=64, unique=True)),
                ("period_id", models.CharField(max_length=64)),
                ("period_end", models.DateTimeField()),
                ("calendar_id", models.CharField(max_length=192)),
                ("calendar_version", models.CharField(max_length=192)),
                ("calendar_hash", models.CharField(max_length=64)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("policy_hash", models.CharField(max_length=64)),
                ("target_hash", models.CharField(max_length=64)),
                ("scope_id", models.CharField(max_length=192)),
                ("decision_id", models.CharField(max_length=192)),
                ("decision_version", models.CharField(max_length=192)),
                ("lifecycle_hash", models.CharField(max_length=64)),
                ("source_receipt_id", models.CharField(max_length=192)),
                ("source_receipt_version", models.CharField(max_length=192)),
                ("source_receipt_hash", models.CharField(max_length=64, unique=True)),
                ("source_available_at", models.DateTimeField()),
                ("source_valid_until", models.DateTimeField()),
                ("fact_recorded_at", models.DateTimeField()),
                ("fact_valid_until", models.DateTimeField()),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("fact_payload", models.JSONField()),
                ("source_payload", models.JSONField()),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("research_only", models.BooleanField(default=True)),
                ("must_not_publish_current", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "portfolio_r5_monitoring_raw_fact_receipt",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=(
                            "policy_id",
                            "policy_version",
                            "calendar_id",
                            "period_id",
                            "ledger_recorded_at",
                        ),
                        name="port_r5_mon_fact_pit_ix",
                    )
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="portfolior5monitoringrawfactreceiptmodel",
            constraint=models.UniqueConstraint(
                fields=("fact_id", "fact_version"),
                name="port_r5_mon_fact_id_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="portfolior5monitoringrawfactreceiptmodel",
            constraint=models.UniqueConstraint(
                fields=(
                    "policy_id",
                    "policy_version",
                    "policy_hash",
                    "target_hash",
                    "calendar_id",
                    "calendar_version",
                    "calendar_hash",
                    "period_id",
                ),
                name="port_r5_mon_fact_period_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="portfolior5monitoringrawfactreceiptmodel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(fact_recorded_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("fact_valid_until"))
                ),
                name="port_r5_mon_fact_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="portfolior5monitoringrawfactreceiptmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="port_r5_mon_fact_safe_ck",
            ),
        ),
    ]
