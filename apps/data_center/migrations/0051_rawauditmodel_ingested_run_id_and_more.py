import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0050_canonicalpublicationmodel_coveragesnapshotmodel_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rawauditmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="parser_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="payload_size_bytes",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="redacted",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="request_params_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="response_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="retention_until",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="schema_fingerprint",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.CreateModel(
            name="RawPayloadModel",
            fields=[
                (
                    "payload_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("provider_name", models.CharField(db_index=True, max_length=100)),
                ("payload_hash", models.CharField(db_index=True, max_length=128, unique=True)),
                ("schema_fingerprint", models.CharField(db_index=True, max_length=128)),
                ("payload", models.JSONField(default=dict)),
                ("request_params", models.JSONField(blank=True, default=dict)),
                ("run_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("batch_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("content_type", models.CharField(default="application/json", max_length=80)),
                ("parser_version", models.CharField(blank=True, max_length=40)),
                ("redacted", models.BooleanField(default=True)),
                ("payload_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("fetched_at", models.DateTimeField(db_index=True)),
                ("retention_until", models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={
                "db_table": "data_center_raw_payload",
                "ordering": ["-fetched_at"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "fetched_at"], name="data_center_dataset_78ffe6_idx"
                    ),
                    models.Index(
                        fields=["provider_name", "schema_fingerprint"],
                        name="data_center_provide_c1eea8_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SchemaFingerprintModel",
            fields=[
                (
                    "fingerprint",
                    models.CharField(max_length=128, primary_key=True, serialize=False),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("provider_name", models.CharField(db_index=True, max_length=100)),
                ("fields", models.JSONField(default=list)),
                ("parser_version", models.CharField(blank=True, max_length=40)),
                ("first_seen_at", models.DateTimeField(db_index=True)),
                ("last_seen_at", models.DateTimeField(db_index=True)),
                ("sample_count", models.PositiveBigIntegerField(default=1)),
            ],
            options={
                "db_table": "data_center_schema_fingerprint",
                "ordering": ["-last_seen_at"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "provider_name", "last_seen_at"],
                        name="data_center_dataset_5f6a1a_idx",
                    )
                ],
            },
        ),
    ]
