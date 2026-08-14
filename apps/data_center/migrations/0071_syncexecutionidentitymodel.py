"""Create the server-issued sync execution identity boundary."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0070_rawaudit_identity_and_content_hash"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncExecutionIdentityModel",
            fields=[
                (
                    "identity_hash",
                    models.CharField(
                        editable=False,
                        max_length=64,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("run_id", models.UUIDField(db_index=True)),
                ("ingested_run_id", models.UUIDField(db_index=True)),
                ("batch_id", models.UUIDField(db_index=True)),
                ("dataset_key", models.CharField(db_index=True, max_length=192)),
                ("provider_name", models.CharField(db_index=True, max_length=192)),
            ],
            options={
                "db_table": "data_center_sync_execution_identity",
                "default_manager_name": "objects",
                "base_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "provider_name"],
                        name="data_center_dataset_307b2f_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("run_id", "ingested_run_id", "batch_id"),
                        name="dc_sync_identity_ids_unique",
                    ),
                ],
            },
        ),
    ]
