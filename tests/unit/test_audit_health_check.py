from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rest_framework.test import APIRequestFactory

from apps.audit.application import health_check
from apps.audit.application.health_check import AuditHealthChecker
from apps.audit.application.system_audit_outbox_observability import (
    SystemAuditOutboxBacklogSnapshot,
)
from apps.audit.infrastructure.failure_counter import FailureRecord, FailureStats
from apps.audit.interface.views import AuditHealthCheckView


class _FakeAuditRepository:
    def __init__(self, *, total_logs: int = 0, database_health: dict[str, str] | None = None):
        self.total_logs = total_logs
        self.database_health = database_health or {
            "database": "test.sqlite3",
            "engine": "django.db.backends.sqlite3",
        }
        self.database_health_calls = 0

    def get_database_health(self) -> dict[str, str]:
        self.database_health_calls += 1
        return self.database_health

    def count_operation_logs(self) -> int:
        return self.total_logs


class _FakeFailureCounter:
    def __init__(self, stats: FailureStats):
        self._stats = stats

    def get_failure_stats(self) -> FailureStats:
        return self._stats

    def get_failure_count(self) -> int:
        return self._stats.total_count

    def reset(self) -> None:
        self._stats = FailureStats()


class _FakeOutboxReader:
    def __init__(self, snapshot: SystemAuditOutboxBacklogSnapshot):
        self.snapshot = snapshot
        self.calls = 0

    def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
        self.calls += 1
        return SystemAuditOutboxBacklogSnapshot(
            as_of=as_of,
            pending_count=self.snapshot.pending_count,
            due_pending_count=self.snapshot.due_pending_count,
            claimed_count=self.snapshot.claimed_count,
            expired_claimed_count=self.snapshot.expired_claimed_count,
            failed_count=self.snapshot.failed_count,
            delivered_count=self.snapshot.delivered_count,
            oldest_backlog_at=(as_of if self.snapshot.backlog_count else None),
            oldest_claimed_at=(as_of if self.snapshot.claimed_count else None),
        )


def test_database_health_check_uses_repository_probe():
    repo = _FakeAuditRepository()
    checker = AuditHealthChecker(
        audit_repo=repo,
        failure_counter=_FakeFailureCounter(FailureStats()),
    )

    result = checker._check_database_connection()

    assert result.status == "OK"
    assert result.details == {"probe": "passed"}
    assert repo.database_health_calls == 1


def test_check_all_reports_warning_and_metrics_from_injected_dependencies():
    repo = _FakeAuditRepository(total_logs=20)
    stats = FailureStats(
        total_count=12,
        by_component={"database": 12},
        recent_failures=[
            FailureRecord(
                timestamp=datetime.now(UTC),
                component="database",
                reason="timeout",
            )
        ],
    )
    checker = AuditHealthChecker(
        warning_threshold=10,
        error_threshold=50,
        audit_repo=repo,
        failure_counter=_FakeFailureCounter(stats),
    )

    report = checker.check_all()

    assert report.overall_status == "WARNING"
    assert report.metrics["total_operation_logs"] == 20
    assert report.metrics["total_failures"] == 12
    assert report.metrics["failure_rate"] == 0.375
    assert "recent_failures" not in report.checks[0].details


def test_outbox_backlog_health_check_is_read_only_and_warns_for_recovery_work() -> None:
    now = datetime.now(UTC)
    reader = _FakeOutboxReader(
        SystemAuditOutboxBacklogSnapshot(
            as_of=now,
            pending_count=2,
            due_pending_count=1,
            claimed_count=1,
            expired_claimed_count=1,
            failed_count=1,
            delivered_count=3,
            oldest_backlog_at=now,
            oldest_claimed_at=now,
        )
    )
    checker = AuditHealthChecker(
        audit_repo=_FakeAuditRepository(),
        failure_counter=_FakeFailureCounter(FailureStats()),
        outbox_reader=reader,
    )

    result = checker._check_outbox_backlog()

    assert result.component == "audit_outbox_backlog"
    assert result.status == "WARNING"
    assert result.details["expired_claimed_count"] == 1
    assert result.details["failed_count"] == 1
    assert reader.calls == 1


def test_check_all_includes_healthy_outbox_backlog_when_reader_is_injected() -> None:
    now = datetime.now(UTC)
    reader = _FakeOutboxReader(
        SystemAuditOutboxBacklogSnapshot(
            as_of=now,
            pending_count=0,
            due_pending_count=0,
            claimed_count=0,
            expired_claimed_count=0,
            failed_count=0,
            delivered_count=2,
            oldest_backlog_at=None,
            oldest_claimed_at=None,
        )
    )
    checker = AuditHealthChecker(
        audit_repo=_FakeAuditRepository(),
        failure_counter=_FakeFailureCounter(FailureStats()),
        outbox_reader=reader,
    )

    report = checker.check_all()

    outbox_check = next(
        check for check in report.checks if check.component == "audit_outbox_backlog"
    )
    assert outbox_check.status == "OK"
    assert reader.calls == 1


def test_zero_warning_threshold_is_respected() -> None:
    checker = AuditHealthChecker(
        warning_threshold=0,
        error_threshold=2,
        audit_repo=_FakeAuditRepository(),
        failure_counter=_FakeFailureCounter(FailureStats(total_count=1)),
    )

    result = checker._check_failure_counter()

    assert checker.warning_threshold == 0
    assert result.status == "WARNING"


@pytest.mark.parametrize(
    ("warning_threshold", "error_threshold"),
    [
        (-1, 10),
        (True, 10),
        (10, 10),
        (10, 9),
        (10, False),
    ],
)
def test_invalid_health_thresholds_are_rejected(
    warning_threshold: int,
    error_threshold: int,
) -> None:
    with pytest.raises(ValueError):
        AuditHealthChecker(
            warning_threshold=warning_threshold,
            error_threshold=error_threshold,
            audit_repo=_FakeAuditRepository(),
            failure_counter=_FakeFailureCounter(FailureStats()),
        )


def test_database_failure_does_not_expose_exception_message() -> None:
    class FailingRepository(_FakeAuditRepository):
        def get_database_health(self) -> dict[str, str]:
            raise RuntimeError("postgresql://user:secret@internal/db")

    checker = AuditHealthChecker(
        audit_repo=FailingRepository(),
        failure_counter=_FakeFailureCounter(FailureStats()),
    )

    result = checker._check_database_connection()

    assert result.status == "ERROR"
    assert result.message == "Database connection check failed"
    assert result.details == {"error_type": "RuntimeError"}
    assert "secret" not in str(result.to_dict())


def test_metrics_collection_failure_marks_overall_health_error() -> None:
    class IntermittentRepository(_FakeAuditRepository):
        def __init__(self) -> None:
            super().__init__()
            self.count_calls = 0

        def count_operation_logs(self) -> int:
            self.count_calls += 1
            if self.count_calls > 1:
                raise RuntimeError("transient metrics failure")
            return 0

    checker = AuditHealthChecker(
        audit_repo=IntermittentRepository(),
        failure_counter=_FakeFailureCounter(FailureStats()),
    )

    report = checker.check_all()

    assert report.overall_status == "ERROR"
    assert report.metrics == {
        "available": False,
        "error_type": "RuntimeError",
    }
    assert report.checks[-1].component == "audit_metrics"


@pytest.mark.parametrize(
    "query_string",
    [
        "warning_threshold=not-an-int",
        "warning_threshold=-1&error_threshold=5",
        "warning_threshold=10&error_threshold=10",
    ],
)
def test_health_api_rejects_invalid_thresholds(query_string: str) -> None:
    request = APIRequestFactory().get(f"/api/audit/health/?{query_string}")

    response = AuditHealthCheckView.as_view()(request)

    assert response.status_code == 400


def test_public_health_api_exposes_only_safe_probe_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_check,
        "get_audit_repository",
        lambda: _FakeAuditRepository(
            database_health={
                "database": "postgresql://user:secret@internal/db",
                "engine": "private.backend",
            }
        ),
    )
    monkeypatch.setattr(
        health_check,
        "get_audit_failure_counter",
        lambda: _FakeFailureCounter(
            FailureStats(
                total_count=1,
                by_component={"database": 1},
                recent_failures=[
                    FailureRecord(
                        timestamp=datetime.now(UTC),
                        component="database",
                        reason="postgresql://user:secret@internal/db",
                    )
                ],
            )
        ),
    )
    monkeypatch.setattr(
        health_check,
        "get_audit_outbox_repository",
        lambda: _FakeOutboxReader(
            SystemAuditOutboxBacklogSnapshot(
                as_of=datetime.now(UTC),
                pending_count=0,
                due_pending_count=0,
                claimed_count=0,
                expired_claimed_count=0,
                failed_count=0,
                delivered_count=0,
                oldest_backlog_at=None,
                oldest_claimed_at=None,
            )
        ),
    )
    request = APIRequestFactory().get("/api/audit/health/")

    response = AuditHealthCheckView.as_view()(request)

    assert response.status_code == 200
    payload = response.data
    assert "secret" not in str(payload)
    assert payload["checks"][0]["details"] == {
        "total_failures": 1,
        "by_component": {"database": 1},
        "warning_threshold": 10,
        "error_threshold": 50,
    }
    assert payload["checks"][1]["details"] == {"probe": "passed"}
