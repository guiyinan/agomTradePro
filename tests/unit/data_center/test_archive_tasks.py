"""Celery boundary contracts for the trusted cold-archive lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

import apps.data_center.application.archive_tasks as archive_tasks


@dataclass(frozen=True)
class _Result:
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return self.payload


class _SuccessfulUseCase:
    def __init__(self, *_dependencies: object) -> None:
        pass

    def execute(self, **kwargs: object) -> _Result:
        operation = "export" if "dataset_key" in kwargs else "verify"
        if "operation_id" in kwargs:
            operation = "restore"
        return _Result(
            {
                "outcome": "success",
                "success": True,
                "operation": operation,
                "archive_id": str(kwargs.get("archive_id", "archive-1")),
                "dataset_key": str(kwargs.get("dataset_key", "market.raw")),
                "requested": 1,
                "candidates": 1,
                "succeeded": 1,
                "failed": 0,
                "stored": 1,
                "object_count": 1,
                "size_bytes": 128,
                "reason": "verified",
            }
        )


class _NoopUseCase:
    def __init__(self, *_dependencies: object) -> None:
        pass

    def execute(self, **kwargs: object) -> _Result:
        operation = "restore" if "operation_id" in kwargs else "export"
        return _Result(
            {
                "outcome": "noop",
                "success": True,
                "operation": operation,
                "archive_id": str(kwargs.get("archive_id", "archive-1")),
                "dataset_key": str(kwargs.get("dataset_key", "market.raw")),
                "requested": 1,
                "candidates": 0,
                "succeeded": 0,
                "failed": 0,
                "stored": 0,
                "object_count": 0,
                "size_bytes": 0,
                "reason": "already_recorded",
            }
        )


class _ExplodingUseCase:
    def __init__(self, *_dependencies: object) -> None:
        pass

    def execute(self, **_kwargs: object) -> _Result:
        raise OSError("fixture failure")


def _patch_dependencies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for name in (
        "get_retention_policy_repository",
        "get_dataset_contract_repository",
        "get_archive_candidate_repository",
        "get_archive_manifest_repository",
        "get_raw_archive_store",
        "get_archive_capacity_guard",
    ):
        monkeypatch.setattr(archive_tasks, name, lambda: object())


def test_archive_raw_payloads_task_rejects_invalid_input_before_dependencies(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        archive_tasks,
        "get_retention_policy_repository",
        lambda: (_ for _ in ()).throw(AssertionError("must not resolve dependencies")),
    )

    result = archive_tasks.archive_raw_payloads_task(dataset_key="", limit=100)

    assert result["outcome"] == "failed"
    assert result["reason"] == "dataset_key is required"


def test_archive_raw_payloads_task_reports_real_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "ArchiveRawPayloadsUseCase", _SuccessfulUseCase)

    result = archive_tasks.archive_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "success"
    assert result["stored"] == 1


def test_archive_raw_payloads_task_reports_zero_output_as_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "ArchiveRawPayloadsUseCase", _NoopUseCase)

    result = archive_tasks.archive_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "noop"
    assert result["stored"] == 0


def test_archive_raw_payloads_task_blocks_when_cold_store_is_unconfigured(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(
        archive_tasks,
        "get_raw_archive_store",
        lambda: (_ for _ in ()).throw(RuntimeError("archive_root_missing")),
    )

    result = archive_tasks.archive_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "archive_root_missing"


def test_archive_raw_payloads_task_reports_complete_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "ArchiveRawPayloadsUseCase", _ExplodingUseCase)

    result = archive_tasks.archive_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "failed"
    assert result["reason"] == "archive_export_failed"


def test_verify_archive_manifest_task_rejects_invalid_input(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        archive_tasks,
        "get_archive_manifest_repository",
        lambda: (_ for _ in ()).throw(AssertionError("must not resolve dependencies")),
    )

    result = archive_tasks.verify_archive_manifest_task(archive_id="")

    assert result["outcome"] == "failed"
    assert result["reason"] == "archive_id is required"


def test_verify_archive_manifest_task_reports_store_backed_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "VerifyStoredArchiveUseCase", _SuccessfulUseCase)

    result = archive_tasks.verify_archive_manifest_task(archive_id="archive-1")

    assert result["outcome"] == "success"
    assert result["succeeded"] == 1


def test_verify_archive_manifest_task_blocks_without_cold_store(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(
        archive_tasks,
        "get_raw_archive_store",
        lambda: (_ for _ in ()).throw(RuntimeError("archive_key_missing")),
    )

    result = archive_tasks.verify_archive_manifest_task(archive_id="archive-1")

    assert result["outcome"] == "blocked"
    assert result["reason"] == "archive_key_missing"


def test_verify_archive_manifest_task_reports_complete_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "VerifyStoredArchiveUseCase", _ExplodingUseCase)

    result = archive_tasks.verify_archive_manifest_task(archive_id="archive-1")

    assert result["outcome"] == "failed"
    assert result["reason"] == "archive_verification_failed"


def test_audit_archive_restore_task_requires_stable_operation_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        archive_tasks,
        "get_archive_manifest_repository",
        lambda: (_ for _ in ()).throw(AssertionError("must not resolve dependencies")),
    )

    result = archive_tasks.audit_archive_restore_task(
        archive_id="archive-1",
        operation_id="",
    )

    assert result["outcome"] == "failed"
    assert result["reason"] == "operation_id is required"


def test_audit_archive_restore_task_reports_real_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "AuditArchiveRestoreUseCase", _SuccessfulUseCase)

    result = archive_tasks.audit_archive_restore_task(
        archive_id="archive-1",
        operation_id="monthly-2026-08",
    )

    assert result["outcome"] == "success"
    assert result["operation"] == "restore"


def test_audit_archive_restore_task_reports_idempotent_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "AuditArchiveRestoreUseCase", _NoopUseCase)

    result = archive_tasks.audit_archive_restore_task(
        archive_id="archive-1",
        operation_id="monthly-2026-08",
    )

    assert result["outcome"] == "noop"
    assert result["stored"] == 0


def test_audit_archive_restore_task_blocks_without_cold_store(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(
        archive_tasks,
        "get_raw_archive_store",
        lambda: (_ for _ in ()).throw(RuntimeError("archive_key_missing")),
    )

    result = archive_tasks.audit_archive_restore_task(
        archive_id="archive-1",
        operation_id="monthly-2026-08",
    )

    assert result["outcome"] == "blocked"
    assert result["reason"] == "archive_key_missing"


def test_audit_archive_restore_task_reports_complete_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_dependencies(monkeypatch)
    monkeypatch.setattr(archive_tasks, "AuditArchiveRestoreUseCase", _ExplodingUseCase)

    result = archive_tasks.audit_archive_restore_task(
        archive_id="archive-1",
        operation_id="monthly-2026-08",
    )

    assert result["outcome"] == "failed"
    assert result["reason"] == "archive_restore_audit_failed"
