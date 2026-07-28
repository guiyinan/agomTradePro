from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0009_indicatorperformancemodel_validation_run_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attributionreport",
            name="regime_actual",
            field=models.CharField(
                blank=True,
                max_length=64,
                null=True,
                verbose_name="实际 Regime",
            ),
        ),
    ]
