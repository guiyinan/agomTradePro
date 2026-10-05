"""
Task Monitor Application Tasks

Celery 任务钩子和装饰器，用于自动记录任务执行状态。
"""

import json
import logging
import re
from collections.abc import Mapping, MutableMapping
from typing import Any
from uuid import uuid4

from celery import Task
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_revoked,
)
from django.utils import timezone

from apps.operational_readiness.application.tasks import (
    execute_personal_readiness_daily_task,
)
from apps.operational_readiness.management.commands.run_personal_readiness_daily import (
    run_personal_readiness_daily,
)
from apps.task_monitor.application.backup_tasks import backup_database_task as backup_database_task
from apps.task_monitor.application.backup_tasks import verify_backup_task as verify_backup_task
from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.domain.interfaces import TaskRecordRepositoryProtocol
from shared.config.secrets import get_secrets
from shared.domain.task_outcomes import (
    TaskBusinessOutcome,
    resolve_task_business_outcome,
    task_business_failure_message,
)
from shared.infrastructure.alert_service import create_default_alert_service

logger = logging.getLogger(__name__)

# 全局仓储实例
_repository: TaskRecordRepositoryProtocol | None = None
_TERMINAL_TASK_STATUSES = {
    TaskStatus.SUCCESS,
    TaskStatus.FAILURE,
    TaskStatus.REVOKED,
    TaskStatus.TIMEOUT,
}
_DUPLICATE_DELIVERY_CODE = "TASK_DUPLICATE_DELIVERY"
_MAX_TASK_RESULT_LENGTH = 10_000
_MAX_PROJECTED_PHASE_RESULTS = 20
_MAX_PROJECTED_PUBLICATION_ITEMS = 3
_RESULT_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}$")
_RESULT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _request_value(request: Any, key: str, default: Any = None) -> Any:
    """Read a Celery request value from Context or test mapping boundaries."""

    if isinstance(request, Mapping):
        return request.get(key, default)
    return getattr(request, key, default)


def _task_request(task: Task) -> Any:
    """Return the request object without trusting third-party shape details."""

    return getattr(task, "request", None)


def _task_attempt_id(task: Task | None) -> str | None:
    """Read the monitor attempt marker attached during task_prerun."""

    if task is None:
        return None
    value = _request_value(_task_request(task), "_task_monitor_attempt_id")
    return value if isinstance(value, str) and value else None


def _set_task_attempt_id(task: Task, attempt_id: str) -> None:
    """Attach an attempt marker to a Celery request for later signal guards."""

    request = _task_request(task)
    if isinstance(request, MutableMapping):
        try:
            request["_task_monitor_attempt_id"] = attempt_id
            return
        except TypeError:
            return
    try:
        request._task_monitor_attempt_id = attempt_id
    except (AttributeError, TypeError):
        return


def _task_retries(task: Task) -> int:
    """Return the Celery retry ordinal, rejecting malformed request input."""

    value = _request_value(_task_request(task), "retries", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return int(value)


def _task_queue_and_worker(task: Task) -> tuple[str | None, str | None]:
    """Extract bounded routing metadata from a Celery request."""

    request = _task_request(task)
    delivery_info = _request_value(request, "delivery_info", {})
    queue = delivery_info.get("routing_key") if isinstance(delivery_info, Mapping) else None
    worker = _request_value(request, "hostname")
    return (
        queue if isinstance(queue, str) else None,
        worker if isinstance(worker, str) else None,
    )


def get_repository() -> TaskRecordRepositoryProtocol:
    """获取仓储实例（延迟初始化）"""
    global _repository
    if _repository is None:
        _repository = get_task_record_repository()
    return _repository


def get_use_case() -> RecordTaskExecutionUseCase:
    """获取用例实例（带告警功能）"""
    # 创建告警服务
    secrets = get_secrets()
    alert_service = create_default_alert_service(
        slack_webhook=secrets.slack_webhook,
        use_console=True,
    )

    return RecordTaskExecutionUseCase(
        repository=get_repository(),
        alert_channels=[alert_service],
    )


def _resolve_terminal_status(*, state: str | None, retval: Any) -> TaskStatus:
    """Resolve technical state together with a task's normalized business outcome."""

    if state == "FAILURE":
        return TaskStatus.FAILURE
    if state == "REVOKED":
        return TaskStatus.REVOKED
    if state == "RETRY":
        return TaskStatus.RETRY
    if resolve_task_business_outcome(retval) is TaskBusinessOutcome.FAILED:
        return TaskStatus.FAILURE
    return TaskStatus.SUCCESS


def _safe_result_text(value: Any, *, limit: int = 128) -> str | None:
    """Keep only short machine-readable tokens from a task result."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if len(normalized) > limit or not _RESULT_TOKEN.fullmatch(normalized):
        return None
    return normalized


def _safe_result_count(value: Any) -> int | None:
    """Keep non-negative integral result counts with a bounded representation."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    if len(str(value)) > 20:
        return None
    return int(value)


def _project_phase_result(value: Any) -> dict[str, object] | None:
    """Retain the bounded counters used by Task Monitor's phase projection."""

    if not isinstance(value, Mapping):
        return None
    projected: dict[str, object] = {}
    phase = _safe_result_text(value.get("phase"), limit=24)
    if phase is not None:
        projected["phase"] = phase
    for key in ("requested", "succeeded", "failed", "stored"):
        count = _safe_result_count(value.get(key))
        if count is not None:
            projected[key] = count
    for key in ("count_unit", "stored_count_unit"):
        unit = _safe_result_text(value.get(key), limit=24)
        if unit is not None:
            projected[key] = unit
    return projected or None


def _project_publication_dataset(value: Any) -> dict[str, object] | None:
    """Retain publication identity and summary scalars without nested evidence."""

    if not isinstance(value, Mapping):
        return None
    projected: dict[str, object] = {}
    text_limits = {
        "dataset_key": 32,
        "publication_id": 64,
        "publication_hash": 64,
        "outcome": 16,
        "as_of": 32,
        "published_at": 32,
        "run_id": 64,
        "publication_run_id": 64,
    }
    for key, limit in text_limits.items():
        text_value = _safe_result_text(value.get(key), limit=limit)
        if text_value is not None:
            projected[key] = text_value
    policy_identity = _safe_result_text(
        value.get("policy_identity") or value.get("policy_version"), limit=64
    )
    policy_version = _safe_result_text(
        value.get("policy_version") or value.get("policy_identity"), limit=64
    )
    if policy_identity is not None:
        projected["policy_identity"] = policy_identity
    if policy_version is not None:
        projected["policy_version"] = policy_version
    for key in (
        "member_count",
        "requested_asset_count",
        "covered_asset_count",
        "missing_asset_count",
    ):
        count = _safe_result_count(value.get(key))
        if count is not None:
            projected[key] = count
    return projected or None


def _bounded_business_result(retval: Mapping[str, Any]) -> str:
    """Serialize a canonical bounded business projection of a large mapping."""

    projected: dict[str, object] = {"result_projection": "bounded_business_fields"}
    outcome = _safe_result_text(retval.get("outcome"), limit=16)
    if outcome in {"success", "partial", "noop", "blocked", "failed"}:
        projected["outcome"] = outcome
    for key in ("success", "partial_success", "publication_updated", "must_not_use_for_decision"):
        value = retval.get(key)
        if isinstance(value, bool):
            projected[key] = value
    for key in (
        "requested",
        "succeeded",
        "failed",
        "stored",
        "published",
        "published_members",
        "publication_members",
        "operation_requested",
        "operation_succeeded",
        "operation_failed",
    ):
        count = _safe_result_count(retval.get(key))
        if count is not None:
            projected[key] = count
    for key in (
        "phase",
        "current_phase",
        "count_unit",
        "stored_count_unit",
        "error_code",
        "stable_error_code",
        "blocked_reason",
        "trace_id",
        "publication_run_id",
        "run_id",
        "quote_source",
        "valuation_source",
        "valuation_policy_identity",
    ):
        value = _safe_result_text(retval.get(key))
        if value is not None:
            projected[key] = value
    trade_date = retval.get("target_trade_date")
    if isinstance(trade_date, str) and _RESULT_DATE.fullmatch(trade_date):
        projected["target_trade_date"] = trade_date
    raw_phase_results = retval.get("phase_results")
    if isinstance(raw_phase_results, (list, tuple)):
        phase_results = [
            normalized
            for item in raw_phase_results[:_MAX_PROJECTED_PHASE_RESULTS]
            if (normalized := _project_phase_result(item)) is not None
        ]
        projected["phase_results"] = phase_results
    raw_publication_ids = retval.get("publication_ids")
    if isinstance(raw_publication_ids, (list, tuple)):
        publication_ids = [
            publication_id
            for item in raw_publication_ids[:_MAX_PROJECTED_PUBLICATION_ITEMS]
            if (publication_id := _safe_result_text(item, limit=128)) is not None
        ]
        projected["publication_ids"] = publication_ids
    raw_datasets = retval.get("datasets")
    if isinstance(raw_datasets, (list, tuple)):
        datasets = [
            dataset
            for item in raw_datasets[:_MAX_PROJECTED_PUBLICATION_ITEMS]
            if (dataset := _project_publication_dataset(item)) is not None
        ]
        projected["datasets"] = datasets
    serialized = json.dumps(projected, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) <= _MAX_TASK_RESULT_LENGTH:
        return serialized

    essential_keys = (
        "result_projection",
        "outcome",
        "success",
        "requested",
        "succeeded",
        "failed",
        "stored",
        "phase",
        "current_phase",
        "count_unit",
        "stored_count_unit",
        "target_trade_date",
        "error_code",
        "stable_error_code",
        "blocked_reason",
        "publication_updated",
        "publication_run_id",
        "phase_results",
        "publication_ids",
        "datasets",
    )
    essential = {key: projected[key] for key in essential_keys if key in projected}
    raw_essential_datasets = essential.get("datasets")
    if isinstance(raw_essential_datasets, list):
        essential["datasets"] = [
            {
                key: dataset[key]
                for key in (
                    "dataset_key",
                    "publication_id",
                    "publication_hash",
                    "member_count",
                    "policy_identity",
                    "policy_version",
                    "as_of",
                    "published_at",
                    "run_id",
                    "publication_run_id",
                )
                if key in dataset
            }
            for dataset in raw_essential_datasets
            if isinstance(dataset, dict)
        ]
    serialized = json.dumps(essential, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > _MAX_TASK_RESULT_LENGTH:
        # The fixed caps above make this unreachable; keep the monitor signal bounded if the
        # projection contract is extended without updating those caps.
        return json.dumps(
            {
                key: projected[key]
                for key in (
                    "outcome",
                    "requested",
                    "succeeded",
                    "failed",
                    "stored",
                    "phase",
                    "error_code",
                    "blocked_reason",
                    "publication_updated",
                    "publication_run_id",
                )
                if key in projected
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    return serialized


def _serialize_task_result(retval: Any) -> str:
    """Keep ordinary results intact and safely project results above the storage bound."""

    try:
        rendered = str(retval)
    except Exception:
        return "<unserializable result>"
    if len(rendered) <= _MAX_TASK_RESULT_LENGTH:
        return rendered
    if isinstance(retval, Mapping):
        return _bounded_business_result(retval)
    return json.dumps(
        {"result_projection": "oversized_non_mapping_omitted"},
        sort_keys=True,
        separators=(",", ":"),
    )


# ========== Celery 信号处理 ==========


@task_prerun.connect  # type: ignore[misc]
def task_prerun_handler(
    sender: Any = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **kwds: Any,
) -> None:
    """任务开始前记录"""
    if not task_id or not task:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)
        retries = _task_retries(task)
        existing_attempt_id = existing.attempt_id if existing is not None else None
        request_attempt_id = _task_attempt_id(task)

        if existing is not None and existing.status in _TERMINAL_TASK_STATUSES:
            attempt_id = request_attempt_id or uuid4().hex
            _set_task_attempt_id(task, attempt_id)
            logger.warning(
                "task_delivery_duplicate_detected code=%s task_id=%s status=%s",
                _DUPLICATE_DELIVERY_CODE,
                task_id,
                existing.status.value,
            )
            return

        if (
            existing is not None
            and existing.status is TaskStatus.STARTED
            and retries <= existing.retries
            and request_attempt_id != existing_attempt_id
        ):
            attempt_id = request_attempt_id or uuid4().hex
            _set_task_attempt_id(task, attempt_id)
            logger.warning(
                "task_delivery_duplicate_detected code=%s task_id=%s status=%s",
                _DUPLICATE_DELIVERY_CODE,
                task_id,
                existing.status.value,
            )
            return

        is_retry_attempt = existing is not None and existing.status is TaskStatus.RETRY
        attempt_id = uuid4().hex if is_retry_attempt else request_attempt_id or uuid4().hex
        _set_task_attempt_id(task, attempt_id)
        queue, worker = _task_queue_and_worker(task)
        started_at = (
            existing.started_at
            if existing is not None and existing.status in {TaskStatus.STARTED, TaskStatus.RETRY}
            else timezone.now()
        )
        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=task.name,
            status=TaskStatus.STARTED,
            args=args or (),
            kwargs=kwargs or {},
            started_at=started_at,
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=max(retries, existing.retries if existing is not None else 0),
            priority=TaskPriority.NORMAL,
            queue=queue,
            worker=worker,
            attempt_id=attempt_id,
        )

        use_case = get_use_case()
        use_case.execute(record)

    except Exception as exc:
        logger.error(
            "Failed to record task start: error_type=%s",
            exc.__class__.__name__,
        )


@task_postrun.connect  # type: ignore[misc]
def task_postrun_handler(
    sender: Any = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    retval: Any | None = None,
    state: str | None = None,
    **kwds: Any,
) -> None:
    """任务完成后记录"""
    if not task_id or not task:
        return

    try:
        # 获取之前的记录
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        attempt_id = _task_attempt_id(task)
        if existing.attempt_id is not None and attempt_id != existing.attempt_id:
            logger.warning(
                "task_signal_ignored code=%s task_id=%s signal=postrun",
                _DUPLICATE_DELIVERY_CODE,
                task_id,
            )
            return

        # 同时读取 Celery 技术状态和规范化业务 outcome。
        status = _resolve_terminal_status(state=state, retval=retval)
        if status is TaskStatus.RETRY:
            return
        business_failure = task_business_failure_message(retval)

        # 计算运行时长
        runtime_seconds = None
        if existing.started_at:
            runtime_seconds = (timezone.now() - existing.started_at).total_seconds()

        # 序列化结果
        result = None
        if retval is not None:
            result = _serialize_task_result(retval)

        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=task.name,
            status=status,
            args=args or existing.args,
            kwargs=kwargs or existing.kwargs,
            started_at=existing.started_at,
            finished_at=timezone.now(),
            result=result,
            exception=business_failure,
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
            attempt_id=attempt_id or existing.attempt_id,
        )

        use_case = get_use_case()
        if attempt_id:
            use_case.execute(record, expected_attempt_id=attempt_id)
        else:
            use_case.execute(record)

    except Exception as exc:
        logger.error(
            "Failed to record task completion: error_type=%s",
            exc.__class__.__name__,
        )


@task_failure.connect  # type: ignore[misc]
def task_failure_handler(
    sender: Any = None,
    task_id: str | None = None,
    exception: Exception | None = None,
    traceback: str | None = None,
    einfo: Any | None = None,
    **kwds: Any,
) -> None:
    """任务失败记录"""
    if not task_id:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        signal_task = sender if sender is not None else None
        attempt_id = _task_attempt_id(signal_task)
        if sender is None and existing.attempt_id is not None:
            attempt_id = existing.attempt_id
        if existing.attempt_id is not None and attempt_id != existing.attempt_id:
            logger.warning(
                "task_signal_ignored code=%s task_id=%s signal=failure",
                _DUPLICATE_DELIVERY_CODE,
                task_id,
            )
            return

        # 计算运行时长
        runtime_seconds = None
        if existing.started_at:
            runtime_seconds = (timezone.now() - existing.started_at).total_seconds()

        # 获取异常信息
        exception_str = None
        if einfo:
            captured_exception = getattr(einfo, "exception", None)
            exception_str = (
                captured_exception.__class__.__name__
                if captured_exception is not None
                else "TaskFailure"
            )
        elif exception:
            exception_str = exception.__class__.__name__

        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=existing.task_name,
            status=TaskStatus.FAILURE,
            args=existing.args,
            kwargs=existing.kwargs,
            started_at=existing.started_at,
            finished_at=timezone.now(),
            result=None,
            exception=exception_str,
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
            attempt_id=attempt_id or existing.attempt_id,
        )

        use_case = get_use_case()
        if attempt_id:
            use_case.execute(record, expected_attempt_id=attempt_id)
        else:
            use_case.execute(record)

    except Exception as exc:
        logger.error(
            "Failed to record task failure: error_type=%s",
            exc.__class__.__name__,
        )


@task_retry.connect  # type: ignore[misc]
def task_retry_handler(
    sender: Any = None,
    task_id: str | None = None,
    request: Any | None = None,
    reason: str | None = None,
    einfo: Any | None = None,
    **kwds: Any,
) -> None:
    """任务重试记录"""
    if not task_id:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        attempt_id = _task_attempt_id(sender if sender is not None else None)
        if sender is None and existing.attempt_id is not None:
            attempt_id = existing.attempt_id
        if existing.attempt_id is not None and attempt_id != existing.attempt_id:
            logger.warning(
                "task_signal_ignored code=%s task_id=%s signal=retry",
                _DUPLICATE_DELIVERY_CODE,
                task_id,
            )
            return
        retry_value = _request_value(request, "retries", existing.retries + 1)
        retries = (
            retry_value
            if isinstance(retry_value, int) and not isinstance(retry_value, bool)
            else existing.retries + 1
        )

        # 更新重试次数
        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=existing.task_name,
            status=TaskStatus.RETRY,
            args=existing.args,
            kwargs=existing.kwargs,
            started_at=existing.started_at,
            finished_at=None,
            result=None,
            exception=(
                reason.__class__.__name__
                if isinstance(reason, BaseException)
                else "task_retry" if reason else None
            ),
            traceback=None,
            runtime_seconds=None,
            retries=max(existing.retries + 1, retries),
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
            attempt_id=attempt_id or existing.attempt_id,
        )

        if attempt_id:
            repository.save_if_attempt(record, expected_attempt_id=attempt_id)
        else:
            repository.save(record)

    except Exception as exc:
        logger.error(
            "Failed to record task retry: error_type=%s",
            exc.__class__.__name__,
        )


@task_revoked.connect  # type: ignore[misc]
def task_revoked_handler(
    sender: Any = None,
    task_id: str | None = None,
    signum: int | None = None,
    terminated: bool | None = None,
    expired: bool | None = None,
    **kwds: Any,
) -> None:
    """任务撤销记录"""
    if not task_id:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        signal_task = sender if sender is not None else None
        attempt_id = _task_attempt_id(signal_task)
        if sender is None and existing.attempt_id is not None:
            attempt_id = existing.attempt_id
        if existing.attempt_id is not None and attempt_id != existing.attempt_id:
            logger.warning(
                "task_signal_ignored code=%s task_id=%s signal=revoked",
                _DUPLICATE_DELIVERY_CODE,
                task_id,
            )
            return

        # 计算运行时长
        runtime_seconds = None
        if existing.started_at:
            runtime_seconds = (timezone.now() - existing.started_at).total_seconds()

        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=existing.task_name,
            status=TaskStatus.REVOKED,
            args=existing.args,
            kwargs=existing.kwargs,
            started_at=existing.started_at,
            finished_at=timezone.now(),
            result=None,
            exception=f"Task revoked (terminated={terminated}, expired={expired})",
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
            attempt_id=attempt_id or existing.attempt_id,
        )

        if attempt_id:
            repository.save_if_attempt(record, expected_attempt_id=attempt_id)
        else:
            repository.save(record)

    except Exception as exc:
        logger.error(
            "Failed to record task revocation: error_type=%s",
            exc.__class__.__name__,
        )


# ========== Celery 定时清理任务 ==========

from celery import shared_task  # noqa: E402


def _cleanup_old_task_records_result(
    *,
    outcome: str,
    days_to_keep: object,
    deleted_count: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    """Build one normalized cleanup operation result in record-count units."""

    if outcome not in {"success", "noop", "failed"}:
        raise ValueError("invalid task-monitor cleanup outcome")
    completed = outcome in {"success", "noop"}
    payload: dict[str, Any] = {
        "status": "success" if completed else "error",
        "outcome": outcome,
        "success": completed,
        "requested": 1,
        "succeeded": 1 if completed else 0,
        "failed": 1 if outcome == "failed" else 0,
        "stored": 0,
        "deleted_count": deleted_count,
        "days_to_keep": days_to_keep,
    }
    if error is not None:
        payload["error"] = error
    return payload


@shared_task(time_limit=300, soft_time_limit=280)  # type: ignore[misc]
def cleanup_old_task_records(days_to_keep: int = 30) -> dict[str, Any]:
    """
    清理旧的任务记录

    定时任务，清理超过保留期限的任务记录。

    Args:
        days_to_keep: 保留天数（默认 30 天）

    Returns:
        dict: 清理结果
    """
    if type(days_to_keep) is not int or not 1 <= days_to_keep <= 3650:
        return _cleanup_old_task_records_result(
            outcome="failed",
            days_to_keep=days_to_keep,
            error="days_to_keep must be an integer between 1 and 3650",
        )

    try:
        from apps.task_monitor.application.use_cases import CleanupOldRecordsUseCase

        use_case = CleanupOldRecordsUseCase(repository=get_repository())
        count = use_case.execute(days_to_keep=days_to_keep)
        if type(count) is not int or count < 0:
            raise ValueError("cleanup repository returned an invalid deleted count")

        logger.info(f"Cleaned up {count} old task records")

        return _cleanup_old_task_records_result(
            outcome="success" if count else "noop",
            days_to_keep=days_to_keep,
            deleted_count=count,
        )

    except Exception as exc:
        logger.error(
            "Failed to cleanup old task records: error_type=%s",
            exc.__class__.__name__,
        )
        return _cleanup_old_task_records_result(
            outcome="failed",
            days_to_keep=days_to_keep,
            error="cleanup_old_task_records_failed",
        )


@shared_task(  # type: ignore[misc]
    bind=True,
    name="apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
    time_limit=3600,
    soft_time_limit=3300,
)
def run_personal_readiness_daily_task(
    self: Any,
    target_date: str | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    output_dir: str = "var/readiness-evidence",
    required_days: int = 20,
    calendar_source: str = "auto",
    max_qlib_staleness_days: int = 5,
    repair_accounts: bool = False,
    run_workspace_refresh: bool = True,
    include_weekly_advisor: bool = True,
    persist_risk_report: bool = True,
    strict_daily: bool = False,
    allow_unclosed_target_date: bool = False,
    trigger_source: str = "scheduler",
) -> dict[str, Any]:
    """Proxy the legacy task name to the canonical readiness owner."""

    return execute_personal_readiness_daily_task(
        task=self,
        target_date=target_date,
        user_id=user_id,
        account_id=account_id,
        output_dir=output_dir,
        required_days=required_days,
        calendar_source=calendar_source,
        max_qlib_staleness_days=max_qlib_staleness_days,
        repair_accounts=repair_accounts,
        run_workspace_refresh=run_workspace_refresh,
        include_weekly_advisor=include_weekly_advisor,
        persist_risk_report=persist_risk_report,
        strict_daily=strict_daily,
        allow_unclosed_target_date=allow_unclosed_target_date,
        trigger_source=trigger_source,
        runner=run_personal_readiness_daily,
    )
