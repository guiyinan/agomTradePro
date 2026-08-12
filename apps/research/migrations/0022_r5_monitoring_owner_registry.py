from django.db import migrations, models

SAFETY_FIELDS = (
    ("research_only", models.BooleanField(default=True)),
    ("must_not_publish_current", models.BooleanField(default=True)),
    ("must_not_use_for_decision", models.BooleanField(default=True)),
    ("must_not_execute", models.BooleanField(default=True)),
)


class Migration(migrations.Migration):
    dependencies = [("research", "0021_r2_trial_policy_registry")]

    operations = [
        migrations.CreateModel(
            name="R5MonitoringPolicyRegistryModel",
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
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("policy_hash", models.CharField(max_length=64, unique=True)),
                ("definition_hash", models.CharField(max_length=64, unique=True)),
                ("source_receipt_id", models.CharField(max_length=192)),
                ("source_receipt_version", models.CharField(max_length=192)),
                ("source_receipt_hash", models.CharField(max_length=64, unique=True)),
                ("source_available_at", models.DateTimeField()),
                ("source_valid_until", models.DateTimeField()),
                ("policy_recorded_at", models.DateTimeField()),
                ("policy_valid_until", models.DateTimeField()),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("policy_payload", models.JSONField()),
                ("source_payload", models.JSONField()),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                *SAFETY_FIELDS,
            ],
            options={
                "db_table": "research_r5_monitoring_policy_registry",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="R5MonitoringCalendarRegistryModel",
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
                ("calendar_id", models.CharField(max_length=192)),
                ("calendar_version", models.CharField(max_length=192)),
                ("calendar_hash", models.CharField(max_length=64, unique=True)),
                ("definition_hash", models.CharField(max_length=64, unique=True)),
                ("source_receipt_id", models.CharField(max_length=192)),
                ("source_receipt_version", models.CharField(max_length=192)),
                ("source_receipt_hash", models.CharField(max_length=64, unique=True)),
                ("source_available_at", models.DateTimeField()),
                ("source_valid_until", models.DateTimeField()),
                ("calendar_recorded_at", models.DateTimeField()),
                ("calendar_valid_until", models.DateTimeField()),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("calendar_payload", models.JSONField()),
                ("source_payload", models.JSONField()),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                *SAFETY_FIELDS,
            ],
            options={
                "db_table": "research_r5_monitoring_calendar_registry",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AddConstraint(
            model_name="r5monitoringpolicyregistrymodel",
            constraint=models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="res_r5_mon_pol_reg_id_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="r5monitoringpolicyregistrymodel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(policy_recorded_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("policy_valid_until"))
                ),
                name="res_r5_mon_pol_reg_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r5monitoringpolicyregistrymodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_pol_reg_safe_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r5monitoringcalendarregistrymodel",
            constraint=models.UniqueConstraint(
                fields=("calendar_id", "calendar_version"),
                name="res_r5_mon_cal_reg_id_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="r5monitoringcalendarregistrymodel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(calendar_recorded_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("calendar_valid_until"))
                ),
                name="res_r5_mon_cal_reg_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="r5monitoringcalendarregistrymodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_cal_reg_safe_ck",
            ),
        ),
    ]
