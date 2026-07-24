from django.db import migrations, models


def keep_latest_active_config(apps, schema_editor) -> None:
    """Deactivate duplicate active rows before adding unique constraints."""

    for model_name in ("ScoringWeightConfigModel", "ValuationRepairConfigModel"):
        model = apps.get_model("equity", model_name)
        active_ids = list(
            model.objects.filter(is_active=True)
            .order_by("-updated_at", "-pk")
            .values_list("pk", flat=True)
        )
        if len(active_ids) > 1:
            model.objects.filter(pk__in=active_ids[1:]).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("equity", "0008_stockscreeningruleconfigmodel"),
    ]

    operations = [
        migrations.RunPython(keep_latest_active_config, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="scoringweightconfigmodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("is_active",),
                name="equity_single_active_scoring_weight",
            ),
        ),
        migrations.AddConstraint(
            model_name="valuationrepairconfigmodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("is_active",),
                name="equity_single_active_valuation_repair",
            ),
        ),
    ]
