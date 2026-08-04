"""Behavioral evidence for policy-gated raw retention tasks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from apps.data_center.application.tasks import (
    cleanup_expired_raw_payloads_task,
    enforce_retention_task,
    plan_retention_task,
    verify_archive_manifest_task,
    verify_storage_budget_task,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveState,
    RetentionPolicy,
    RetentionRun,
)

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


class _Policies:
    def __init__(self, policy: RetentionPolicy | None) -> None:
        self.policy = policy

    def get_active(self, dataset_key: str) -> RetentionPolicy | None:
        return self.policy if self.policy and self.policy.dataset_key == dataset_key else None


class _Holds:
    def __init__(self, held: set[str] | None = None) -> None:
        self.held = held or set()

    def has_active_hold(
        self, resource_type: str, resource_key: str, *, now: datetime | None = None
    ) -> bool:
        return resource_key in self.held


class _Archives:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def has_verified_for_dataset(self, dataset_key: str, *, now: datetime | None = None) -> bool:
        return self.ready


class _Candidates:
    def __init__(self, rows: list[RawPayload]) -> None:
        self.rows = rows
        self.deleted: list[str] = []

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
        now: datetime | None = None,
    ) -> list[RawPayload]:
        return [
            row
            for row in self.rows
            if row.dataset_key == dataset_key
            and row.fetched_at < before
            and (row.retention_until is None or now is None or row.retention_until <= now)
        ][:limit]

    def delete(self, payload_id: str) -> int:
        self.deleted.append(payload_id)
        return 1


class _Runs:
    def __init__(self) -> None:
        self.saved: list[RetentionRun] = []

    def save(self, run: RetentionRun) -> RetentionRun:
        self.saved.append(run)
        return run


class _VerifiableArchives:
    def __init__(self, manifest: ArchiveManifest | None) -> None:
        self.manifest = manifest
        self.marked = False

    def get(self, archive_id: str) -> ArchiveManifest | None:
        if self.manifest is None or self.manifest.archive_id != archive_id:
            return None
        return self.manifest

    def mark_verified(
        self, archive_id: str, *, verified_at: datetime | None = None
    ) -> ArchiveManifest:
        if self.manifest is None or self.manifest.archive_id != archive_id:
            raise LookupError("archive not found")
        self.marked = True
        self.manifest = replace(
            self.manifest,
            state=ArchiveState.VERIFIED,
            verified_at=verified_at or NOW,
        )
        return self.manifest


def _archive_manifest() -> ArchiveManifest:
    return ArchiveManifest(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        object_count=2,
        size_bytes=256,
        location="s3://fixture/archive.tar.zst",
        checksum="sha256:archive",
        state=ArchiveState.EXPORTED,
        created_at=NOW,
    )


def _policy() -> RetentionPolicy:
    return RetentionPolicy(
        policy_id=str(uuid4()),
        dataset_key="market.raw",
        version=1,
        retention_days=30,
        active=True,
    )


def _payload(*, retention_until: datetime | None = None) -> RawPayload:
    return RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash="sha256:payload",
        schema_fingerprint="sha256:schema",
        payload={"value": 1},
        fetched_at=NOW - timedelta(days=31),
        payload_size_bytes=128,
        retention_until=retention_until,
    )


def _patch_task_dependencies(
    monkeypatch,
    policies,
    holds,
    archives,
    candidates,
    runs,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: {"state": "healthy"},
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository", lambda: policies
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_storage_hold_repository", lambda: holds
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_archive_manifest_repository", lambda: archives
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_raw_landing_repository", lambda: candidates
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_run_repository", lambda: runs
    )


def test_retention_task_rejects_invalid_input_before_repositories() -> None:
    result = cleanup_expired_raw_payloads_task(dataset_key="", limit=100)
    assert result["outcome"] == "failed"
    assert result["deleted"] == 0


def test_retention_task_blocks_without_active_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(None), _Holds(), _Archives(True), candidates, runs
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "retention_policy_missing_or_inactive"
    assert runs.saved[0].outcome == "blocked"


def test_retention_task_reports_all_success_after_verified_archive(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, runs
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "success"
    assert result["deleted"] == 1
    assert len(candidates.deleted) == 1
    assert runs.saved[0].bytes_deleted == 128
    assert runs.saved[0].dry_run is False


def test_retention_task_reports_partial_for_active_hold(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload()
    candidates = _Candidates([payload])
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds({payload.payload_id}),
        _Archives(True),
        candidates,
        _Runs(),
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "partial"
    assert result["held"] == 1
    assert result["deleted"] == 0


def test_retention_task_does_not_delete_before_row_retention_deadline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload(retention_until=datetime.now(UTC) + timedelta(days=1))
    candidates = _Candidates([payload])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, runs
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "noop"
    assert result["deleted"] == 0
    assert candidates.deleted == []


class _UnsafeCandidates(_Candidates):
    """Legacy candidate adapter that ignores row-level retention deadlines."""

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
        now: datetime | None = None,
    ) -> list[RawPayload]:
        del now
        return [
            row for row in self.rows if row.dataset_key == dataset_key and row.fetched_at < before
        ][:limit]


def test_retention_task_fails_closed_for_legacy_future_deadline_candidate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload(retention_until=datetime.now(UTC) + timedelta(days=1))
    candidates = _UnsafeCandidates([payload])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, runs
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "retention_until_not_reached"
    assert result["blocked"] == 1
    assert result["deleted"] == 0
    assert candidates.deleted == []


def test_retention_task_reports_storage_evaluation_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("observer down")),
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository",
        lambda: (_ for _ in ()).throw(AssertionError("repository must not be reached")),
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "failed"
    assert result["error"] == "storage_pressure_evaluation_failed"


def test_plan_retention_task_rejects_invalid_limit() -> None:
    result = plan_retention_task(dataset_key="market.raw", limit=0)

    assert result["outcome"] == "failed"
    assert result["operation"] == "plan"


def test_plan_retention_task_is_always_dry_run(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, _Runs()
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "noop"
    assert result["operation"] == "plan"
    assert result["planned"] == 1
    assert result["deleted"] == 0
    assert candidates.deleted == []


def test_plan_retention_task_blocks_without_storage_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: {"state": "blocked", "reason": "storage_policy_missing"},
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository",
        lambda: (_ for _ in ()).throw(AssertionError("retention repository must not be reached")),
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "blocked"
    assert result["error"] == "storage_policy_missing"


def test_enforce_retention_task_rejects_non_boolean_confirmation() -> None:
    result = enforce_retention_task(
        dataset_key="market.raw", limit=10, dry_run=False, confirm=1  # type: ignore[arg-type]
    )

    assert result["outcome"] == "failed"
    assert result["error"] == "confirm must be a boolean"


def test_enforce_retention_task_deletes_only_with_confirmation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, _Runs()
    )

    result = enforce_retention_task(dataset_key="market.raw", limit=10, dry_run=False, confirm=True)

    assert result["outcome"] == "success"
    assert result["operation"] == "enforce"
    assert result["deleted"] == 1
    assert len(candidates.deleted) == 1


def test_enforce_retention_task_requires_explicit_confirmation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, _Runs()
    )

    result = enforce_retention_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "blocked"
    assert result["error"] == "explicit_confirmation_required"
    assert candidates.deleted == []


def test_archive_verification_rejects_invalid_evidence_before_repository(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_archive_manifest_repository",
        lambda: (_ for _ in ()).throw(AssertionError("repository must not be reached")),
    )

    result = verify_archive_manifest_task(
        archive_id="archive-1",
        observed_checksum="sha256:archive",
        observed_object_count=True,  # type: ignore[arg-type]
        observed_size_bytes=256,
    )

    assert result["outcome"] == "failed"
    assert result["reason"] == "observed_object_count must be a non-negative integer"


def test_archive_verification_marks_matching_manifest_verified(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repository = _VerifiableArchives(_archive_manifest())
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_archive_manifest_repository", lambda: repository
    )

    result = verify_archive_manifest_task(
        archive_id=repository.manifest.archive_id,
        observed_checksum="sha256:archive",
        observed_object_count=2,
        observed_size_bytes=256,
    )

    assert result["outcome"] == "success"
    assert result["reason"] == "archive_manifest_verified"
    assert repository.marked is True
    assert repository.manifest.state is ArchiveState.VERIFIED


def test_archive_verification_blocks_checksum_mismatch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repository = _VerifiableArchives(_archive_manifest())
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_archive_manifest_repository", lambda: repository
    )

    result = verify_archive_manifest_task(
        archive_id=repository.manifest.archive_id,
        observed_checksum="sha256:tampered",
        observed_object_count=2,
        observed_size_bytes=256,
    )

    assert result["outcome"] == "blocked"
    assert result["reason"] == "archive_manifest_evidence_mismatch"
    assert repository.marked is False


def test_archive_verification_reports_repository_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_archive_manifest_repository",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    result = verify_archive_manifest_task(
        archive_id="archive-1",
        observed_checksum="sha256:archive",
        observed_object_count=2,
        observed_size_bytes=256,
    )

    assert result["outcome"] == "failed"
    assert result["reason"] == "archive_manifest_verification_failed"


def _patch_storage_probe(monkeypatch, pressure: dict[str, object]) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, used=20, free=80),
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: pressure,
    )


def test_storage_budget_task_reports_healthy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_storage_probe(monkeypatch, {"state": "healthy", "usage_ratio": 0.2})

    result = verify_storage_budget_task()

    assert result["outcome"] == "success"
    assert result["succeeded"] == 1
    assert result["failed"] == 0


def test_storage_budget_task_reports_warning_as_partial(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_storage_probe(monkeypatch, {"state": "warning", "usage_ratio": 0.8})

    result = verify_storage_budget_task()

    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["succeeded"] == 1


def test_storage_budget_task_blocks_critical_pressure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_storage_probe(monkeypatch, {"state": "critical", "usage_ratio": 0.95})

    result = verify_storage_budget_task()

    assert result["outcome"] == "blocked"
    assert result["blocked"] == 1
    assert result["error"] == "storage_pressure_critical"


def test_storage_budget_task_reports_observer_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.shutil.disk_usage",
        lambda _path: (_ for _ in ()).throw(OSError("mount unavailable")),
    )

    result = verify_storage_budget_task()

    assert result["outcome"] == "failed"
    assert result["error"] == "storage_budget_verification_failed"


def test_storage_budget_task_rejects_non_string_path() -> None:
    result = verify_storage_budget_task(storage_path=1)  # type: ignore[arg-type]

    assert result["outcome"] == "failed"
    assert result["error"] == "storage_path must be a string"
