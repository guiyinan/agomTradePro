from typing import Any

from django.db import migrations, models


def keep_latest_active_model(apps: Any, schema_editor: Any) -> None:
    registry_model = apps.get_model("alpha", "QlibModelRegistryModel")
    active_models = registry_model.objects.filter(is_active=True).order_by(
        "-created_at",
        "artifact_hash",
    )
    keeper = active_models.first()
    if keeper is not None:
        active_models.exclude(pk=keeper.pk).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("alpha", "0005_alphamonitoringarchivemodel"),
    ]

    operations = [
        migrations.RunPython(
            keep_latest_active_model,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="qlibmodelregistrymodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_active=True),
                fields=("is_active",),
                name="alpha_single_active_qlib_model",
            ),
        ),
    ]
