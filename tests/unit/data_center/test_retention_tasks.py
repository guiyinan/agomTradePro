"""Behavioral evidence for policy-gated raw retention tasks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apps.data_center.application.tasks import cleanup_expired_raw_payloads_task
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.retention import RetentionPolicy

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


class _Policies:
    def __init__(self, policy: RetentionPolicy | None) -> None:
        self.policy = policy

    def get_active(self, dataset_key: str) -> RetentionPolicy | None:
        return self.policy if self.policy and self.policy.dataset_key == dataset_key else None


class _Holds:
    def __init__(self, held: set[str] | None = None) -> None:
        self.held = held or set()

    def has_active_hold(self, resource_type: str, resource_key: str, *, now: datetime | None = None) -> bool:
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

    def list_expired(self, dataset_key: str, *, before: datetime, limit: int) -> list[RawPayload]:
        return [row for row in self.rows if row.dataset_key == dataset_key and row.fetched_at < before][:limit]

    def delete(self, payload_id: str) -> int:
        self.deleted.append(payload_id)
        return 1


def _policy() -> RetentionPolicy:
    return RetentionPolicy(
        policy_id=str(uuid4()),
        dataset_key="market.raw",
        version=1,
        retention_days=30,
        active=True,
    )


def _payload() -> RawPayload:
    return RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash="sha256:payload",
        schema_fingerprint="sha256:schema",
        payload={"value": 1},
        fetched_at=NOW - timedelta(days=31),
    )


def _patch_task_dependencies(monkeypatch, policies, holds, archives, candidates) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: {"state": "healthy"},
    )
    monkeypatch.setattr("apps.data_center.application.tasks.get_retention_policy_repository", lambda: policies)
    monkeypatch.setattr("apps.data_center.application.tasks.get_storage_hold_repository", lambda: holds)
    monkeypatch.setattr("apps.data_center.application.tasks.get_archive_manifest_repository", lambda: archives)
    monkeypatch.setattr("apps.data_center.application.tasks.get_raw_landing_repository", lambda: candidates)


def test_retention_task_rejects_invalid_input_before_repositories() -> None:
    result = cleanup_expired_raw_payloads_task(dataset_key="", limit=100)
    assert result["outcome"] == "failed"
    assert result["deleted"] == 0


def test_retention_task_blocks_without_active_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([])
    _patch_task_dependencies(monkeypatch, _Policies(None), _Holds(), _Archives(True), candidates)

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "retention_policy_missing_or_inactive"


def test_retention_task_reports_all_success_after_verified_archive(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    _patch_task_dependencies(monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates)

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "success"
    assert result["deleted"] == 1
    assert len(candidates.deleted) == 1


def test_retention_task_reports_partial_for_active_hold(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload()
    candidates = _Candidates([payload])
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds({payload.payload_id}),
        _Archives(True),
        candidates,
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "partial"
    assert result["held"] == 1
    assert result["deleted"] == 0
