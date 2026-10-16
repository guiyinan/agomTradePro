from django.db import migrations, models


class Migration(migrations.Migration):
    """Add one-time lifecycle metadata without changing canonical rule payloads."""

    dependencies = [
        ("risk_center", "0010_ashare_execution_rules"),
    ]

    operations = [
        migrations.AddField(
            model_name="ashareexecutionrulemodel",
            name="retirement_effective_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ashareexecutionrulemodel",
            name="retirement_recorded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ashareexecutionrulemodel",
            name="retirement_request_id",
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="ashareexecutionrulemodel",
            name="retirement_actor_type",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="ashareexecutionrulemodel",
            name="retirement_actor_id",
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
        migrations.AddField(
            model_name="ashareexecutionrulemodel",
            name="retirement_request_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name="ashareexecutionrulemodel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        retirement_effective_at__isnull=True,
                        retirement_recorded_at__isnull=True,
                        retirement_request_id__isnull=True,
                        retirement_actor_type__isnull=True,
                        retirement_actor_id__isnull=True,
                        retirement_request_hash__isnull=True,
                    )
                    | models.Q(
                        retirement_effective_at__isnull=False,
                        retirement_recorded_at__isnull=False,
                        retirement_request_id__isnull=False,
                        retirement_actor_type__isnull=False,
                        retirement_actor_id__isnull=False,
                        retirement_request_hash__isnull=False,
                    )
                ),
                name="risk_ash_rule_retire_all_or_none_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="ashareexecutionrulemodel",
            constraint=models.CheckConstraint(
                condition=models.Q(retirement_recorded_at__isnull=True)
                | models.Q(retirement_recorded_at__lte=models.F("retirement_effective_at")),
                name="risk_ash_rule_retire_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="ashareexecutionrulemodel",
            constraint=models.CheckConstraint(
                condition=models.Q(retirement_effective_at__isnull=True)
                | models.Q(
                    effective_from__lte=models.F("retirement_effective_at"),
                    retirement_effective_at__lt=models.F("valid_until"),
                ),
                name="risk_ash_rule_retire_window_ck",
            ),
        ),
    ]
