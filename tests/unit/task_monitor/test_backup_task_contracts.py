"""Exact business-outcome and recovery contracts for database backup tasks."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.task_monitor.application import backup_tasks
from apps.task_monitor.infrastructure.backup_service import (
    DatabaseBackupResult,
    DatabaseBackupService,
)
from apps.task_monitor.management.commands import backup_database as backup_command


def _healthy_capacity() -> dict[str, object]:
    return {
        "state": "healthy",
        "reason": "within_active_policy",
        "observation_id": "capacity-1",
        "database_size_bytes": 128,
        "projected_used_bytes": 256,
    }


def test_backup_database_task_rejects_invalid_input_before_capacity_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capacity = SimpleNamespace(called=False)

    def fail_if_called() -> dict[str, object]:
        capacity.called = True
        raise AssertionError("capacity preflight must not run for invalid input")

    monkeypatch.setattr(backup_tasks, "collect_backup_capacity_report", fail_if_called)

    result = backup_tasks.backup_database_task.run(keep_days=0)

    assert result["outcome"] == "failed"
    assert result["reason"] == "keep_days_must_be_between_1_and_3650"
    assert result["failed"] == 1
    assert capacity.called is False


def test_backup_database_task_creates_one_verified_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBackupService:
        def backup_database(
            self,
            *,
            keep_days: int | None,
            compress: bool,
            output_dir: str | None,
        ) -> DatabaseBackupResult:
            assert keep_days == 1
            assert compress is True
            assert output_dir == "D:/backups"
            return DatabaseBackupResult(
                backup_file="D:/backups/postgres-current.dump",
                removed_old_backups=4,
                keep_days=1,
                compressed=True,
                engine="django.db.backends.postgresql",
                sha256="a" * 64,
                size_bytes=1024,
                backup_format="postgresql-custom",
            )

    monkeypatch.setattr(backup_tasks, "collect_backup_capacity_report", _healthy_capacity)
    monkeypatch.setattr(
        backup_tasks,
        "get_database_backup_service",
        lambda: FakeBackupService(),
    )

    result = backup_tasks.backup_database_task.run(
        keep_days=1,
        output_dir="D:/backups",
    )

    assert result["outcome"] == "success"
    assert result["success"] is True
    assert result["requested"] == result["succeeded"] == result["stored"] == 1
    assert result["failed"] == 0
    assert result["backup_format"] == "postgresql-custom"
    assert result["sha256"] == "a" * 64


def test_backup_database_task_blocks_at_critical_projected_pressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backup_tasks,
        "collect_backup_capacity_report",
        lambda: {"state": "critical", "reason": "critical_watermark_reached"},
    )
    monkeypatch.setattr(
        backup_tasks,
        "get_database_backup_service",
        lambda: pytest.fail("backup service must not run while capacity is critical"),
    )

    result = backup_tasks.backup_database_task.run(keep_days=1)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "critical_watermark_reached"
    assert result["stored"] == 0


def test_backup_database_task_propagates_complete_backup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingBackupService:
        def backup_database(self, **_kwargs: object) -> DatabaseBackupResult:
            raise RuntimeError("backup_failed")

    monkeypatch.setattr(backup_tasks, "collect_backup_capacity_report", _healthy_capacity)
    monkeypatch.setattr(
        backup_tasks,
        "get_database_backup_service",
        lambda: FailingBackupService(),
    )

    with pytest.raises(RuntimeError, match="backup_failed"):
        backup_tasks.backup_database_task.run(keep_days=1)


def test_backup_management_command_blocks_before_backup_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backup_command,
        "require_backup_capacity",
        lambda: (_ for _ in ()).throw(RuntimeError("critical_watermark_reached")),
    )
    monkeypatch.setattr(
        backup_command,
        "get_database_backup_service",
        lambda: pytest.fail("management command must not bypass capacity preflight"),
    )

    with pytest.raises(CommandError, match="critical_watermark_reached"):
        backup_command.Command().handle(output=None, keep=1, compress=True)


def test_verify_backup_task_rejects_invalid_input() -> None:
    result = backup_tasks.verify_backup_task.run("")

    assert result["outcome"] == "failed"
    assert result["reason"] == "backup_file_must_be_non_empty_string"


def test_verify_backup_task_accepts_readable_artifact_and_matching_sha(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "database.sqlite3.gz"
    with gzip.open(backup, "wb") as stream:
        stream.write(b"verified-backup")
    expected = hashlib.sha256(backup.read_bytes()).hexdigest()

    result = backup_tasks.verify_backup_task.run(str(backup), expected)

    assert result["outcome"] == "success"
    assert result["sha256"] == expected
    assert result["succeeded"] == 1


def test_verify_backup_task_reports_unreadable_artifact(tmp_path: Path) -> None:
    corrupt = tmp_path / "database.sqlite3.gz"
    corrupt.write_bytes(b"not-gzip")

    result = backup_tasks.verify_backup_task.run(str(corrupt))

    assert result["outcome"] == "failed"
    assert result["reason"] == "backup_artifact_unreadable"


def test_postgresql_backup_is_custom_atomic_verified_and_single_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: object,
) -> None:
    database_settings = {
        **settings.DATABASES["default"],  # type: ignore[attr-defined]
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "agom",
        "USER": "agom",
        "HOST": "postgres",
        "PORT": "5432",
        "PASSWORD": "secret",
    }
    monkeypatch.setitem(
        settings.DATABASES,  # type: ignore[attr-defined]
        "default",
        database_settings,
    )
    output = tmp_path / "backups"
    output.mkdir()
    (output / "postgres-20260801.dump").write_bytes(b"old")
    (output / "db_backup_20260802.sql.gz").write_bytes(b"old")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        if command[0] == "pg_dump":
            target = Path(command[command.index("-f") + 1])
            target.write_bytes(b"PGDMP-custom-format")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = DatabaseBackupService().backup_database(
        keep_days=1,
        compress=True,
        output_dir=str(output),
    )

    current = output / "postgres-current.dump"
    assert current.read_bytes() == b"PGDMP-custom-format"
    assert not (output / ".postgres-current.dump.partial").exists()
    assert [path.name for path in output.glob("*.dump")] == ["postgres-current.dump"]
    assert not (output / "db_backup_20260802.sql.gz").exists()
    assert commands[0][0] == "pg_dump"
    assert "--format=custom" in commands[0]
    assert commands[1] == ["pg_restore", "--list", str(output / ".postgres-current.dump.partial")]
    assert result.backup_format == "postgresql-custom"
    assert result.removed_old_backups == 2
    assert result.sha256 == hashlib.sha256(current.read_bytes()).hexdigest()
