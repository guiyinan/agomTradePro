"""Add exact archive coverage and isolated restore evidence."""

from __future__ import annotations

import uuid
from typing import Any

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q


def quarantine_legacy_archive_evidence(apps: Any, schema_editor: Any) -> None:
    """Fail closed: old caller-verified manifests cannot authorize deletion."""

    del schema_editor
    ArchiveManifest = apps.get_model("data_center", "ArchiveManifestModel")
    ArchiveManifest.objects.filter(state="verified").update(
        state="exported",
        verified_at=None,
        restore_outcome="not_tested",
        last_restored_at=None,
    )

    RetentionPolicy = apps.get_model("data_center", "RetentionPolicyModel")
    for policy in RetentionPolicy.objects.exclude(archive_after_days=None).iterator():
        if policy.archive_after_days > policy.retention_days:
            policy.archive_after_days = policy.retention_days
            policy.save(update_fields=["archive_after_days"])
    active_rows = RetentionPolicy.objects.filter(active=True).order_by(
        "dataset_key", "-version", "-policy_id"
    )
    seen: set[str] = set()
    deactivate: list[uuid.UUID] = []
    for row in active_rows.iterator():
        if row.dataset_key in seen:
            deactivate.append(row.policy_id)
        else:
            seen.add(row.dataset_key)
    if deactivate:
        RetentionPolicy.objects.filter(policy_id__in=deactivate).update(active=False)


class Migration(migrations.Migration):
    dependencies = [("data_center", "0062_providercredentialmodel")]

    operations = [
        migrations.AddField(
            model_name="retentionpolicymodel",
            name="archive_retention_days",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="contract_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="coverage_ended_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="coverage_started_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="encryption_algorithm",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="encryption_key_ref",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="encryption_key_version",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="format_version",
            field=models.CharField(
                default="raw-payload-fernet-jsonl-gzip-v1",
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="last_restored_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="restore_outcome",
            field=models.CharField(
                choices=[
                    ("not_tested", "not_tested"),
                    ("success", "success"),
                    ("failed", "failed"),
                ],
                db_index=True,
                default="not_tested",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="archivemanifestmodel",
            name="schema_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.CreateModel(
            name="ArchiveMemberModel",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("payload_id", models.UUIDField(db_index=True)),
                ("payload_hash", models.CharField(db_index=True, max_length=128)),
                ("record_digest", models.CharField(db_index=True, max_length=128)),
                ("schema_fingerprint", models.CharField(max_length=128)),
                ("fetched_at", models.DateTimeField(db_index=True)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                (
                    "archive",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="members",
                        to="data_center.archivemanifestmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_archive_member",
                "ordering": ["fetched_at", "payload_id"],
                "indexes": [
                    models.Index(
                        fields=["payload_id", "payload_hash"],
                        name="data_center_payload_59b604_idx",
                    ),
                    models.Index(
                        fields=["archive", "fetched_at"],
                        name="data_center_archive_004942_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("archive", "payload_id"),
                        name="dc_archive_member_payload_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ArchiveRestoreAuditModel",
            fields=[
                (
                    "audit_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("operation_key", models.CharField(max_length=240, unique=True)),
                (
                    "outcome",
                    models.CharField(
                        choices=[("success", "success"), ("failed", "failed")],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("observed_checksum", models.CharField(blank=True, max_length=128)),
                ("observed_object_count", models.PositiveBigIntegerField(default=0)),
                ("observed_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("restored_object_count", models.PositiveBigIntegerField(default=0)),
                ("restored_bytes", models.PositiveBigIntegerField(default=0)),
                ("started_at", models.DateTimeField(db_index=True)),
                ("finished_at", models.DateTimeField(db_index=True)),
                ("reason", models.TextField(blank=True)),
                (
                    "archive",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="restore_audits",
                        to="data_center.archivemanifestmodel",
                    ),
                ),
            ],
            options={
                "db_table": "data_center_archive_restore_audit",
                "ordering": ["-started_at"],
                "indexes": [
                    models.Index(
                        fields=["archive", "outcome", "started_at"],
                        name="data_center_archive_738067_idx",
                    )
                ],
            },
        ),
        migrations.RunPython(quarantine_legacy_archive_evidence, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="retentionpolicymodel",
            constraint=models.UniqueConstraint(
                condition=Q(active=True),
                fields=("dataset_key",),
                name="dc_retention_one_active_per_dataset",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivemanifestmodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(coverage_started_at__isnull=True, coverage_ended_at__isnull=True)
                    | Q(coverage_started_at__isnull=False, coverage_ended_at__isnull=False)
                ),
                name="dc_archive_coverage_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivemanifestmodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(coverage_started_at__isnull=True)
                    | Q(coverage_ended_at__gte=F("coverage_started_at"))
                ),
                name="dc_archive_coverage_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivemanifestmodel",
            constraint=models.CheckConstraint(
                condition=(~Q(state="verified") | Q(verified_at__isnull=False)),
                name="dc_archive_verified_at_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivemanifestmodel",
            constraint=models.CheckConstraint(
                condition=(~Q(restore_outcome="success") | Q(last_restored_at__isnull=False)),
                name="dc_archive_restore_time_required",
            ),
        ),
    ]
