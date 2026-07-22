from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_center", "0038_govern_etf_size_flow_unit")]

    operations = [
        migrations.CreateModel(
            name="PITDatasetManifestModel",
            fields=[
                ("manifest_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("as_of_time", models.DateTimeField(db_index=True)),
                (
                    "knowledge_scope",
                    models.CharField(
                        choices=[("public", "Public"), ("system", "System")], max_length=10
                    ),
                ),
                ("calendar_version", models.CharField(max_length=64)),
                ("query_spec", models.JSONField(default=dict)),
                ("selected_versions", models.JSONField(default=list)),
                ("coverage", models.JSONField(default=dict)),
                ("missing", models.JSONField(default=list)),
                ("estimated", models.JSONField(default=list)),
                ("unknown", models.JSONField(default=list)),
                ("manifest_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "data_center_pit_dataset_manifest",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["knowledge_scope", "as_of_time"],
                        name="data_center_knowled_76d1c9_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PITFactVersionModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dataset", models.CharField(db_index=True, max_length=64)),
                ("business_key", models.CharField(db_index=True, max_length=255)),
                ("effective_at", models.DateTimeField(db_index=True)),
                ("effective_to", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("available_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("ingested_at", models.DateTimeField(db_index=True)),
                ("superseded_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("revision_number", models.PositiveIntegerField(default=0)),
                ("source_record_id", models.CharField(max_length=255)),
                ("content_hash", models.CharField(max_length=64)),
                (
                    "pit_quality",
                    models.CharField(
                        choices=[
                            ("verified", "Verified"),
                            ("estimated", "Estimated"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("payload", models.JSONField(default=dict)),
            ],
            options={
                "db_table": "data_center_pit_fact_version",
                "indexes": [
                    models.Index(
                        fields=["dataset", "business_key", "effective_at"],
                        name="data_center_dataset_2d0100_idx",
                    ),
                    models.Index(
                        fields=["dataset", "available_at"], name="data_center_dataset_5bf9ab_idx"
                    ),
                    models.Index(
                        fields=["dataset", "ingested_at"], name="data_center_dataset_10cc27_idx"
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset", "business_key", "revision_number", "content_hash"),
                        name="dc_pit_fact_version_identity_uniq",
                    )
                ],
            },
        ),
    ]
