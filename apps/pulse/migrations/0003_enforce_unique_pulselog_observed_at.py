from django.db import migrations, models


def _deduplicate_pulse_logs(apps, schema_editor):
    PulseLog = apps.get_model("pulse", "PulseLog")
    duplicates = (
        PulseLog.objects.values("observed_at")
        .annotate(row_count=models.Count("id"))
        .filter(row_count__gt=1)
    )
    for item in duplicates.iterator():
        observed_at = item["observed_at"]
        rows = PulseLog.objects.filter(observed_at=observed_at).order_by("-created_at", "-id")
        keep = rows.first()
        if keep is None:
            continue
        rows.exclude(id=keep.id).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pulse", "0002_pulseweightconfig_pulseindicatorweight"),
    ]

    operations = [
        migrations.RunPython(_deduplicate_pulse_logs, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="pulselog",
            options={
                "db_table": "pulse_log",
                "get_latest_by": "observed_at",
                "ordering": ["-observed_at", "-created_at"],
            },
        ),
        migrations.AlterField(
            model_name="pulselog",
            name="observed_at",
            field=models.DateField(db_index=True, unique=True, verbose_name="观测日期"),
        ),
    ]
