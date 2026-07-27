"""Task Monitor retention and SQLite maintenance safety contracts."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import cast

import pytest
from django.utils import timezone

from apps.task_monitor.infrastructure.models import TaskExecutionModel
from apps.task_monitor.infrastructure.repositories import DjangoTaskRecordRepository


@pytest.mark.django_db
@pytest.mark.parametrize("days_to_keep", [0, -1, True, 1.5, "30"])
def test_cleanup_rejects_unsafe_retention_before_mutating_rows(days_to_keep: object) -> None:
    """Malformed retention cannot time out active rows or widen terminal deletion."""

    now = timezone.now()
    pending = TaskExecutionModel.objects.create(
        task_id=f"pending-{days_to_keep}",
        task_name="test.retention",
        status="pending",
        args=[],
        kwargs={},
    )
    success = TaskExecutionModel.objects.create(
        task_id=f"success-{days_to_keep}",
        task_name="test.retention",
        status="success",
        args=[],
        kwargs={},
    )
    TaskExecutionModel.objects.filter(pk__in=[pending.pk, success.pk]).update(
        created_at=now - timedelta(days=60)
    )

    with pytest.raises(ValueError, match="positive integer"):
        DjangoTaskRecordRepository().cleanup_old_records(cast(int, days_to_keep))

    pending.refresh_from_db()
    assert pending.status == "pending"
    assert TaskExecutionModel.objects.filter(pk=success.pk).exists()


def test_fresh_backup_check_requires_nonempty_sqlite_artifact(tmp_path, settings) -> None:
    """VACUUM evidence excludes empty, temporary, and non-SQLite backup files."""

    settings.BASE_DIR = tmp_path
    backup_dir = tmp_path / "backups" / "database"
    backup_dir.mkdir(parents=True)
    now = timezone.now()
    zero_backup = backup_dir / "db_backup_zero.sqlite3"
    zero_backup.touch()
    sql_backup = backup_dir / "db_backup_postgres.sql"
    sql_backup.write_text("SELECT 1;", encoding="utf-8")
    temporary = backup_dir / "db_backup_partial.sqlite3.tmp"
    temporary.write_bytes(b"partial")

    assert DjangoTaskRecordRepository._has_fresh_database_backup(now) is False

    sqlite_backup = backup_dir / "db_backup_verified.sqlite3.gz"
    sqlite_backup.write_bytes(b"verified-backup")
    assert DjangoTaskRecordRepository._has_fresh_database_backup(now) is True

    old_timestamp = (now - timedelta(hours=27)).timestamp()
    os.utime(sqlite_backup, (old_timestamp, old_timestamp))
    assert DjangoTaskRecordRepository._has_fresh_database_backup(now) is False
