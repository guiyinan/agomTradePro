from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0015_r8_monitoring_feedback_registry")]

    operations = [
        migrations.AddField(
            model_name="portfoliotransitionplanmodel",
            name="plan_contract_family",
            field=models.CharField(
                blank=True,
                choices=[
                    ("decision_rhythm_legacy_v1", "Decision Rhythm legacy v1"),
                    ("portfolio_canonical_v1", "Portfolio canonical v1"),
                ],
                db_index=True,
                help_text=(
                    "Transition-plan payload contract family; "
                    "NULL denotes unclassified legacy data"
                ),
                max_length=40,
                null=True,
            ),
        )
    ]
