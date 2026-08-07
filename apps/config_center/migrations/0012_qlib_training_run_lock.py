"""Add the Config Center-owned Qlib training admission lock."""

from django.db import migrations, models


def seed_global_training_lock(apps, schema_editor) -> None:
    """Seed the singleton row so upgraded deployments lock an existing record."""

    lock_model = apps.get_model("config_center", "QlibTrainingRunLockModel")
    lock_model.objects.get_or_create(lock_key="global")


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0011_version_storage_budget_policies"),
    ]

    operations = [
        migrations.CreateModel(
            name="QlibTrainingRunLockModel",
            fields=[
                (
                    "lock_key",
                    models.CharField(
                        editable=False, max_length=64, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Qlib 训练准入锁",
                "verbose_name_plural": "Qlib 训练准入锁",
                "db_table": "config_center_qlib_training_run_lock",
            },
        ),
        migrations.RunPython(seed_global_training_lock, migrations.RunPython.noop),
    ]
