from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0008_alter_operationlogmodel_response_payload"),
    ]

    operations = [
        migrations.AddField(
            model_name="indicatorperformancemodel",
            name="validation_run_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=100,
                null=True,
                verbose_name="验证运行ID",
            ),
        ),
        migrations.AddConstraint(
            model_name="indicatorperformancemodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("validation_run_id__isnull", False)),
                fields=("validation_run_id", "indicator_code"),
                name="audit_indicator_unique_per_validation_run",
            ),
        ),
    ]
