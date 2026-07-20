from django.db import migrations, models

CANONICAL_REGIMES = ("Recovery", "Overheat", "Stagflation", "Deflation")
LEGACY_REGIME_ALIASES = {
    "HG": "Overheat",
    "HD": "Recovery",
    "LG": "Stagflation",
    "LD": "Deflation",
}


def normalize_legacy_regime_codes(apps, schema_editor):
    regime_log = apps.get_model("regime", "RegimeLog")
    for legacy_code, canonical_code in LEGACY_REGIME_ALIASES.items():
        regime_log.objects.filter(dominant_regime=legacy_code).update(
            dominant_regime=canonical_code
        )

    unknown_codes = list(
        regime_log.objects.exclude(dominant_regime__in=CANONICAL_REGIMES)
        .values_list("dominant_regime", flat=True)
        .distinct()
    )
    if unknown_codes:
        raise RuntimeError(
            "Unknown regime codes require manual review before migration: "
            + ", ".join(sorted(unknown_codes))
        )


class Migration(migrations.Migration):
    dependencies = [("regime", "0007_riskparameterconfigmodel_and_more")]

    operations = [
        migrations.RunPython(normalize_legacy_regime_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="regimelog",
            name="dominant_regime",
            field=models.CharField(
                choices=[
                    ("Recovery", "Recovery"),
                    ("Overheat", "Overheat"),
                    ("Stagflation", "Stagflation"),
                    ("Deflation", "Deflation"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="regimelog",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    dominant_regime__in=[
                        "Recovery",
                        "Overheat",
                        "Stagflation",
                        "Deflation",
                    ]
                ),
                name="regime_log_valid_dominant_regime",
            ),
        ),
    ]
