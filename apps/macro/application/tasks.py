"""
Celery Tasks for Macro Data Synchronization.

异步任务：宏观数据同步、数据更新检查等。

重构说明 (2026-03-11):
- 移除对 regime 模块的直接依赖
- regime 相关任务已移至 apps/regime/application/orchestration.py
- 使用 regime 模块的编排函数来协调完整工作流

编排任务请使用:
    from apps.regime.application.orchestration import sync_macro_then_refresh_regime
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger

from apps.data_center.application.dtos import MacroSeriesRequest, SyncMacroRequest, SyncResult
from apps.data_center.application.public import (
    get_active_provider_id_by_source,
    make_query_macro_series_use_case,
    make_sync_macro_use_case,
)
from apps.data_center.composition import (
    get_indicator_catalog_repository,
)
from apps.macro.application.repository_provider import get_macro_repository
from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)
from shared.domain.task_outcomes import TaskBusinessOutcome
from shared.infrastructure.operational_alert_registry import record_operational_alert

logger = get_task_logger(__name__)


def _task_result(
    *,
    outcome: TaskBusinessOutcome,
    requested: int,
    succeeded: int,
    failed: int,
    stored: int,
    count_unit: str,
    blocked: int = 0,
    error: str = "",
    status: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one normalized Celery business-outcome payload."""

    payload: dict[str, Any] = {
        "success": outcome
        in {
            TaskBusinessOutcome.SUCCESS,
            TaskBusinessOutcome.PARTIAL,
            TaskBusinessOutcome.NOOP,
        },
        "outcome": outcome.value,
        "status": status or outcome.value,
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
        "blocked": blocked,
        "count_unit": count_unit,
        "error": error,
    }
    if extra:
        payload.update(extra)
    return payload


def _validated_identifier(value: object, *, field_name: str) -> str:
    """Validate one bounded non-empty task identifier."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        raise ValueError(f"{field_name} must be a non-empty identifier")
    return normalized


def _validated_positive_int(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> int:
    """Validate one positive bounded integer at the Celery boundary."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{field_name} must be between 1 and {maximum}")
    return value


def _validated_indicator_filter(value: object) -> list[str] | None:
    """Validate and normalize the optional auto-sync indicator filter."""

    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("indicator_codes must be a non-empty list of strings")
    normalized: list[str] = []
    for raw_code in value:
        code = _validated_identifier(raw_code, field_name="indicator_code").upper()
        if code not in normalized:
            normalized.append(code)
    return normalized


def _is_enabled_flag(value: Any) -> bool:
    """Return True when a catalog metadata flag is enabled."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _default_refresh_start(period_type: str, *, today: date) -> date:
    """Return a generic default backfill window by period type."""

    normalized_period_type = (period_type or "").upper()
    if normalized_period_type == "D":
        return today - timedelta(days=365 * 2)
    if normalized_period_type == "W":
        return today - timedelta(days=365 * 5)
    return date(2010, 1, 1)


def _suggest_refresh_start(
    *,
    period_type: str,
    latest_reporting_period: date | None,
    today: date,
) -> date:
    """Return a pragmatic backfill window for an auto-sync refresh."""

    if latest_reporting_period is None:
        return _default_refresh_start(period_type, today=today)

    normalized_period_type = (period_type or "").upper()
    if normalized_period_type == "D":
        overlap_days = 30
    elif normalized_period_type == "W":
        overlap_days = 90
    else:
        overlap_days = 365
    suggested = latest_reporting_period - timedelta(days=overlap_days)
    return max(suggested, _default_refresh_start(period_type, today=today))


def _list_sync_governed_indicators() -> list[dict[str, str]]:
    """Return active indicators that are configured for automatic macro sync."""

    catalog_repo = get_indicator_catalog_repository()
    indicators: list[dict[str, str]] = []
    for catalog in sorted(catalog_repo.list_active(), key=lambda item: item.code):
        extra = dict(catalog.extra or {})
        if not _is_enabled_flag(extra.get("governance_sync_supported")):
            continue
        source_type = str(extra.get("governance_sync_source_type") or "").strip()
        if not source_type:
            logger.warning(
                "Skipping governed auto-sync indicator without source_type: %s",
                catalog.code,
            )
            continue
        indicators.append(
            {
                "indicator_code": catalog.code,
                "period_type": catalog.default_period_type,
                "source_type": source_type,
            }
        )
    return indicators


def _collect_due_macro_indicators(
    governed_indicators: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return governed sync-supported indicators whose data is missing or stale."""

    query_use_case = make_query_macro_series_use_case()
    today = date.today()
    due_items: list[dict[str, Any]] = []

    for item in (
        governed_indicators if governed_indicators is not None else _list_sync_governed_indicators()
    ):
        response = query_use_case.execute(
            MacroSeriesRequest(
                indicator_code=item["indicator_code"],
                end=today,
                limit=1,
            )
        )
        latest = response.data[0] if response.data else None
        reason = ""
        if response.total == 0:
            reason = "missing"
        elif response.freshness_status == "stale" or response.decision_grade == "degraded":
            reason = "stale"
        if not reason:
            continue

        due_items.append(
            {
                "indicator": item["indicator_code"],
                "reason": reason,
                "period_type": item["period_type"],
                "source_type": item["source_type"],
                "freshness_status": response.freshness_status,
                "decision_grade": response.decision_grade,
                "blocked_reason": response.blocked_reason,
                "latest_reporting_period": response.latest_reporting_period,
                "latest_published_at": response.latest_published_at,
                "latest_date": (
                    response.latest_reporting_period.isoformat()
                    if response.latest_reporting_period
                    else ""
                ),
                "days_lag": latest.age_days if latest else None,
            }
        )
    return due_items


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def sync_macro_data(
    self: Any, source: str = "akshare", indicator: str | None = None, days_back: int = 1
) -> dict[str, Any]:
    """
    同步宏观数据任务

    定时任务，从 AKShare/Tushare 同步最新的宏观数据。

    Args:
        source: 数据源 ('akshare' 或 'tushare')
        indicator: 指标代码 (None 表示同步所有)
        days_back: 回溯天数

    Returns:
        dict: 同步结果统计
    """
    try:
        normalized_source = _validated_identifier(source, field_name="source")
        validated_days_back = _validated_positive_int(
            days_back,
            field_name="days_back",
            maximum=36_500,
        )
        normalized_indicator = (
            _validated_identifier(indicator, field_name="indicator")
            if indicator is not None
            else None
        )
    except ValueError as exc:
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            count_unit="batch",
            error=str(exc),
            extra={"source": "", "indicator": None, "synced_count": 0},
        )

    try:
        logger.info(
            "Starting macro data sync from %s, indicator=%s, days_back=%s",
            normalized_source,
            normalized_indicator,
            validated_days_back,
        )

        use_case = build_sync_macro_data_use_case(normalized_source)

        # 计算日期范围
        end_date = date.today()
        start_date = end_date - timedelta(days=validated_days_back)

        # 构建请求对象
        request = SyncMacroDataRequest(
            start_date=start_date,
            end_date=end_date,
            indicators=[normalized_indicator] if normalized_indicator else None,
        )

        # 执行同步
        result = use_case.execute(request)

        errors = list(result.errors or [])
        synced_count = int(result.synced_count)
        if synced_count < 0:
            raise ValueError("synced_count cannot be negative")
        outcome = (
            TaskBusinessOutcome.FAILED
            if synced_count == 0
            else (TaskBusinessOutcome.PARTIAL if errors else TaskBusinessOutcome.SUCCESS)
        )
        failed_indicators = []
        for error in errors:
            indicator_code = str(error).rsplit(":", 1)[-1].strip()
            if indicator_code and indicator_code not in failed_indicators:
                failed_indicators.append(indicator_code)

        if outcome is TaskBusinessOutcome.PARTIAL:
            logger.warning(
                "Macro data sync partially completed: synced=%s skipped=%s errors=%s",
                result.synced_count,
                result.skipped_count,
                len(errors),
            )
            record_operational_alert(
                level="warning",
                task_name="apps.macro.application.tasks.sync_macro_data",
                title="Macro data sync partially completed",
                message=(
                    f"Synced {result.synced_count} series with {len(errors)} missing or failed "
                    "indicators."
                ),
                metadata={
                    "source": normalized_source,
                    "error_count": len(errors),
                    "failed_indicators": failed_indicators[:10],
                },
                task_id=getattr(getattr(self, "request", None), "id", "") or "",
            )
        else:
            logger.info("Macro data sync completed: %s", result)

        return _task_result(
            outcome=outcome,
            requested=1,
            succeeded=1 if synced_count > 0 else 0,
            failed=1 if outcome is TaskBusinessOutcome.FAILED else 0,
            stored=1 if synced_count > 0 else 0,
            count_unit="batch",
            error=("macro_sync_zero_output" if synced_count == 0 else ""),
            extra={
                "source": normalized_source,
                "indicator": normalized_indicator,
                "synced_count": synced_count,
                "records_stored": synced_count,
                "skipped_count": int(result.skipped_count),
                "errors": errors,
                "error_count": len(errors),
                "failed_indicators": failed_indicators,
                "degraded": bool(errors),
            },
        )

    except Exception as exc:
        logger.exception("Macro data sync failed")
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=1,
            succeeded=0,
            failed=1,
            stored=0,
            count_unit="batch",
            error="macro_sync_failed",
            extra={
                "source": normalized_source,
                "indicator": normalized_indicator,
                "synced_count": 0,
                "records_stored": 0,
                "errors": [str(exc)],
                "error_count": 1,
                "failed_indicators": [],
                "degraded": True,
            },
        )


# 注意: calculate_regime 任务已移至 apps/regime/application/tasks.py
# 使用 regime 模块的编排函数来协调 macro 同步和 regime 计算


@shared_task(time_limit=300, soft_time_limit=280)  # type: ignore[misc]
def check_data_freshness() -> dict[str, Any]:
    """
    检查数据新鲜度任务

    定时检查所有已配置自动同步的宏观指标，发现缺失或过期时告警。

    Returns:
        dict: 数据新鲜度报告
    """
    governed_indicators: list[dict[str, str]] = []
    try:
        logger.info("Checking data freshness")
        governed_indicators = _list_sync_governed_indicators()
        due_indicators = _collect_due_macro_indicators(governed_indicators)
        stale_indicators = [item for item in due_indicators if item.get("reason") == "stale"]

        if due_indicators:
            send_data_freshness_alert.delay(due_indicators)

        checked_count = len(governed_indicators)
        outcome = TaskBusinessOutcome.SUCCESS if checked_count > 0 else TaskBusinessOutcome.NOOP
        return _task_result(
            outcome=outcome,
            requested=checked_count,
            succeeded=checked_count,
            failed=0,
            stored=0,
            count_unit="indicator",
            extra={
                "checked_count": checked_count,
                "due_count": len(due_indicators),
                "due_indicators": due_indicators,
                "stale_indicators": stale_indicators,
                "all_fresh": len(due_indicators) == 0,
            },
        )

    except Exception:
        logger.exception("Data freshness check failed")
        indicator_count = len(governed_indicators)
        requested = indicator_count or 1
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=requested,
            succeeded=0,
            failed=requested,
            stored=0,
            count_unit="indicator" if indicator_count else "batch",
            error="macro_freshness_check_failed",
            extra={
                "checked_count": indicator_count,
                "due_count": 0,
                "due_indicators": [],
                "stale_indicators": [],
                "all_fresh": False,
            },
        )


@shared_task(time_limit=300, soft_time_limit=280)  # type: ignore[misc]
def send_data_freshness_alert(
    stale_indicators: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    发送数据新鲜度告警

    Args:
        stale_indicators: 缺失或过期指标列表

    Returns:
        dict: 告警发送结果
    """
    if not isinstance(stale_indicators, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("indicator"), str)
        or not str(item.get("indicator") or "").strip()
        for item in stale_indicators
    ):
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            count_unit="indicator",
            error="stale_indicators must be a list of indicator mappings",
        )
    if not stale_indicators:
        return _task_result(
            outcome=TaskBusinessOutcome.NOOP,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            count_unit="indicator",
            status="not_needed",
        )

    try:
        logger.warning(f"Sending data freshness alert for {len(stale_indicators)} indicators")

        # 这里可以集成邮件、Slack、钉钉等告警渠道
        # 暂时只记录日志
        for item in stale_indicators:
            logger.warning(
                f"STALE DATA ALERT: {item['indicator']} "
                f"reason={item.get('reason', 'stale')} "
                f"latest={item.get('latest_date', '')} "
                f"lag={item.get('days_lag')} days "
                f"status={item.get('freshness_status')} "
                f"grade={item.get('decision_grade')}"
            )

        count = len(stale_indicators)
        return _task_result(
            outcome=TaskBusinessOutcome.SUCCESS,
            requested=count,
            succeeded=count,
            failed=0,
            stored=0,
            count_unit="indicator",
            status="alerted",
            extra={"count": count},
        )

    except Exception:
        logger.exception("Failed to send alert")
        count = len(stale_indicators)
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=count,
            succeeded=0,
            failed=count,
            stored=0,
            count_unit="indicator",
            error="macro_freshness_alert_failed",
            extra={"count": 0},
        )


@shared_task(time_limit=1800, soft_time_limit=1700)  # type: ignore[misc]
def auto_sync_due_macro_indicators(
    indicator_codes: list[str] | None = None,
) -> dict[str, Any]:
    """
    Automatically sync governed macro indicators whose series are missing or stale.

    Args:
        indicator_codes: Optional subset of indicator codes to refresh.

    Returns:
        dict: Sync result summary.
    """

    try:
        normalized_codes = _validated_indicator_filter(indicator_codes)
    except ValueError as exc:
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            count_unit="indicator",
            error=str(exc),
            extra={"sync_runs": [], "synced_indicator_count": 0, "failed_indicator_count": 0},
        )

    due_indicators: list[dict[str, Any]] = []
    try:
        logger.info("Starting governed macro auto-sync")
        due_indicators = _collect_due_macro_indicators()
        if normalized_codes is not None:
            requested_codes = set(normalized_codes)
            due_indicators = [
                item
                for item in due_indicators
                if str(item.get("indicator") or "").upper() in requested_codes
            ]
        if not due_indicators:
            return _task_result(
                outcome=TaskBusinessOutcome.NOOP,
                requested=0,
                succeeded=0,
                failed=0,
                stored=0,
                count_unit="indicator",
                extra={
                    "message": "No governed stale or missing indicators to sync.",
                    "sync_runs": [],
                    "synced_indicator_count": 0,
                    "failed_indicator_count": 0,
                    "blocked_indicator_count": 0,
                    "records_stored": 0,
                },
            )

        sync_executor: Callable[[SyncMacroRequest], SyncResult] | None = None
        today = date.today()
        sync_runs: list[dict[str, Any]] = []

        for item in due_indicators:
            indicator_code = str(item.get("indicator") or "").strip()
            source_type = str(item.get("source_type") or "").strip()
            latest_reporting_period = item.get("latest_reporting_period")
            period_type = str(item.get("period_type") or "")
            provider_id = get_active_provider_id_by_source(source_type)
            if provider_id is None:
                logger.warning(
                    "Skipping auto-sync for %s because source_type=%s has no active provider",
                    indicator_code,
                    source_type,
                )
                sync_runs.append(
                    {
                        "indicator_code": indicator_code,
                        "reason": item.get("reason"),
                        "source_type": source_type,
                        "status": "blocked",
                        "stored_count": 0,
                        "error_message": f"No active provider configured for source_type={source_type}",
                    }
                )
                continue

            start_date = _suggest_refresh_start(
                period_type=period_type,
                latest_reporting_period=latest_reporting_period,
                today=today,
            )
            try:
                if sync_executor is None:
                    sync_executor = make_sync_macro_use_case().execute
                result = sync_executor(
                    SyncMacroRequest(
                        provider_id=provider_id,
                        indicator_code=indicator_code,
                        start=start_date,
                        end=today,
                    )
                )
                stored_count = int(result.stored_count)
                run_status = (
                    "success" if result.status == "success" and stored_count > 0 else "failed"
                )
                sync_runs.append(
                    {
                        "indicator_code": indicator_code,
                        "reason": item.get("reason"),
                        "source_type": source_type,
                        "provider_id": provider_id,
                        "provider_name": result.provider_name,
                        "status": run_status,
                        "provider_status": result.status,
                        "stored_count": stored_count,
                        "start": start_date.isoformat(),
                        "end": today.isoformat(),
                        "error_message": (
                            "" if stored_count > 0 else "sync returned zero stored records"
                        ),
                    }
                )
            except Exception as exc:
                logger.exception("Governed macro auto-sync failed for %s", indicator_code)
                sync_runs.append(
                    {
                        "indicator_code": indicator_code,
                        "reason": item.get("reason"),
                        "source_type": source_type,
                        "provider_id": provider_id,
                        "status": "failed",
                        "stored_count": 0,
                        "start": start_date.isoformat(),
                        "end": today.isoformat(),
                        "error_message": str(exc),
                    }
                )

        requested_count = len(sync_runs)
        success_count = sum(1 for run in sync_runs if run.get("status") == "success")
        failed_count = sum(1 for run in sync_runs if run.get("status") == "failed")
        blocked_count = sum(1 for run in sync_runs if run.get("status") == "blocked")
        records_stored = sum(int(run.get("stored_count") or 0) for run in sync_runs)
        if success_count == requested_count:
            outcome = TaskBusinessOutcome.SUCCESS
        elif blocked_count == requested_count:
            outcome = TaskBusinessOutcome.BLOCKED
        elif failed_count == requested_count:
            outcome = TaskBusinessOutcome.FAILED
        else:
            outcome = TaskBusinessOutcome.PARTIAL
        return _task_result(
            outcome=outcome,
            requested=requested_count,
            succeeded=success_count,
            failed=failed_count,
            stored=success_count,
            blocked=blocked_count,
            count_unit="indicator",
            error=("macro_auto_sync_failed" if outcome is TaskBusinessOutcome.FAILED else ""),
            extra={
                "sync_runs": sync_runs,
                "synced_indicator_count": success_count,
                "failed_indicator_count": failed_count,
                "blocked_indicator_count": blocked_count,
                "records_stored": records_stored,
            },
        )
    except Exception:
        logger.exception("Governed macro auto-sync failed")
        indicator_count = len(due_indicators)
        requested = indicator_count or 1
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=requested,
            succeeded=0,
            failed=requested,
            stored=0,
            count_unit="indicator" if indicator_count else "batch",
            error="macro_auto_sync_failed",
            extra={
                "sync_runs": [],
                "synced_indicator_count": 0,
                "failed_indicator_count": indicator_count,
                "blocked_indicator_count": 0,
                "records_stored": 0,
            },
        )


@shared_task(time_limit=900, soft_time_limit=850)  # type: ignore[misc]
def cleanup_old_data(days_to_keep: int = 365 * 10) -> dict[str, Any]:
    """
    清理旧数据任务

    定期清理超过保留期限的历史数据（可选）。

    Args:
        days_to_keep: 保留天数（默认 10 年）

    Returns:
        dict: 清理结果
    """
    try:
        validated_days_to_keep = _validated_positive_int(
            days_to_keep,
            field_name="days_to_keep",
            maximum=36_500,
        )
    except ValueError as exc:
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            count_unit="record",
            error=str(exc),
            extra={"cutoff_date": "", "records_found": 0, "records_deleted": 0},
        )

    try:
        logger.info(f"Starting cleanup of data older than {days_to_keep} days")
        cutoff_date = date.today() - timedelta(days=validated_days_to_keep)

        # 统计即将删除的数据
        count = get_macro_repository().count_records_before_date(cutoff_date)

        if count > 0:
            logger.warning(f"Cleanup would delete {count} records (cutoff={cutoff_date})")
            # 实际删除（谨慎操作）
            # old_records.delete()
        else:
            logger.info("No old records to clean up")

        if count < 0:
            raise ValueError("repository returned a negative record count")
        outcome = TaskBusinessOutcome.BLOCKED if count > 0 else TaskBusinessOutcome.NOOP
        return _task_result(
            outcome=outcome,
            requested=count,
            succeeded=0,
            failed=0,
            stored=0,
            blocked=count,
            count_unit="record",
            error=("cleanup_deletion_disabled" if count > 0 else ""),
            extra={
                "cutoff_date": str(cutoff_date),
                "records_found": count,
                "records_deleted": 0,
            },
        )

    except Exception:
        logger.exception("Cleanup failed")
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=1,
            succeeded=0,
            failed=1,
            stored=0,
            count_unit="batch",
            error="macro_cleanup_scan_failed",
            extra={"cutoff_date": "", "records_found": 0, "records_deleted": 0},
        )


# ==================== High-Frequency Data Sync Tasks ====================


def _sync_high_frequency_indicator_batch(
    *,
    source: object,
    years_back: object,
    indicators: list[str],
    task_label: str,
) -> dict[str, Any]:
    """Run one governed high-frequency indicator batch with normalized counts."""

    try:
        normalized_source = _validated_identifier(source, field_name="source")
        validated_years_back = _validated_positive_int(
            years_back,
            field_name="years_back",
            maximum=50,
        )
    except ValueError as exc:
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            count_unit="indicator",
            error=str(exc),
            extra={"synced_count": 0, "records_stored": 0, "errors": [], "indicators": indicators},
        )

    try:
        logger.info(
            "Starting %s data sync from %s, years_back=%s",
            task_label,
            normalized_source,
            validated_years_back,
        )
        end_date = date.today()
        start_date = end_date - timedelta(days=365 * validated_years_back)
        result = build_sync_macro_data_use_case(normalized_source).execute(
            SyncMacroDataRequest(
                start_date=start_date,
                end_date=end_date,
                indicators=indicators,
            )
        )
        synced_count = int(result.synced_count)
        errors = list(result.errors or [])
        requested = 1
        if synced_count <= 0:
            outcome = TaskBusinessOutcome.FAILED
            succeeded = 0
            failed = requested
        elif errors:
            outcome = TaskBusinessOutcome.PARTIAL
            succeeded = 1
            failed = 0
        else:
            outcome = TaskBusinessOutcome.SUCCESS
            succeeded = 1
            failed = 0
        return _task_result(
            outcome=outcome,
            requested=requested,
            succeeded=succeeded,
            failed=failed,
            stored=succeeded,
            count_unit="batch",
            error=(f"{task_label}_sync_zero_output" if synced_count <= 0 else ""),
            extra={
                "source": normalized_source,
                "synced_count": max(synced_count, 0),
                "records_stored": max(synced_count, 0),
                "errors": errors,
                "error_count": len(errors),
                "indicators": indicators,
                "indicator_count": len(indicators),
            },
        )
    except Exception:
        logger.exception("High-frequency %s sync failed", task_label)
        requested = 1
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            requested=requested,
            succeeded=0,
            failed=requested,
            stored=0,
            count_unit="batch",
            error=f"{task_label}_sync_failed",
            extra={
                "source": normalized_source,
                "synced_count": 0,
                "records_stored": 0,
                "errors": [f"{task_label}_sync_failed"],
                "error_count": 1,
                "indicators": indicators,
                "indicator_count": len(indicators),
            },
        )


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=900,
    soft_time_limit=850,
)
def sync_high_frequency_bonds(
    self: Any,
    source: str = "akshare",
    years_back: int = 1,
) -> dict[str, Any]:
    """
    同步高频债券收益率数据任务

    定时任务，从 AKShare 同步最新的国债收益率数据。
    建议运行时间：每个交易日 16:30（收盘后）

    Args:
        source: 数据源（当前仅支持 akshare）
        years_back: 回溯年数（默认1年，用于首次同步）

    Returns:
        dict: 同步结果统计
    """
    return _sync_high_frequency_indicator_batch(
        source=source,
        years_back=years_back,
        indicators=[
            "CN_BOND_10Y",
            "CN_BOND_5Y",
            "CN_BOND_2Y",
            "US_BOND_10Y",
            "CN_TERM_SPREAD_10Y2Y",
        ],
        task_label="bond",
    )


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=900,
    soft_time_limit=850,
)
def sync_high_frequency_commodities(
    self: Any,
    source: str = "akshare",
    years_back: int = 1,
) -> dict[str, Any]:
    """
    同步高频商品指数数据任务

    定时任务，从 AKShare 同步最新的南华商品指数数据。
    建议运行时间：每个交易日 16:30（收盘后）

    Args:
        source: 数据源（当前仅支持 akshare）
        years_back: 回溯年数

    Returns:
        dict: 同步结果统计
    """
    return _sync_high_frequency_indicator_batch(
        source=source,
        years_back=years_back,
        indicators=["CN_NHCI"],
        task_label="commodity",
    )


# ============================================================================
# Celery Beat 调度配置建议
# ============================================================================
#
# 在 Django Admin 的 Periodic Tasks 中配置:
#
# 1. sync_macro_data:
#    - Crontab: 每日 00:00
#    - Args: {"source": "akshare"}
#
# 2. check_data_freshness:
#    - Interval: 每 6 小时
#    - Args: {}
#
# 3. cleanup_old_data:
#    - Crontab: 每月 1 日 02:00
#    - Args: {"days_to_keep": 3650}
#
# 4. sync_macro_then_refresh_regime (推荐):
#    - 位置: apps.regime.application.orchestration
#    - Crontab: 每日 00:00
#    - Args: {"source": "akshare", "use_pit": true}
#    - 说明: 这个编排任务会自动依次执行 sync -> calculate -> notify
