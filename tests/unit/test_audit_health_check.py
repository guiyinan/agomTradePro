from __future__ import annotations

from datetime import UTC, datetime

from apps.audit.application.health_check import AuditHealthChecker
from apps.audit.infrastructure.failure_counter import FailureRecord, FailureStats


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


def test_database_health_check_uses_repository_probe():
    repo = _FakeAuditRepository()
    checker = AuditHealthChecker(
        audit_repo=repo,
        failure_counter=_FakeFailureCounter(FailureStats()),
    )

    result = checker._check_database_connection()

    assert result.status == "OK"
    assert result.details["database"] == "test.sqlite3"
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
    assert report.metrics["failure_rate"] == 0.6
