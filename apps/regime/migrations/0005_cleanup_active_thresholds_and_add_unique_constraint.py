from django.db import migrations, models
from django.db.models import Q


def cleanup_duplicate_active_threshold_configs(apps, schema_editor):
    RegimeThresholdConfig = apps.get_model("regime", "RegimeThresholdConfig")

    active_ids = list(
        RegimeThresholdConfig.objects.filter(is_active=True)
        .order_by("-updated_at", "-created_at", "-pk")
        .values_list("pk", flat=True)
    )
    if len(active_ids) <= 1:
        return

    RegimeThresholdConfig.objects.filter(pk__in=active_ids[1:]).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("regime", "0004_actionrecommendationlog_and_more"),
    ]

    operations = [
        migrations.RunPython(
            cleanup_duplicate_active_threshold_configs,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="regimethresholdconfig",
            constraint=models.UniqueConstraint(
                fields=("is_active",),
                condition=Q(is_active=True),
                name="regime_single_active_threshold",
            ),
        ),
    ]
