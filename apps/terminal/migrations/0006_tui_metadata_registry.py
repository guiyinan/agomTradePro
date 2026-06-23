"""Add published TUI metadata registry."""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("terminal", "0005_seed_market_temperature_command"),
    ]

    operations = [
        migrations.CreateModel(
            name="TuiMetadataRegistryORM",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("registry_key", models.CharField(db_index=True, default="default", max_length=80)),
                ("version", models.CharField(default="tui-workbench.v2", max_length=40)),
                ("schema_version", models.CharField(default="tui-metadata.v3", max_length=40)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("published", "Published"),
                            ("archived", "Archived"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "generation_source",
                    models.CharField(
                        choices=[
                            ("ai", "AI"),
                            ("manual", "Manual"),
                            ("mixed", "Mixed"),
                        ],
                        default="mixed",
                        max_length=20,
                    ),
                ),
                ("backend_version", models.CharField(blank=True, max_length=80)),
                ("payload", models.JSONField(default=dict)),
                ("source_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("source_evidence_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("changed_fields", models.JSONField(blank=True, default=list)),
                ("review_note", models.TextField(blank=True)),
                ("published_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_tui_metadata_registries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "rollback_of",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rollback_releases",
                        to="terminal.tuimetadataregistryorm",
                    ),
                ),
            ],
            options={
                "verbose_name": "TUI 元数据发布注册表",
                "verbose_name_plural": "TUI 元数据发布注册表",
                "db_table": "terminal_tui_metadata_registry",
                "ordering": ["-published_at", "-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="tuimetadataregistryorm",
            index=models.Index(fields=["registry_key", "status", "-published_at"], name="terminal_tu_registr_380299_idx"),
        ),
    ]
