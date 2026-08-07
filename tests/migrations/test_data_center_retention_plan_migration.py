"""Forward/reverse evidence for exact Data Center retention plans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError

NOW = datetime(2026, 8, 7, 5, 0, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_retention_plan_migration_forward_reverse_and_reapply() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0063_archivemanifest_archive_restore_evidence")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [("data_center", "0063_archivemanifest_archive_restore_evidence")]
        ).apps
        with pytest.raises(LookupError):
            old_apps.get_model("data_center", "RetentionPlanModel")

        executor.migrate([("data_center", "0066_make_retention_digest_widening_reversible")])
        executor = MigrationExecutor(connection)
        new_apps = executor.loader.project_state(
            [("data_center", "0066_make_retention_digest_widening_reversible")]
        ).apps
        Archive = new_apps.get_model("data_center", "ArchiveManifestModel")
        Plan = new_apps.get_model("data_center", "RetentionPlanModel")
        Member = new_apps.get_model("data_center", "RetentionPlanMemberModel")
        archive = Archive.objects.create(
            archive_id=uuid4(),
            dataset_key="market.raw",
            object_count=1,
            size_bytes=128,
            location="archive/migration-fixture.bin",
            checksum="a" * 64,
            state="verified",
            created_at=NOW,
            verified_at=NOW,
            retention_until=NOW + timedelta(days=365),
            contract_version="raw-payload-v1",
            schema_version="raw-payload-v1",
            format_version="raw-payload-fernet-jsonl-gzip-v1",
            encryption_algorithm="fernet",
            encryption_key_ref="test-key",
            encryption_key_version="v1",
            coverage_started_at=NOW - timedelta(days=31),
            coverage_ended_at=NOW - timedelta(days=31),
            restore_outcome="success",
            last_restored_at=NOW,
        )
        plan = Plan.objects.create(
            plan_id=uuid4(),
            operation_id="migration-plan",
            dataset_key="market.raw",
            policy_id=uuid4(),
            policy_version=1,
            requested=10,
            candidates=1,
            planned=1,
            held=0,
            blocked=0,
            bytes_planned=128,
            cutoff=NOW - timedelta(days=30),
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            snapshot_digest="b" * 64,
            status="ready",
            outcome="success",
        )
        member = Member.objects.create(
            plan=plan,
            ordinal=0,
            payload_id=uuid4(),
            payload_hash="sha256:" + ("c" * 64),
            record_digest="sha256:" + ("d" * 64),
            schema_fingerprint="sha256:schema",
            fetched_at=NOW - timedelta(days=31),
            size_bytes=128,
            decision="eligible",
            archive=archive,
            execution="pending",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Member.objects.create(
                plan=plan,
                ordinal=1,
                payload_id=member.payload_id,
                payload_hash="sha256:" + ("e" * 64),
                record_digest="sha256:" + ("f" * 64),
                schema_fingerprint="sha256:schema",
                fetched_at=NOW - timedelta(days=31),
                size_bytes=128,
                decision="eligible",
                archive=archive,
                execution="pending",
            )
        with pytest.raises(ProtectedError):
            archive.delete()

        executor.migrate([("data_center", "0063_archivemanifest_archive_restore_evidence")])
        executor = MigrationExecutor(connection)
        reversed_apps = executor.loader.project_state(
            [("data_center", "0063_archivemanifest_archive_restore_evidence")]
        ).apps
        with pytest.raises(LookupError):
            reversed_apps.get_model("data_center", "RetentionPlanModel")

        executor.migrate([("data_center", "0066_make_retention_digest_widening_reversible")])
        executor = MigrationExecutor(connection)
        reapplied_apps = executor.loader.project_state(
            [("data_center", "0066_make_retention_digest_widening_reversible")]
        ).apps
        assert reapplied_apps.get_model("data_center", "RetentionPlanModel") is not None
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
