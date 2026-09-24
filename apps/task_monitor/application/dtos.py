"""Task Monitor Application DTOs and safe business-result projections."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.task_monitor.domain.entities import TaskExecutionRecord


_ALLOWED_OUTCOMES = frozenset({"success", "partial", "noop", "blocked", "failed"})
_SAFE_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_ERROR_CODE = re.compile(
    r"^(?:[A-Z][A-Z0-9]*(?:[_.:-][A-Z0-9]+)*|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)$"
)
_TECHNICAL_ERROR_NAMES = frozenset(
    {
        "DataFetchError",
        "KeyError",
        "OSError",
        "ProviderAssetIdentityError",
        "RuntimeError",
        "TypeError",
        "ValueError",
    }
)


@dataclass(frozen=True)
class TaskPhaseResultResponse:
    """Safe counters for one persisted business phase."""

    phase: str | None
    requested: int | None
    succeeded: int | None
    failed: int | None
    stored: int | None


@dataclass(frozen=True)
class TaskAttemptResponse:
    """Safe public projection of one task attempt's business result."""

    task_id: str
    status: str
    started_at: str | None
    finished_at: str | None
    retries: int
    outcome: str | None = None
    phase: str | None = None
    count_unit: str | None = None
    requested: int | None = None
    succeeded: int | None = None
    failed: int | None = None
    stored: int | None = None
    error_code: str | None = None
    stable_error_code: str | None = None
    trace_id: str | None = None
    stored_count_unit: str | None = None
    target_trade_date: str | None = None
    phase_results: tuple[TaskPhaseResultResponse, ...] | None = None
    business_success: bool | None = None


@dataclass(frozen=True)
class TaskBusinessProjection:
    """Normalized business fields retained from a persisted task result."""

    outcome: str | None
    phase: str | None
    count_unit: str | None
    requested: int | None
    succeeded: int | None
    failed: int | None
    stored: int | None
    error_code: str | None
    stable_error_code: str | None
    trace_id: str | None
    stored_count_unit: str | None
    target_trade_date: str | None
    phase_results: tuple[TaskPhaseResultResponse, ...] | None
    business_success: bool | None


def _result_payload(result: str | None) -> dict[str, object]:
    """Decode JSON or legacy repr task results without raising to API callers."""

    if not result or len(result) > 100_000:
        return {}
    try:
        parsed: object = json.loads(result)
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(result)
        except (ValueError, SyntaxError, RecursionError):
            return {}
    if not isinstance(parsed, Mapping):
        return {}
    return {str(key): value for key, value in parsed.items()}


def _text_value(payload: Mapping[str, object], *keys: str) -> str | None:
    """Return the first non-empty string value under the supplied keys."""

    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_token(value: object) -> str | None:
    """Return a bounded identifier without exposing arbitrary persisted text."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if _SAFE_TOKEN.fullmatch(normalized) else None


def _safe_error_code(value: object) -> str | None:
    """Return a stable code or known exception class, never a raw error message."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if len(normalized) <= 128 and (
        normalized in _TECHNICAL_ERROR_NAMES or _SAFE_ERROR_CODE.fullmatch(normalized)
    ):
        return normalized
    return None


def _safe_trace_id(value: object) -> str | None:
    """Return a bounded trace identifier without accepting arbitrary text."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if _SAFE_TRACE_ID.fullmatch(normalized) else None


def _count_value(payload: Mapping[str, object], key: str) -> int | None:
    """Return an integral business count, keeping unknown values as ``None``."""

    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _phase_result(value: object) -> TaskPhaseResultResponse | None:
    """Normalize one phase counter map while retaining unknown counts as null."""

    if not isinstance(value, Mapping):
        return None
    return TaskPhaseResultResponse(
        phase=_safe_token(value.get("phase")),
        requested=_count_value(value, "requested"),
        succeeded=_count_value(value, "succeeded"),
        failed=_count_value(value, "failed"),
        stored=_count_value(value, "stored"),
    )


def _phase_results(payload: Mapping[str, object]) -> tuple[TaskPhaseResultResponse, ...] | None:
    """Return at most twenty safe phase maps from a persisted result."""

    raw = payload.get("phase_results")
    if not isinstance(raw, (list, tuple)):
        return None
    normalized = tuple(phase for item in raw[:20] if (phase := _phase_result(item)) is not None)
    return normalized


def project_task_business_result(result: str | None) -> TaskBusinessProjection:
    """Project persisted result fields while preserving missing-count semantics."""

    payload = _result_payload(result)
    outcome_candidate = _text_value(payload, "outcome")
    if outcome_candidate is None:
        outcome_candidate = _text_value(payload, "status")
    outcome = (
        outcome_candidate.lower()
        if outcome_candidate is not None and outcome_candidate.lower() in _ALLOWED_OUTCOMES
        else None
    )
    error_code = _safe_error_code(payload.get("error_code"))
    stable_error_code = _safe_error_code(payload.get("stable_error_code")) or error_code
    if stable_error_code is None:
        errors = payload.get("errors")
        if isinstance(errors, (list, tuple)) and errors:
            stable_error_code = _safe_error_code(errors[0])
    trace_id = _safe_trace_id(payload.get("trace_id"))
    trace_value = payload.get("trace")
    if trace_id is None and isinstance(trace_value, Mapping):
        trace_id = _safe_trace_id(
            _text_value(trace_value, "trace_id", "request_id", "correlation_id")
        )
    if trace_id is None:
        trace_id = _safe_trace_id(_text_value(payload, "request_id", "correlation_id"))
    stored_count_unit = _safe_token(payload.get("stored_count_unit"))
    target_trade_date = payload.get("target_trade_date")
    if not isinstance(target_trade_date, str) or not _SAFE_DATE.fullmatch(target_trade_date):
        target_trade_date = None
    business_success = (
        True
        if outcome in {"success", "noop"}
        else False if outcome in {"partial", "blocked", "failed"} else None
    )
    return TaskBusinessProjection(
        outcome=outcome,
        phase=_safe_token(_text_value(payload, "phase", "current_phase")),
        count_unit=_safe_token(payload.get("count_unit")),
        requested=_count_value(payload, "requested"),
        succeeded=_count_value(payload, "succeeded"),
        failed=_count_value(payload, "failed"),
        stored=_count_value(payload, "stored"),
        error_code=error_code,
        stable_error_code=stable_error_code,
        trace_id=trace_id,
        stored_count_unit=stored_count_unit,
        target_trade_date=target_trade_date,
        phase_results=_phase_results(payload),
        business_success=business_success,
    )


def task_attempt_response(
    record: TaskExecutionRecord,
) -> TaskAttemptResponse:
    """Build a safe attempt projection from one domain record."""

    projection = project_task_business_result(record.result)
    return TaskAttemptResponse(
        task_id=record.task_id,
        status=record.status.value,
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        retries=record.retries,
        outcome=projection.outcome,
        phase=projection.phase,
        count_unit=projection.count_unit,
        requested=projection.requested,
        succeeded=projection.succeeded,
        failed=projection.failed,
        stored=projection.stored,
        error_code=projection.error_code,
        stable_error_code=projection.stable_error_code,
        trace_id=projection.trace_id,
        stored_count_unit=projection.stored_count_unit,
        target_trade_date=projection.target_trade_date,
        phase_results=projection.phase_results,
        business_success=projection.business_success,
    )


def task_status_response(
    record: TaskExecutionRecord,
    *,
    current_attempt: TaskAttemptResponse | None = None,
    last_completed: TaskAttemptResponse | None = None,
    include_diagnostics: bool = False,
) -> TaskStatusResponse:
    """Build a public task status projection with optional operator diagnostics."""

    projection = project_task_business_result(record.result)
    return TaskStatusResponse(
        task_id=record.task_id,
        task_name=record.task_name,
        status=record.status.value,
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        runtime_seconds=record.runtime_seconds,
        retries=record.retries,
        is_success=record.status.value == "success",
        is_failure=record.status.value in {"failure", "timeout"},
        outcome=projection.outcome,
        phase=projection.phase,
        count_unit=projection.count_unit,
        requested=projection.requested,
        succeeded=projection.succeeded,
        failed=projection.failed,
        stored=projection.stored,
        error_code=projection.error_code,
        stable_error_code=projection.stable_error_code,
        trace_id=projection.trace_id,
        stored_count_unit=projection.stored_count_unit,
        target_trade_date=projection.target_trade_date,
        phase_results=projection.phase_results,
        business_success=projection.business_success,
        current_attempt=current_attempt,
        last_completed=last_completed,
        exception=record.exception if include_diagnostics else None,
        traceback=record.traceback if include_diagnostics else None,
    )


@dataclass
class TaskStatusResponse:
    """任务状态响应 DTO"""

    task_id: str
    task_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    runtime_seconds: float | None
    retries: int
    is_success: bool
    is_failure: bool
    outcome: str | None = None
    phase: str | None = None
    count_unit: str | None = None
    requested: int | None = None
    succeeded: int | None = None
    failed: int | None = None
    stored: int | None = None
    error_code: str | None = None
    stable_error_code: str | None = None
    trace_id: str | None = None
    stored_count_unit: str | None = None
    target_trade_date: str | None = None
    phase_results: tuple[TaskPhaseResultResponse, ...] | None = None
    business_success: bool | None = None
    current_attempt: TaskAttemptResponse | None = None
    last_completed: TaskAttemptResponse | None = None
    exception: str | None = None
    traceback: str | None = None


@dataclass
class TaskListResponse:
    """任务列表响应 DTO"""

    total: int
    items: list[TaskStatusResponse]


@dataclass
class HealthCheckResponse:
    """健康检查响应 DTO"""

    is_healthy: bool
    broker_reachable: bool
    backend_reachable: bool
    active_workers: list[str]
    active_tasks_count: int
    pending_tasks_count: int
    scheduled_tasks_count: int
    last_check: str


@dataclass
class TaskStatisticsResponse:
    """任务统计响应 DTO"""

    task_name: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_runtime: float
    success_rate: float
    last_execution_status: str
    last_execution_at: str | None


@dataclass
class ScheduledTaskResponse:
    """周期任务行 DTO。"""

    name: str
    task_path: str
    enabled: bool
    schedule_type: str
    schedule_display: str
    queue: str | None
    description: str
    kwargs_preview: str
    last_run_at: str | None
    total_run_count: int
    last_execution_status: str | None
    last_execution_at: str | None
    last_runtime_seconds: float | None
    recent_failure_count: int


@dataclass
class SchedulerSummaryResponse:
    """周期任务摘要 DTO。"""

    total_tasks: int
    enabled_tasks: int
    disabled_tasks: int
    crontab_tasks: int
    interval_tasks: int
    one_off_tasks: int


@dataclass
class SchedulerBootstrapResponse:
    """周期任务初始化响应 DTO。"""

    executed_commands: list[str]
    output_lines: list[str]


@dataclass
class ReadinessScheduleResponse:
    """收市后 readiness 调度响应 DTO。"""

    quote_pre_refresh_time: str
    daily_evidence_time: str
    weekly_auto_advisor_time: str
    quote_pre_refresh_enabled: bool
    daily_evidence_enabled: bool
    weekly_auto_advisor_enabled: bool
    quote_pre_refresh_task_exists: bool
    daily_evidence_task_exists: bool
    weekly_auto_advisor_task_exists: bool
    quote_pre_refresh_day_of_week: str
    daily_evidence_day_of_week: str
    weekly_auto_advisor_day_of_week: str


@dataclass
class ReadinessScheduleUpdateResponse:
    """收市后 readiness 调度更新响应 DTO。"""

    executed_commands: list[str]
    output_lines: list[str]
    quote_pre_refresh_time: str
    daily_evidence_time: str
    weekly_auto_advisor_time: str


@dataclass
class SchedulerConsoleResponse:
    """统一任务后台页面 DTO。"""

    summary: SchedulerSummaryResponse
    health: HealthCheckResponse
    periodic_tasks: list[ScheduledTaskResponse]
    recent_failures: TaskListResponse
