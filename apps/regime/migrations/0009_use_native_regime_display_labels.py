from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("regime", "0008_normalize_regime_codes")]

    operations = [
        migrations.AlterField(
            model_name="regimelog",
            name="dominant_regime",
            field=models.CharField(
                choices=[
                    ("Recovery", "复苏"),
                    ("Overheat", "过热"),
                    ("Stagflation", "滞胀"),
                    ("Deflation", "通缩"),
                ],
                max_length=20,
            ),
        ),
    ]
