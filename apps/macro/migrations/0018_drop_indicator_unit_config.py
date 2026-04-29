from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("macro", "0017_normalize_monthly_period_type_and_rededupe"),
    ]

    operations = [
        migrations.DeleteModel(
            name="IndicatorUnitConfig",
        ),
    ]
