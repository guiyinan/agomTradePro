"""Behavioral contracts for governed Macro Celery entrypoints."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.data_center.application.dtos import SyncResult
from apps.macro.application import tasks


def _sync_response(
    *,
    synced_count: int,
    errors: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        synced_count=synced_count,
        skipped_count=0,
        errors=errors or [],
    )


def _due_indicator(code: str, *, source_type: str = "akshare") -> dict[str, Any]:
    return {
        "indicator": code,
        "reason": "stale",
        "period_type": "M",
        "source_type": source_type,
        "latest_reporting_period": None,
    }


def test_sync_macro_data_rejects_invalid_input_before_use_case(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "build_sync_macro_data_use_case",
        lambda _source: (_ for _ in ()).throw(AssertionError("must not build")),
    )

    result = tasks.sync_macro_data.run(source=1)

    assert result["outcome"] == "failed"
    assert result["requested"] == 0
    assert result["stored"] == 0


def test_sync_macro_data_reports_all_success_with_normalized_counts(monkeypatch) -> None:
    use_case = SimpleNamespace(execute=lambda _request: _sync_response(synced_count=4))
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = tasks.sync_macro_data.run(source="akshare", indicator="CN_PMI")

    assert result["outcome"] == "success"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        1,
        1,
        0,
        1,
    )
    assert result["records_stored"] == 4


def test_sync_macro_data_reports_partial_failure(monkeypatch) -> None:
    use_case = SimpleNamespace(
        execute=lambda _request: _sync_response(
            synced_count=3,
            errors=["failed: CN_CPI"],
        )
    )
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)
    monkeypatch.setattr(tasks, "record_operational_alert", lambda **_kwargs: None)

    result = tasks.sync_macro_data.run(source="akshare")

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["error_count"] == 1
    assert result["records_stored"] == 3


def test_sync_macro_data_reports_zero_output_as_failure(monkeypatch) -> None:
    use_case = SimpleNamespace(execute=lambda _request: _sync_response(synced_count=0))
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = tasks.sync_macro_data.run(source="akshare")

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["error"] == "macro_sync_zero_output"


def test_sync_macro_data_reports_complete_failure(monkeypatch) -> None:
    use_case = SimpleNamespace(
        execute=lambda _request: (_ for _ in ()).throw(OSError("provider down"))
    )
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = tasks.sync_macro_data.run(source="akshare")

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["error"] == "macro_sync_failed"


def test_check_data_freshness_reports_all_success(monkeypatch) -> None:
    governed = [{"indicator_code": "CN_PMI"}, {"indicator_code": "CN_CPI"}]
    monkeypatch.setattr(tasks, "_list_sync_governed_indicators", lambda: governed)
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda supplied: [_due_indicator("CN_PMI")],
    )
    delay = SimpleNamespace(delay=lambda _items: None)
    monkeypatch.setattr(tasks, "send_data_freshness_alert", delay)

    result = tasks.check_data_freshness()

    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 2
    assert result["due_count"] == 1


def test_check_data_freshness_reports_zero_output_as_noop(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "_list_sync_governed_indicators", lambda: [])
    monkeypatch.setattr(tasks, "_collect_due_macro_indicators", lambda supplied: [])

    result = tasks.check_data_freshness()

    assert result["outcome"] == "noop"
    assert result["requested"] == 0
    assert result["all_fresh"] is True


def test_check_data_freshness_reports_complete_failure(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "_list_sync_governed_indicators", lambda: [{}])
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda supplied: (_ for _ in ()).throw(OSError("query failed")),
    )

    result = tasks.check_data_freshness()

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["error"] == "macro_freshness_check_failed"


def test_send_data_freshness_alert_rejects_invalid_input() -> None:
    result = tasks.send_data_freshness_alert("CN_PMI")  # type: ignore[arg-type]

    assert result["outcome"] == "failed"
    assert result["requested"] == 0


def test_send_data_freshness_alert_reports_all_success() -> None:
    result = tasks.send_data_freshness_alert([{"indicator": "CN_PMI", "latest_date": "2026-07-31"}])

    assert result["outcome"] == "success"
    assert result["status"] == "alerted"
    assert result["requested"] == result["succeeded"] == 1


def test_send_data_freshness_alert_reports_zero_output_as_noop() -> None:
    result = tasks.send_data_freshness_alert([])

    assert result["outcome"] == "noop"
    assert result["status"] == "not_needed"


def test_send_data_freshness_alert_reports_complete_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks.logger,
        "warning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("logger failed")),
    )

    result = tasks.send_data_freshness_alert([{"indicator": "CN_PMI"}])

    assert result["outcome"] == "failed"
    assert result["failed"] == 1


def test_auto_sync_due_macro_indicators_rejects_invalid_input(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda: (_ for _ in ()).throw(AssertionError("must not collect")),
    )

    result = tasks.auto_sync_due_macro_indicators(indicator_codes=[])

    assert result["outcome"] == "failed"
    assert result["requested"] == 0


def test_auto_sync_due_macro_indicators_reports_zero_output_as_noop(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "_collect_due_macro_indicators", lambda: [])

    result = tasks.auto_sync_due_macro_indicators()

    assert result["outcome"] == "noop"
    assert result["requested"] == 0


def test_auto_sync_due_macro_indicators_reports_all_success(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda: [_due_indicator("CN_PMI")],
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _source: 7)
    use_case = SimpleNamespace(
        execute=lambda _request: SyncResult(
            domain="macro",
            provider_name="AKShare",
            stored_count=3,
            status="success",
        )
    )
    monkeypatch.setattr(tasks, "make_sync_macro_use_case", lambda: use_case)

    result = tasks.auto_sync_due_macro_indicators()

    assert result["outcome"] == "success"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        1,
        1,
        0,
        1,
    )
    assert result["records_stored"] == 3


def test_auto_sync_due_macro_indicators_reports_partial_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda: [_due_indicator("CN_PMI"), _due_indicator("CN_CPI")],
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _source: 7)
    responses = iter(
        [
            SyncResult(
                domain="macro",
                provider_name="AKShare",
                stored_count=2,
                status="success",
            ),
            OSError("provider failed"),
        ]
    )

    def _execute(_request: object) -> SyncResult:
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        tasks,
        "make_sync_macro_use_case",
        lambda: SimpleNamespace(execute=_execute),
    )

    result = tasks.auto_sync_due_macro_indicators()

    assert result["outcome"] == "partial"
    assert result["succeeded"] == 1
    assert result["failed"] == 1


def test_auto_sync_due_macro_indicators_blocks_without_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda: [_due_indicator("CN_PMI")],
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _source: None)
    monkeypatch.setattr(
        tasks,
        "make_sync_macro_use_case",
        lambda: (_ for _ in ()).throw(AssertionError("must not compose")),
    )

    result = tasks.auto_sync_due_macro_indicators()

    assert result["outcome"] == "blocked"
    assert result["blocked"] == 1
    assert result["stored"] == 0


def test_auto_sync_due_macro_indicators_reports_complete_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda: [_due_indicator("CN_PMI")],
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _source: 7)
    monkeypatch.setattr(
        tasks,
        "make_sync_macro_use_case",
        lambda: SimpleNamespace(
            execute=lambda _request: (_ for _ in ()).throw(OSError("provider failed"))
        ),
    )

    result = tasks.auto_sync_due_macro_indicators()

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["stored"] == 0


def test_auto_sync_due_macro_indicators_rejects_zero_stored_result(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "_collect_due_macro_indicators",
        lambda: [_due_indicator("CN_PMI")],
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _source: 7)
    monkeypatch.setattr(
        tasks,
        "make_sync_macro_use_case",
        lambda: SimpleNamespace(
            execute=lambda _request: SyncResult(
                domain="macro",
                provider_name="AKShare",
                stored_count=0,
                status="success",
            )
        ),
    )

    result = tasks.auto_sync_due_macro_indicators()

    assert result["outcome"] == "failed"
    assert result["sync_runs"][0]["error_message"] == "sync returned zero stored records"


def test_cleanup_old_data_rejects_invalid_input_before_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "get_macro_repository",
        lambda: (_ for _ in ()).throw(AssertionError("must not query")),
    )

    result = tasks.cleanup_old_data(days_to_keep=True)

    assert result["outcome"] == "failed"
    assert result["requested"] == 0


def test_cleanup_old_data_reports_zero_output_as_noop(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "get_macro_repository",
        lambda: SimpleNamespace(count_records_before_date=lambda _cutoff: 0),
    )

    result = tasks.cleanup_old_data()

    assert result["outcome"] == "noop"
    assert result["records_found"] == 0


def test_cleanup_old_data_blocks_when_deletion_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "get_macro_repository",
        lambda: SimpleNamespace(count_records_before_date=lambda _cutoff: 3),
    )

    result = tasks.cleanup_old_data()

    assert result["outcome"] == "blocked"
    assert result["requested"] == result["blocked"] == 3
    assert result["records_deleted"] == 0


def test_cleanup_old_data_reports_complete_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "get_macro_repository",
        lambda: SimpleNamespace(
            count_records_before_date=lambda _cutoff: (_ for _ in ()).throw(
                OSError("database failed")
            )
        ),
    )

    result = tasks.cleanup_old_data()

    assert result["outcome"] == "failed"
    assert result["failed"] == 1


_HIGH_FREQUENCY_TASKS = [
    pytest.param(tasks.sync_high_frequency_bonds, 5, id="bonds"),
    pytest.param(tasks.sync_high_frequency_commodities, 1, id="commodities"),
]


@pytest.mark.parametrize(("task", "requested"), _HIGH_FREQUENCY_TASKS)
def test_high_frequency_tasks_reject_invalid_input(
    monkeypatch,
    task,
    requested: int,
) -> None:
    monkeypatch.setattr(
        tasks,
        "build_sync_macro_data_use_case",
        lambda _source: (_ for _ in ()).throw(AssertionError("must not build")),
    )

    result = task.run(years_back=False)

    assert result["outcome"] == "failed"
    assert result["requested"] == 0


@pytest.mark.parametrize(("task", "requested"), _HIGH_FREQUENCY_TASKS)
def test_high_frequency_tasks_report_all_success(
    monkeypatch,
    task,
    requested: int,
) -> None:
    use_case = SimpleNamespace(execute=lambda _request: _sync_response(synced_count=10))
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = task.run()

    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == result["stored"] == 1
    assert result["indicator_count"] == requested
    assert result["records_stored"] == 10


@pytest.mark.parametrize(("task", "requested"), _HIGH_FREQUENCY_TASKS)
def test_high_frequency_tasks_report_partial_failure(
    monkeypatch,
    task,
    requested: int,
) -> None:
    use_case = SimpleNamespace(
        execute=lambda _request: _sync_response(
            synced_count=4,
            errors=["one indicator failed"],
        )
    )
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = task.run()

    assert result["outcome"] == "partial"
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["records_stored"] == 4


@pytest.mark.parametrize(("task", "requested"), _HIGH_FREQUENCY_TASKS)
def test_high_frequency_tasks_report_zero_output_as_failure(
    monkeypatch,
    task,
    requested: int,
) -> None:
    use_case = SimpleNamespace(execute=lambda _request: _sync_response(synced_count=0))
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = task.run()

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["stored"] == 0


@pytest.mark.parametrize(("task", "requested"), _HIGH_FREQUENCY_TASKS)
def test_high_frequency_tasks_report_complete_failure(
    monkeypatch,
    task,
    requested: int,
) -> None:
    use_case = SimpleNamespace(
        execute=lambda _request: (_ for _ in ()).throw(OSError("provider down"))
    )
    monkeypatch.setattr(tasks, "build_sync_macro_data_use_case", lambda _source: use_case)

    result = task.run()

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["stored"] == 0
