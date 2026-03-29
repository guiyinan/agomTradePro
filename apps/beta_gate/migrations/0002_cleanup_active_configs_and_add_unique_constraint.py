from django.db import migrations, models
from django.db.models import Q


def cleanup_duplicate_active_gate_configs(apps, schema_editor):
    GateConfigModel = apps.get_model("beta_gate", "GateConfigModel")

    risk_profiles = (
        GateConfigModel.objects.filter(is_active=True)
        .values_list("risk_profile", flat=True)
        .distinct()
    )
    for risk_profile in risk_profiles:
        active_ids = list(
            GateConfigModel.objects.filter(
                is_active=True,
                risk_profile=risk_profile,
            )
            .order_by("-version", "-updated_at", "-created_at", "-pk")
            .values_list("pk", flat=True)
        )
        if len(active_ids) <= 1:
            continue

        GateConfigModel.objects.filter(pk__in=active_ids[1:]).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("beta_gate", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            cleanup_duplicate_active_gate_configs,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="gateconfigmodel",
            constraint=models.UniqueConstraint(
                fields=("risk_profile",),
                condition=Q(is_active=True),
                name="beta_gate_one_active_per_profile",
            ),
        ),
    ]
