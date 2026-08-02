import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0052_capitalflowfactmodel_contract_version_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArchiveManifestModel",
            fields=[
                (
                    "archive_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("object_count", models.PositiveBigIntegerField(default=0)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("location", models.CharField(max_length=500)),
                ("checksum", models.CharField(db_index=True, max_length=128)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("planned", "planned"),
                            ("exported", "exported"),
                            ("verified", "verified"),
                            ("deleted", "deleted"),
                            ("failed", "failed"),
                        ],
                        db_index=True,
                        default="planned",
                        max_length=20,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("retention_until", models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={
                "db_table": "data_center_archive_manifest",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "state", "created_at"],
                        name="data_center_dataset_73d1be_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RetentionPolicyModel",
            fields=[
                (
                    "policy_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("version", models.PositiveIntegerField()),
                ("retention_days", models.PositiveIntegerField()),
                ("archive_after_days", models.PositiveIntegerField(blank=True, null=True)),
                ("priority", models.CharField(default="normal", max_length=20)),
                ("active", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "data_center_retention_policy",
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "active"], name="data_center_dataset_8ce586_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset_key", "version"),
                        name="dc_retention_dataset_version_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="StorageHoldModel",
            fields=[
                (
                    "hold_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("resource_type", models.CharField(db_index=True, max_length=60)),
                ("resource_key", models.CharField(db_index=True, max_length=240)),
                ("reason", models.TextField()),
                ("created_by", models.CharField(max_length=150)),
                (
                    "created_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "data_center_storage_hold",
                "indexes": [
                    models.Index(
                        fields=["resource_type", "resource_key", "released_at"],
                        name="data_center_resourc_2051fb_idx",
                    )
                ],
            },
        ),
    ]
