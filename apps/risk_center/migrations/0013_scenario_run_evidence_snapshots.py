"""Retain canonical inputs and results for reviewable scenario runs."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add optional, paired snapshots to scenario run evidence."""

    dependencies = [("risk_center", "0012_m1_rebalance_risk_policy_immutable")]

    operations = [
        migrations.AddField(
            model_name="scenariorunevidencemodel",
            name="input_snapshot_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scenariorunevidencemodel",
            name="result_snapshot_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="scenariorunevidencemodel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        input_snapshot_json__isnull=True,
                        result_snapshot_json__isnull=True,
                    )
                    | models.Q(
                        input_snapshot_json__isnull=False,
                        result_snapshot_json__isnull=False,
                    )
                ),
                name="risk_scn_run_snapshot_pair_ck",
            ),
        ),
    ]
