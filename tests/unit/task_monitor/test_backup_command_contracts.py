"""Database backup command success and failure contracts."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.task_monitor.management.commands import backup_database


@pytest.fixture(autouse=True)
def _stub_healthy_backup_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep command service contracts independent from Config Center storage."""
    monkeypatch.setattr(
        backup_database,
        "require_backup_capacity",
        lambda: {"state": "healthy", "reason": "within_active_policy"},
    )


def test_backup_database_command_reports_artifact_and_cleanup(monkeypatch) -> None:
    """Successful backups publish the exact artifact and retention cleanup count."""
    service = SimpleNamespace(
        backup_database=lambda **kwargs: SimpleNamespace(
            backup_file="/backups/db.dump",
            keep_days=7,
            compressed=True,
            removed_old_backups=2,
        )
    )
    monkeypatch.setattr(
        backup_database,
        "get_database_backup_service",
        lambda: service,
    )
    output = StringIO()
    backup_database.Command(stdout=output).handle(
        output="/backups",
        keep=7,
        compress=True,
    )
    assert "Database backup created: /backups/db.dump" in output.getvalue()
    assert "Cleaned up 2 old backup(s)" in output.getvalue()


def test_backup_database_command_maps_expected_operational_failures(monkeypatch) -> None:
    """Known filesystem and database-tool failures become actionable CommandError."""

    class _Service:
        def backup_database(self, **kwargs: object):
            raise FileNotFoundError("pg_dump missing")

    monkeypatch.setattr(
        backup_database,
        "get_database_backup_service",
        lambda: _Service(),
    )
    with pytest.raises(CommandError, match="pg_dump missing"):
        backup_database.Command(stdout=StringIO()).handle(
            output=None,
            keep=14,
            compress=False,
        )
