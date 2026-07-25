from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rest_framework.test import APIRequestFactory

from apps.audit.application import health_check
from apps.audit.application.health_check import AuditHealthChecker
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
