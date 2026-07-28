"""Safety contracts for Alpha/Qlib operational query services."""

from datetime import UTC, datetime

import pytest

from apps.alpha.application import ops_services
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)


def test_task_result_projection_redacts_secrets_and_exception_details() -> None:
    result = ops_services._serialize_task_result(
        "{'summary': {'stock_count': 3}, 'api_token': 'secret-token', "
        "'error': 'postgresql://user:pass@host/db', "
        "'runtime_refresh_error': 'password=another-secret'}"
    )

    assert result == {
        "summary": {"stock_count": 3},
        "api_token": "***",
        "error": "operation_failed",
        "runtime_refresh_error": "operation_failed",
    }


@pytest.mark.parametrize("raw_value", ["plain secret text", "['not', 'a', 'mapping']"])
def test_task_result_projection_rejects_unstructured_payload(raw_value: str) -> None:
    assert ops_services._serialize_task_result(raw_value) == "task_result_unavailable"


def test_recent_task_projection_does_not_publish_stored_exception(monkeypatch) -> None:
    record = TaskExecutionRecord(
        task_id="failed-task-1",
        task_name=ops_services.INFERENCE_TASK_NAMES[0],
        status=TaskStatus.FAILURE,
        args=(),
        kwargs={},
        started_at=datetime(2026, 7, 28, tzinfo=UTC),
        finished_at=datetime(2026, 7, 28, 0, 1, tzinfo=UTC),
        result="{'access_token': 'secret-token'}",
        exception="database password=secret-password",
        traceback=None,
        runtime_seconds=60.0,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue="alpha",
        worker="worker-1",
    )

    class FakeTaskRepository:
        def list_by_task_name(
            self,
            task_name: str,
            limit: int = 100,
            status: str | None = None,
        ) -> list[TaskExecutionRecord]:
            return [record] if task_name == record.task_name else []

    monkeypatch.setattr(
        ops_services,
        "get_task_record_repository",
        FakeTaskRepository,
    )

    rows = ops_services.AlphaOpsOverviewQueryService()._list_recent_tasks(
        ops_services.INFERENCE_TASK_NAMES,
        limit=12,
    )

    assert rows[0]["exception"] == "task_failed"
    assert rows[0]["result"] == {"access_token": "***"}


def test_celery_health_failure_is_redacted(monkeypatch, caplog) -> None:
    class FailingHealthChecker:
        def check_health(self) -> None:
            raise RuntimeError("redis://user:secret-password@host/0")

    monkeypatch.setattr(
        ops_services,
        "get_celery_health_checker",
        FailingHealthChecker,
    )

    health = ops_services.AlphaOpsOverviewQueryService()._get_celery_health()

    assert health["error"] == "celery_health_check_failed"
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"


@pytest.mark.parametrize("provider_uri", [None, 42, "", "bad\npath", "x" * 4_097])
def test_refresh_rejects_invalid_provider_uri_without_builder(
    monkeypatch,
    provider_uri: object,
) -> None:
    service = ops_services.QlibRuntimeDataRefreshService()
    monkeypatch.setattr(
        service,
        "get_runtime_config",
        lambda: {"enabled": True, "provider_uri": provider_uri},
    )

    class UnexpectedBuilder:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("builder must not receive an invalid provider URI")

    monkeypatch.setattr(ops_services, "TushareQlibBuilder", UnexpectedBuilder)

    result = service.refresh_universes(target_date=datetime(2026, 7, 28, tzinfo=UTC).date())

    assert result == {"status": "skipped", "reason": "qlib_provider_uri_invalid"}


def test_qlib_overview_rejects_invalid_provider_uri_without_inspection(monkeypatch) -> None:
    monkeypatch.setattr(
        ops_services,
        "get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": {"unexpected": "mapping"}},
    )
    monkeypatch.setattr(
        ops_services,
        "inspect_latest_trade_date",
        lambda _provider_uri: pytest.fail("invalid provider URI must not reach inspection"),
    )
    monkeypatch.setattr(
        ops_services.AlphaOpsOverviewQueryService,
        "_list_recent_tasks",
        lambda _self, _task_names, limit: [],
    )

    overview = ops_services.QlibDataOpsOverviewQueryService().build()

    assert overview["local_data_status"]["local_data_error"] == "qlib_provider_uri_invalid"


def test_qlib_inspection_failure_is_redacted(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        ops_services,
        "get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": "C:/qlib/data"},
    )

    def fail_inspection(_provider_uri: str) -> None:
        raise RuntimeError("database password=secret-password")

    monkeypatch.setattr(ops_services, "inspect_latest_trade_date", fail_inspection)
    monkeypatch.setattr(
        ops_services.AlphaOpsOverviewQueryService,
        "_list_recent_tasks",
        lambda _self, _task_names, limit: [],
    )

    overview = ops_services.QlibDataOpsOverviewQueryService().build()

    assert overview["local_data_status"]["local_data_error"] == "qlib_data_inspection_failed"
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"
