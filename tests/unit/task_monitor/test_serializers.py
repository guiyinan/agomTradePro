"""Typed Task Monitor serializer contracts."""

from apps.task_monitor.application.dtos import (
    HealthCheckResponse,
    TaskAttemptResponse,
    TaskListResponse,
    TaskPhaseResultResponse,
    TaskStatisticsResponse,
    TaskStatusResponse,
    project_task_business_result,
)
from apps.task_monitor.interface.serializers import (
    HealthCheckSerializer,
    TaskListSerializer,
    TaskStatisticsSerializer,
    TaskStatusRequestSerializer,
)


def _task_status() -> TaskStatusResponse:
    """Build one representative Application response DTO."""

    return TaskStatusResponse(
        task_id="task-1",
        task_name="sync_macro_data",
        status="success",
        started_at="2026-07-27T09:00:00+00:00",
        finished_at="2026-07-27T09:00:01+00:00",
        runtime_seconds=1.0,
        retries=0,
        is_success=True,
        is_failure=False,
        outcome="success",
        phase="completed",
        count_unit="sync_operation",
        requested=3,
        succeeded=3,
        failed=0,
        stored=12,
        error_code=None,
        stable_error_code=None,
        trace_id="trace-1",
        phase_results=(
            TaskPhaseResultResponse(
                phase="quote",
                requested=1,
                succeeded=1,
                failed=None,
                stored=12,
            ),
        ),
        business_success=True,
        current_attempt=TaskAttemptResponse(
            task_id="task-1",
            status="success",
            started_at="2026-07-27T09:00:00+00:00",
            finished_at="2026-07-27T09:00:01+00:00",
            retries=0,
            outcome="success",
            phase="completed",
            count_unit="sync_operation",
            requested=3,
            succeeded=3,
            failed=0,
            stored=12,
            error_code=None,
            stable_error_code=None,
            trace_id="trace-1",
            phase_results=(
                TaskPhaseResultResponse(
                    phase="quote",
                    requested=1,
                    succeeded=1,
                    failed=None,
                    stored=12,
                ),
            ),
            business_success=True,
        ),
        last_completed=None,
    )


def test_response_serializers_accept_application_dtos() -> None:
    """Response serializers preserve the DTO contracts emitted by use cases."""

    listed = TaskListSerializer(TaskListResponse(total=1, items=[_task_status()])).data
    health = HealthCheckSerializer(
        HealthCheckResponse(
            is_healthy=True,
            broker_reachable=True,
            backend_reachable=True,
            active_workers=["worker-1"],
            active_tasks_count=1,
            pending_tasks_count=2,
            scheduled_tasks_count=3,
            last_check="2026-07-27T09:00:00+00:00",
        )
    ).data
    statistics = TaskStatisticsSerializer(
        TaskStatisticsResponse(
            task_name="sync_macro_data",
            total_executions=10,
            successful_executions=9,
            failed_executions=1,
            average_runtime=2.5,
            success_rate=0.9,
            last_execution_status="success",
            last_execution_at="2026-07-27T09:00:01+00:00",
        )
    ).data

    assert listed["items"][0]["task_id"] == "task-1"
    assert listed["items"][0]["count_unit"] == "sync_operation"
    assert listed["items"][0]["requested"] == 3
    assert listed["items"][0]["current_attempt"]["stored"] == 12
    assert listed["items"][0]["phase_results"][0]["failed"] is None
    assert listed["items"][0]["business_success"] is True
    assert "exception" not in listed["items"][0]
    assert "traceback" not in listed["items"][0]
    assert health["active_workers"] == ["worker-1"]
    assert statistics["success_rate"] == 0.9


def test_task_status_request_serializer_requires_non_blank_task_id() -> None:
    """The request serializer rejects missing or blank task identities."""

    missing = TaskStatusRequestSerializer(data={})
    blank = TaskStatusRequestSerializer(data={"task_id": ""})
    valid = TaskStatusRequestSerializer(data={"task_id": "task-1"})

    assert missing.is_valid() is False
    assert blank.is_valid() is False
    assert valid.is_valid() is True
    assert valid.validated_data == {"task_id": "task-1"}


def test_business_projection_preserves_phase_evidence_without_fabricating_counts() -> None:
    """Persisted business evidence survives projection with safe unknown values."""

    projection = project_task_business_result(
        '{"outcome":"partial","phase":"publication",'
        '"requested":57,"succeeded":56,"failed":1,"stored":11114,'
        '"count_unit":"sync_operation","stored_count_unit":"fact_row",'
        '"target_trade_date":"2026-09-24",'
        '"phase_results":[{"phase":"quote","requested":2,"succeeded":2},'
        '{"phase":"publication","requested":1,"succeeded":0,"failed":1}],'
        '"errors":["ValueError"],"trace_id":"trace-1"}'
    )

    assert projection.outcome == "partial"
    assert projection.business_success is False
    assert projection.phase == "publication"
    assert projection.requested == 57
    assert projection.succeeded == 56
    assert projection.failed == 1
    assert projection.stored == 11114
    assert projection.count_unit == "sync_operation"
    assert projection.stored_count_unit == "fact_row"
    assert projection.target_trade_date == "2026-09-24"
    assert projection.stable_error_code == "ValueError"
    assert projection.trace_id == "trace-1"
    assert projection.phase_results is not None
    assert projection.phase_results[0].failed is None

    unknown = project_task_business_result(
        '{"outcome":"not-a-contract-value","requested":-1,"stored":"unknown"}'
    )
    assert unknown.outcome is None
    assert unknown.requested is None
    assert unknown.stored is None
    assert unknown.business_success is None


def test_projection_preserves_lowercase_business_codes_and_rejects_diagnostic_text() -> None:
    import json

    for code in (
        "canonical_publication_stale",
        "decision_runtime_blocked",
        "qlib_source_data_stale",
    ):
        projection = project_task_business_result(
            json.dumps({"outcome": "blocked", "errors": [code]})
        )
        assert projection.stable_error_code == code
        assert projection.business_success is False
    for message in (
        "https://provider.test?token=secret",
        "request failed: password=secret",
        "x" * 200,
    ):
        projection = project_task_business_result(json.dumps({"error_code": message}))
        assert projection.error_code is None
        assert projection.stable_error_code is None
