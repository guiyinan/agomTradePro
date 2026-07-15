import uuid
from typing import Any

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_collected_semantic_keys(apps: Any, schema_editor: Any) -> None:
    """Copy existing effective semantic keys into collected-key evidence."""

    catalog = apps.get_model("ai_capability", "CapabilityCatalogModel")
    catalog.objects.filter(collected_semantic_key="").update(
        collected_semantic_key=models.F("semantic_key")
    )


def clear_collected_semantic_keys(apps: Any, schema_editor: Any) -> None:
    """Clear backfilled evidence before reversing the field addition."""

    catalog = apps.get_model("ai_capability", "CapabilityCatalogModel")
    catalog.objects.update(collected_semantic_key="")


class Migration(migrations.Migration):
    dependencies = [
        ("ai_capability", "0004_capabilitycatalogmodel_semantic_key"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="capabilitycatalogmodel",
            name="collected_semantic_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Semantic key collected from the source before manual override",
                max_length=255,
            ),
        ),
        migrations.RunPython(
            backfill_collected_semantic_keys,
            clear_collected_semantic_keys,
        ),
        migrations.CreateModel(
            name="CapabilitySemanticOverrideModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("capability_key", models.CharField(max_length=255, unique=True)),
                ("semantic_key", models.CharField(max_length=255)),
                ("reason", models.TextField()),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="semantic_capability_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "ai_capability_semantic_override",
                "ordering": ["capability_key"],
            },
        ),
        migrations.CreateModel(
            name="CapabilitySemanticAuditModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                    ),
                ),
                ("idempotency_key", models.CharField(db_index=True, max_length=255)),
                ("capability_key", models.CharField(db_index=True, max_length=255)),
                (
                    "action",
                    models.CharField(
                        choices=[("set", "Set"), ("remove", "Remove")],
                        max_length=10,
                    ),
                ),
                (
                    "old_collected_value",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "old_effective_value",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "new_effective_value",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("reason", models.TextField()),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "operator",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="semantic_capability_audits",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "ai_capability_semantic_audit",
                "ordering": ["-created_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["idempotency_key", "request_fingerprint"],
                        name="ai_capabili_idempot_bf0320_idx",
                    ),
                    models.Index(
                        fields=["capability_key", "-created_at"],
                        name="ai_capabili_capabil_a842c5_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="capabilitysemanticoverridemodel",
            constraint=models.CheckConstraint(
                condition=~models.Q(("semantic_key", "")),
                name="ai_cap_sem_override_key_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="capabilitysemanticoverridemodel",
            constraint=models.CheckConstraint(
                condition=~models.Q(("reason", "")),
                name="ai_cap_sem_override_reason_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="capabilitysemanticauditmodel",
            constraint=models.UniqueConstraint(
                fields=("idempotency_key", "capability_key"),
                name="ai_cap_sem_audit_idem_cap_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="capabilitysemanticauditmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("action__in", ["set", "remove"])),
                name="ai_cap_sem_audit_action_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="capabilitysemanticauditmodel",
            constraint=models.CheckConstraint(
                condition=~models.Q(("reason", "")),
                name="ai_cap_sem_audit_reason_nonempty",
            ),
        ),
    ]
