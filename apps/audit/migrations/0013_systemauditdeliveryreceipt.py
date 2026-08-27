from django.core.serializers.json import DjangoJSONEncoder
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("audit", "0012_systemauditevent_scope")]

    operations = [
        migrations.CreateModel(
            name="SystemAuditDeliveryReceiptModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("event_id", models.CharField(max_length=128)),
                ("event_version", models.CharField(max_length=64)),
                ("identity_hash", models.CharField(max_length=64)),
                ("content_hash", models.CharField(max_length=64)),
                ("stream_id", models.CharField(max_length=256)),
                ("sequence_no", models.PositiveBigIntegerField()),
                ("predecessor_hash", models.CharField(blank=True, max_length=64, null=True)),
                ("idempotency_key", models.CharField(max_length=256)),
                ("canonical_payload", models.JSONField(encoder=DjangoJSONEncoder)),
                ("sink_id", models.CharField(max_length=128)),
                ("delivery_id", models.CharField(max_length=256)),
                ("published_at", models.DateTimeField()),
            ],
            options={
                "db_table": "audit_system_delivery_receipt",
                "default_manager_name": "objects",
                "base_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event_id", "event_version"), name="audit_receipt_event_unique"
                    ),
                    models.UniqueConstraint(
                        fields=("idempotency_key",), name="audit_receipt_idempotency_unique"
                    ),
                    models.UniqueConstraint(
                        fields=("delivery_id",), name="audit_receipt_delivery_unique"
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["sink_id", "published_at"], name="audit_receipt_sink_time_idx"
                    )
                ],
            },
        )
    ]
