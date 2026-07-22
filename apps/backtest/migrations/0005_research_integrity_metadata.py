from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("backtest", "0004_backtestresultmodel_signal_configs_and_more")]

    operations = [
        migrations.AddField(
            model_name="backtestresultmodel",
            name="decision_snapshot_id",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="code_commit",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="config_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="data_manifest_id",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="engine_version",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="pit_coverage",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="research_trial_id",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="backtestresultmodel",
            name="trust_status",
            field=models.CharField(
                choices=[
                    ("legacy_unverified", "Legacy unverified"),
                    ("exploratory", "Exploratory"),
                    ("pit_verified", "PIT verified"),
                ],
                db_index=True,
                default="legacy_unverified",
                max_length=24,
            ),
        ),
        migrations.AddIndex(
            model_name="backtestresultmodel",
            index=models.Index(
                fields=["trust_status", "-created_at"], name="backtest_re_trust_s_f686aa_idx"
            ),
        ),
    ]
