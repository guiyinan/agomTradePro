"""Add one lockable current-publication pointer row per dataset scope."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_center", "0086_canonical_publication_scope_blocks")]

    operations = [
        migrations.CreateModel(
            name="CanonicalPublicationPointerModel",
            fields=[
                (
                    "pointer_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("dataset_key", models.CharField(max_length=160)),
                ("publication_key", models.CharField(max_length=300)),
                (
                    "publication_id",
                    models.UUIDField(blank=True, db_index=True, null=True),
                ),
                ("publication_hash", models.CharField(blank=True, max_length=128)),
                ("activation_id", models.CharField(blank=True, max_length=300)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_canonical_publication_pointer",
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "publication_key", "publication_id"],
                        name="dc_pub_pointer_scope_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset_key", "publication_key"),
                        name="dc_publication_pointer_scope_unique",
                    ),
                ],
            },
        ),
    ]
