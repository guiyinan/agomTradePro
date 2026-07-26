"""
Celery Tasks for Regime Calculation.

异步任务：Regime 计算、变化通知等。
"""

import math
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, NotRequired, Protocol, TypedDict, TypeVar, cast

from celery import shared_task
from celery.utils.log import get_task_logger

from apps.regime.application.current_regime import resolve_current_regime
from apps.regime.application.repository_provider import get_regime_repository

logger = get_task_logger(__name__)

TaskResult = TypeVar("TaskResult", covariant=True)
DecoratedResult = TypeVar("DecoratedResult")


class _TypedTask(Protocol[TaskResult]):
    """Callable Celery task exposing a typed synchronous runner."""

    def __call__(self, *args: Any, **kwargs: Any) -> TaskResult: ...

    def run(self, *args: Any, **kwargs: Any) -> TaskResult: ...


def _typed_shared_task(
    *decorator_args: object,
    **decorator_kwargs: object,
) -> Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]]:
    """Narrow Celery's untyped decorator while retaining task result types."""

    decorator = shared_task(*decorator_args, **decorator_kwargs)
    return cast(
        Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]],
        decorator,
    )


class RegimeCalculationTaskResult(TypedDict):
    """Serialized result of the Regime calculation task."""

    status: str
    reason: NotRequired[str]
    as_of_date: NotRequired[str]
    dominant_regime: NotRequired[str]
    confidence: NotRequired[float]
    distribution: NotRequired[dict[str, float]]
    growth_z: NotRequired[float | None]
    inflation_z: NotRequired[float | None]
    warnings: NotRequired[list[str]]
    source: NotRequired[str]
    is_fallback: NotRequired[bool]


class RegimeNotificationTaskResult(TypedDict):
    """Serialized result of the Regime change notification task."""

    status: str
    reason: NotRequired[str]
    notified: NotRequired[bool]
    regime: NotRequired[str]
    confidence: NotRequired[float]


class RegimeHealthTaskResult(TypedDict):
    """Serialized health result for the latest Regime snapshot."""

    status: str
    error: NotRequired[str]
    error_code: NotRequired[str]
    health: NotRequired[str]
    latest_date: NotRequired[str]
    days_since: NotRequired[int]
    dominant_regime: NotRequired[str]
    confidence: NotRequired[float]
    is_stale: NotRequired[bool]
    is_low_confidence: NotRequired[bool]


def _parse_task_date(raw: str | None, *, field_name: str) -> date:
    """Return an ISO task date or today's date when the field is omitted."""

    if raw is None:
        return date.today()
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def _require_non_empty_string(payload: Mapping[str, object], field_name: str) -> str:
    """Read one required non-empty string from a dynamic Celery payload."""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_confidence(value: object, *, field_name: str) -> float:
    """Return a finite probability confidence from a task or snapshot boundary."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number between 0 and 1")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{field_name} must be a finite number between 0 and 1")
    return confidence


@_typed_shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=600,
    soft_time_limit=570,
)
def calculate_regime_task(
    _task: object,
    sync_result: Mapping[str, object] | None = None,
    as_of_date: str | None = None,
    use_pit: bool = True,
) -> RegimeCalculationTaskResult:
    """
    计算 Regime 判定任务（可接收 sync 结果）

    可以作为链式任务的一部分，接收 sync_macro_data 的输出。
    如果 sync_result 存在且显示失败，则跳过计算。

    Args:
        sync_result: sync_macro_data 任务的输出
        as_of_date: 分析时点 (YYYY-MM-DD，None 表示今天)
        use_pit: 是否使用 Point-in-Time 数据

    Returns:
        dict: Regime 计算结果
    """
    if not isinstance(use_pit, bool):
        raise ValueError("use_pit must be a boolean")
    if sync_result is not None and "success" in sync_result:
        sync_success = sync_result["success"]
        if not isinstance(sync_success, bool):
            raise ValueError("sync_result.success must be a boolean")
        if not sync_success:
            logger.warning("Previous sync step failed; skipping Regime calculation")
            return {"status": "skipped", "reason": "sync_failed"}

    target_date = _parse_task_date(as_of_date, field_name="as_of_date")
    logger.info(
        "Starting Regime calculation",
        extra={"as_of_date": target_date.isoformat(), "use_pit": use_pit},
    )
    try:
        current = resolve_current_regime(as_of_date=target_date, use_pit=use_pit)
        confidence = _require_confidence(
            current.confidence,
            field_name="resolved confidence",
        )
        logger.info(
            "Regime calculation completed: regime=%s confidence=%.2f",
            current.dominant_regime,
            confidence,
        )
        return {
            "status": "success",
            "as_of_date": target_date.isoformat(),
            "dominant_regime": current.dominant_regime,
            "confidence": confidence,
            "distribution": dict(current.distribution or {}),
            "growth_z": current.growth_momentum_z,
            "inflation_z": current.inflation_momentum_z,
            "warnings": list(current.warnings),
            "source": current.data_source,
            "is_fallback": current.is_fallback,
        }

    except Exception as exc:
        logger.error(
            "Regime calculation failed",
            extra={"exception_type": type(exc).__name__},
        )
        raise


@_typed_shared_task(time_limit=600, soft_time_limit=570)
def notify_regime_change(
    regime_result: Mapping[str, object],
) -> RegimeNotificationTaskResult:
    """
    发送 Regime 变化通知

    当 Regime 发生显著变化时发送通知。

    Args:
        regime_result: calculate_regime_task 的输出

    Returns:
        dict: 通知发送结果
    """
    task_status = regime_result.get("status")
    legacy_success = regime_result.get("success")
    if task_status != "success" and legacy_success is not True:
        logger.info("Regime calculation not successful; skipping notification")
        return {"status": "skipped", "reason": "regime_not_successful"}
    dominant_regime = _require_non_empty_string(regime_result, "dominant_regime")
    as_of_date = _parse_task_date(
        _require_non_empty_string(regime_result, "as_of_date"),
        field_name="as_of_date",
    )
    confidence = _require_confidence(
        regime_result.get("confidence"),
        field_name="confidence",
    )
    logger.info(
        "Checking Regime change for notification: regime=%s",
        dominant_regime,
    )

    try:
        regime_repo = get_regime_repository()
        last_snapshot = regime_repo.get_latest_snapshot(before_date=as_of_date)

        if last_snapshot:
            previous_confidence = _require_confidence(
                last_snapshot.confidence,
                field_name="previous snapshot confidence",
            )
            regime_changed = last_snapshot.dominant_regime != dominant_regime
            confidence_dropped = confidence < previous_confidence * 0.8

            if regime_changed:
                logger.warning(
                    "REGIME CHANGE DETECTED: %s -> %s",
                    last_snapshot.dominant_regime,
                    dominant_regime,
                )

            if confidence_dropped:
                logger.warning(
                    "CONFIDENCE DROPPED: %.2f -> %.2f",
                    previous_confidence,
                    confidence,
                )

        return {
            "status": "success",
            "notified": True,
            "regime": dominant_regime,
            "confidence": confidence,
        }

    except Exception as exc:
        logger.error(
            "Failed to evaluate Regime change notification",
            extra={"exception_type": type(exc).__name__},
        )
        raise


@_typed_shared_task(time_limit=600, soft_time_limit=570)
def check_regime_health() -> RegimeHealthTaskResult:
    """
    检查 Regime 计算健康状态

    定期检查最新的 Regime 计算，发现异常时告警。

    Returns:
        dict: 健康检查结果
    """
    try:
        logger.info("Checking regime calculation health")

        regime_repo = get_regime_repository()
        latest = regime_repo.get_latest_snapshot()

        if not latest:
            return {
                "status": "error",
                "error": "No Regime data available.",
                "error_code": "REGIME_SNAPSHOT_UNAVAILABLE",
            }

        try:
            confidence = _require_confidence(
                latest.confidence,
                field_name="latest snapshot confidence",
            )
        except ValueError:
            logger.error("Latest Regime snapshot has invalid confidence")
            return {
                "status": "error",
                "error": "Latest Regime snapshot is invalid.",
                "error_code": "INVALID_REGIME_SNAPSHOT",
            }

        days_since = (date.today() - latest.observed_at).days
        is_stale = days_since > 7
        is_low_confidence = confidence < 0.2

        health_status = "healthy"
        if is_stale or is_low_confidence:
            health_status = "warning"
            logger.warning(
                "Regime health warning: stale=%s low_confidence=%s",
                is_stale,
                is_low_confidence,
            )

        return {
            "status": "success",
            "health": health_status,
            "latest_date": latest.observed_at.isoformat(),
            "days_since": days_since,
            "dominant_regime": latest.dominant_regime,
            "confidence": confidence,
            "is_stale": is_stale,
            "is_low_confidence": is_low_confidence,
        }

    except Exception as exc:
        logger.error(
            "Regime health check failed",
            extra={"exception_type": type(exc).__name__},
        )
        raise
