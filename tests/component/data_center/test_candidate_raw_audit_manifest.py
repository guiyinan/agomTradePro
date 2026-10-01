"""Component coverage for candidate-level multi-batch RawAudit manifests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, models
from django.test.utils import CaptureQueriesContext

from apps.data_center.application.candidate_raw_audit_manifest import (
    CandidateRawAuditManifestService,
)
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
    CandidateRawAuditReference,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_models import (
    _MANIFEST_FIXTURE_RESTORE,
    CandidateRawAuditManifestMemberModel,
    CandidateRawAuditManifestModel,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.models import CanonicalPublicationModel, RawAuditModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository

pytestmark = pytest.mark.django_db(transaction=True)

PUBLICATION_RUN_ID = UUID("e274a1f3-44ee-4aaf-8224-a0a6b8522629")
DATASET_KEY = "equity.daily_price"
PUBLICATION_KEY = "2026-09-30"
PUBLICATION_HASH = hashlib.sha256(b"candidate-publication").hexdigest()


def _stageable_manifest(
    *,
    audit_count: int = 8,
    task_attempt_id: str = "full-market-task-attempt-1",
) -> CandidateRawAuditManifest:
    publication_id = uuid4()
    CanonicalPublicationModel._default_manager.create(
        publication_id=publication_id,
        dataset_key=DATASET_KEY,
        publication_key=PUBLICATION_KEY,
        policy_version="test-policy-v1",
        state=PublicationState.CANDIDATE.value,
        selected_source="provider-main",
        publication_hash=PUBLICATION_HASH,
        run_id=PUBLICATION_RUN_ID,
    )

    raw_repository = RawAuditRepository()
    references: list[CandidateRawAuditReference] = []
    for index in range(audit_count):
        saved = raw_repository.log(
            RawAudit(
                provider_name=f"provider-{index % 2}",
                capability="historical_price",
                request_params={"batch": index},
                status="ok",
                row_count=2,
                fetched_at=datetime(2026, 10, 1, 1, index, tzinfo=UTC),
                run_id=str(uuid4()),
                ingested_run_id=str(uuid4()),
            )
        )
        references.append(
            CandidateRawAuditReference(
                raw_audit_id=saved.raw_audit_id,
                version="1",
                content_hash=saved.content_hash,
                provider_name=saved.provider_name,
                capability=saved.capability,
                run_id=saved.run_id,
                ingested_run_id=saved.ingested_run_id,
            )
        )

    return CandidateRawAuditManifest.create(
        publication_id=str(publication_id),
        publication_hash=PUBLICATION_HASH,
        run_id=str(PUBLICATION_RUN_ID),
        dataset_key=DATASET_KEY,
        publication_key=PUBLICATION_KEY,
        task_attempt_id=task_attempt_id,
        raw_audits=tuple(reversed(references)),
    )


def test_stage_read_validate_and_retry_keep_all_batch_lineage() -> None:
    manifest = _stageable_manifest()
    repository = DjangoCandidateRawAuditManifestRepository()
    service = CandidateRawAuditManifestService(repository)

    staged = service.stage(
        publication_id=manifest.publication_id,
        publication_hash=manifest.publication_hash,
        run_id=manifest.run_id,
        dataset_key=manifest.dataset_key,
        publication_key=manifest.publication_key,
        task_attempt_id=manifest.task_attempt_id,
        raw_audits=manifest.raw_audits,
    )
    read = service.read(manifest.publication_id)
    validated = service.validate(manifest.publication_id)

    assert staged.manifest_hash == manifest.manifest_hash
    assert read is not None
    assert read.manifest_hash == manifest.manifest_hash
    assert validated == read
    assert validated.raw_audit_count == 8
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 8
    assert {item.run_id for item in validated.raw_audits} != {manifest.run_id}

    retry = CandidateRawAuditManifest.create(
        publication_id=manifest.publication_id,
        publication_hash=manifest.publication_hash,
        run_id=manifest.run_id,
        dataset_key=manifest.dataset_key,
        publication_key=manifest.publication_key,
        task_attempt_id=manifest.task_attempt_id,
        raw_audits=manifest.raw_audits,
    )
    retried = repository.stage(retry)
    assert retried.manifest_id == staged.manifest_id
    assert CandidateRawAuditManifestModel._default_manager.count() == 1
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 8

    changed_attempt = CandidateRawAuditManifest.create(
        publication_id=manifest.publication_id,
        publication_hash=manifest.publication_hash,
        run_id=manifest.run_id,
        dataset_key=manifest.dataset_key,
        publication_key=manifest.publication_key,
        task_attempt_id="full-market-task-attempt-2",
        raw_audits=manifest.raw_audits,
    )
    with pytest.raises(CandidateRawAuditManifestError, match="task-attempt"):
        repository.stage(changed_attempt)


def test_validate_bulk_reads_raw_audits_and_fails_closed_on_content_drift() -> None:
    manifest = _stageable_manifest(audit_count=25)
    repository = DjangoCandidateRawAuditManifestRepository()
    repository.stage(manifest)

    with CaptureQueriesContext(connection) as queries:
        repository.validate(manifest.publication_id)
    raw_audit_queries = [
        query for query in queries.captured_queries if RawAuditModel._meta.db_table in query["sql"]
    ]
    assert len(raw_audit_queries) == 1

    first_id = int(manifest.raw_audits[0].raw_audit_id)
    RawAuditModel._default_manager.filter(pk=first_id).update(content_hash="0" * 64)
    with pytest.raises(CandidateRawAuditManifestError, match="no longer matches"):
        repository.validate(manifest.publication_id)


def test_child_write_failure_rolls_back_inserted_header(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _stageable_manifest(audit_count=3)
    repository = DjangoCandidateRawAuditManifestRepository()

    def fail_member_insert(
        members: list[CandidateRawAuditManifestMemberModel],
    ) -> None:
        assert len(members) == 3
        raise CandidateRawAuditManifestError("injected child write failure")

    monkeypatch.setattr(repository, "_insert_members", fail_member_insert)
    with pytest.raises(CandidateRawAuditManifestError, match="child write"):
        repository.stage(manifest)

    assert CandidateRawAuditManifestModel._default_manager.count() == 0
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 0


def test_missing_batch_and_unclaimed_model_mutations_fail_closed() -> None:
    manifest = _stageable_manifest(audit_count=2)
    repository = DjangoCandidateRawAuditManifestRepository()
    missing_id = CandidateRawAuditManifest.create(
        publication_id=manifest.publication_id,
        publication_hash=manifest.publication_hash,
        run_id=manifest.run_id,
        dataset_key=manifest.dataset_key,
        publication_key=manifest.publication_key,
        task_attempt_id=manifest.task_attempt_id,
        raw_audits=(
            *manifest.raw_audits,
            CandidateRawAuditReference(
                raw_audit_id="999999999",
                version="1",
                content_hash="b" * 64,
                provider_name="missing-provider",
                capability="historical_price",
                run_id=str(uuid4()),
                ingested_run_id=str(uuid4()),
            ),
        ),
    )
    with pytest.raises(CandidateRawAuditManifestError, match="missing"):
        repository.stage(missing_id)

    audit_id = int(manifest.raw_audits[0].raw_audit_id)
    RawAuditModel._default_manager.filter(pk=audit_id).update(status="error")
    with pytest.raises(CandidateRawAuditManifestError, match="successful and non-empty"):
        repository.stage(manifest)
    RawAuditModel._default_manager.filter(pk=audit_id).update(status="ok", row_count=0)
    with pytest.raises(CandidateRawAuditManifestError, match="successful and non-empty"):
        repository.stage(manifest)

    header = CandidateRawAuditManifestModel(
        manifest_id=UUID(manifest.manifest_id),
        manifest_version=manifest.manifest_version,
        publication_id=UUID(manifest.publication_id),
        publication_hash=manifest.publication_hash,
        run_id=UUID(manifest.run_id),
        dataset_key=manifest.dataset_key,
        publication_key=manifest.publication_key,
        task_attempt_id=manifest.task_attempt_id,
        raw_audit_count=manifest.raw_audit_count,
        raw_audit_hash=manifest.raw_audit_hash,
        manifest_hash=manifest.manifest_hash,
    )
    with pytest.raises(ValidationError, match="append-only"):
        header.save_base(raw=True)
    with pytest.raises(ValidationError, match="capability"):
        models.Model.save_base(header, raw=False)
    with pytest.raises(ValidationError, match="repository staging"):
        CandidateRawAuditManifestModel._default_manager.bulk_create([header])
    with pytest.raises(ValidationError, match="low-level inserts require repository staging"):
        CandidateRawAuditManifestModel._default_manager.all()._insert([header], fields=[])
    assert CandidateRawAuditManifestModel._default_manager.count() == 0
    with pytest.raises(ValueError, match="default database"):
        DjangoCandidateRawAuditManifestRepository(using="replica")


def test_snapshot_dump_flush_and_runner_loaddata_round_trip_manifest_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _stageable_manifest(audit_count=4)
    repository = DjangoCandidateRawAuditManifestRepository()
    repository.stage(manifest)

    fixture_path = tmp_path / "candidate_raw_audit_manifest.json"
    call_command(
        "dumpdata",
        "data_center.CanonicalPublicationModel",
        "data_center.RawAuditModel",
        "data_center.CandidateRawAuditManifestModel",
        "data_center.CandidateRawAuditManifestMemberModel",
        output=str(fixture_path),
        verbosity=0,
    )
    assert fixture_path.is_file()

    call_command("flush", verbosity=0, interactive=False)
    assert CandidateRawAuditManifestModel._default_manager.count() == 0
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 0

    with pytest.raises(ValidationError, match="capability"):
        call_command("loaddata", str(fixture_path), verbosity=0)
    assert CandidateRawAuditManifestModel._default_manager.count() == 0
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 0

    import scripts.manage_vps_migrations as migration_runner

    monkeypatch.setattr(
        migration_runner.connection_created, "connect", lambda *args, **kwargs: None
    )
    migration_runner.main(["loaddata", str(fixture_path)])

    assert CanonicalPublicationModel._default_manager.count() == 1
    assert RawAuditModel._default_manager.count() == 4
    assert CandidateRawAuditManifestModel._default_manager.count() == 1
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 4
    restored = repository.validate(manifest.publication_id)
    assert restored.manifest_hash == manifest.manifest_hash
    assert restored.task_attempt_id == manifest.task_attempt_id
    assert restored.raw_audits == manifest.raw_audits
    assert _MANIFEST_FIXTURE_RESTORE.get() is None


def test_migration_runner_grants_restore_capability_only_to_allowlisted_loaddata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.manage_vps_migrations as migration_runner

    observed: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        migration_runner.connection_created, "connect", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        migration_runner,
        "execute_from_command_line",
        lambda arguments: observed.append(
            (cast(str, arguments[1]), _MANIFEST_FIXTURE_RESTORE.get() is not None)
        ),
    )

    migration_runner.main(["migrate"])
    migration_runner.main(["flush"])
    migration_runner.main(["loaddata", "snapshot.json"])

    assert observed == [("migrate", False), ("flush", False), ("loaddata", True)]
