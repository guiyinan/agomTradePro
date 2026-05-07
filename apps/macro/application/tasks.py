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

from datetime import date, timedelta
from typing import Any, Optional

from celery import shared_task
from celery.utils.log import get_task_logger

from apps.data_center.application.dtos import MacroSeriesRequest, SyncMacroRequest
from apps.data_center.application.interface_services import (
    get_active_provider_id_by_source,
    make_query_macro_series_use_case,
    make_sync_macro_use_case,
)
from apps.data_center.application.repository_provider import (
    get_indicator_catalog_repository,
)
from apps.macro.application.repository_provider import get_macro_repository
from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)

logger = get_task_logger(__name__)


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


def _collect_due_macro_indicators() -> list[dict[str, Any]]:
    """Return governed sync-supported indicators whose data is missing or stale."""

    query_use_case = make_query_macro_series_use_case()
    today = date.today()
    due_items: list[dict[str, Any]] = []

    for item in _list_sync_governed_indicators():
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


@shared_task(
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
    self,
    source: str = 'akshare',
    indicator: str | None = None,
    days_back: int = 1
) -> dict:
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
        logger.info(f"Starting macro data sync from {source}, indicator={indicator}, days_back={days_back}")

        use_case = build_sync_macro_data_use_case(source)

        # 计算日期范围
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        # 构建请求对象
        request = SyncMacroDataRequest(
            start_date=start_date,
            end_date=end_date,
            indicators=[indicator] if indicator else None
        )

        # 执行同步
        result = use_case.execute(request)

        logger.info(f"Macro data sync completed: {result}")

        return {
            'status': 'success',
            'source': source,
            'indicator': indicator,
            'synced_count': result.synced_count,
            'skipped_count': result.skipped_count,
            'errors': result.errors
        }

    except Exception as exc:
        logger.error(f"Macro data sync failed: {exc}")
        raise


# 注意: calculate_regime 任务已移至 apps/regime/application/tasks.py
# 使用 regime 模块的编排函数来协调 macro 同步和 regime 计算


@shared_task(time_limit=300, soft_time_limit=280)
def check_data_freshness() -> dict:
    """
    检查数据新鲜度任务

    定时检查所有已配置自动同步的宏观指标，发现缺失或过期时告警。

    Returns:
        dict: 数据新鲜度报告
    """
    try:
        logger.info("Checking data freshness")
        due_indicators = _collect_due_macro_indicators()
        stale_indicators = [
            item for item in due_indicators if item.get("reason") == "stale"
        ]

        if due_indicators:
            send_data_freshness_alert.delay(due_indicators)

        return {
            'status': 'success',
            'checked_count': len(_list_sync_governed_indicators()),
            'due_indicators': due_indicators,
            'stale_indicators': stale_indicators,
            'all_fresh': len(due_indicators) == 0
        }

    except Exception as exc:
        logger.error(f"Data freshness check failed: {exc}")
        raise


@shared_task(time_limit=300, soft_time_limit=280)
def send_data_freshness_alert(stale_indicators: list) -> dict:
    """
    发送数据新鲜度告警

    Args:
        stale_indicators: 缺失或过期指标列表

    Returns:
        dict: 告警发送结果
    """
    try:
        logger.warning(f"Sending data freshness alert for {len(stale_indicators)} indicators")

        # 这里可以集成邮件、Slack、钉钉等告警渠道
        # 暂时只记录日志
        for item in stale_indicators:
            logger.warning(
                f"STALE DATA ALERT: {item['indicator']} "
                f"reason={item.get('reason', 'stale')} "
                f"latest={item['latest_date']} "
                f"lag={item.get('days_lag')} days "
                f"status={item.get('freshness_status')} "
                f"grade={item.get('decision_grade')}"
            )

        return {
            'status': 'alerted',
            'count': len(stale_indicators)
        }

    except Exception as exc:
        logger.error(f"Failed to send alert: {exc}")
        raise


@shared_task(time_limit=1800, soft_time_limit=1700)
def auto_sync_due_macro_indicators(indicator_codes: list[str] | None = None) -> dict:
    """
    Automatically sync governed macro indicators whose series are missing or stale.

    Args:
        indicator_codes: Optional subset of indicator codes to refresh.

    Returns:
        dict: Sync result summary.
    """

    try:
        logger.info("Starting governed macro auto-sync")
        due_indicators = _collect_due_macro_indicators()
        if indicator_codes:
            requested_codes = {
                str(code).strip().upper()
                for code in indicator_codes
                if str(code).strip()
            }
            due_indicators = [
                item
                for item in due_indicators
                if str(item.get("indicator") or "").upper() in requested_codes
            ]
        if not due_indicators:
            return {
                'status': 'success',
                'message': 'No governed stale or missing indicators to sync.',
                'sync_runs': [],
                'synced_indicator_count': 0,
                'failed_indicator_count': 0,
            }

        sync_use_case = make_sync_macro_use_case()
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
                        'indicator_code': indicator_code,
                        'reason': item.get('reason'),
                        'source_type': source_type,
                        'status': 'failed',
                        'stored_count': 0,
                        'error_message': f'No active provider configured for source_type={source_type}',
                    }
                )
                continue

            start_date = _suggest_refresh_start(
                period_type=period_type,
                latest_reporting_period=latest_reporting_period,
                today=today,
            )
            try:
                result = sync_use_case.execute(
                    SyncMacroRequest(
                        provider_id=provider_id,
                        indicator_code=indicator_code,
                        start=start_date,
                        end=today,
                    )
                )
                sync_runs.append(
                    {
                        'indicator_code': indicator_code,
                        'reason': item.get('reason'),
                        'source_type': source_type,
                        'provider_id': provider_id,
                        'provider_name': result.provider_name,
                        'status': result.status,
                        'stored_count': result.stored_count,
                        'start': start_date.isoformat(),
                        'end': today.isoformat(),
                    }
                )
            except Exception as exc:
                logger.exception("Governed macro auto-sync failed for %s", indicator_code)
                sync_runs.append(
                    {
                        'indicator_code': indicator_code,
                        'reason': item.get('reason'),
                        'source_type': source_type,
                        'provider_id': provider_id,
                        'status': 'failed',
                        'stored_count': 0,
                        'start': start_date.isoformat(),
                        'end': today.isoformat(),
                        'error_message': str(exc),
                    }
                )

        success_count = sum(1 for run in sync_runs if run.get('status') == 'success')
        failed_count = len(sync_runs) - success_count
        return {
            'status': 'success' if failed_count == 0 else 'partial',
            'sync_runs': sync_runs,
            'synced_indicator_count': success_count,
            'failed_indicator_count': failed_count,
        }
    except Exception as exc:
        logger.error(f"Governed macro auto-sync failed: {exc}")
        raise


@shared_task(time_limit=900, soft_time_limit=850)
def cleanup_old_data(days_to_keep: int = 365 * 10) -> dict:
    """
    清理旧数据任务

    定期清理超过保留期限的历史数据（可选）。

    Args:
        days_to_keep: 保留天数（默认 10 年）

    Returns:
        dict: 清理结果
    """
    try:
        logger.info(f"Starting cleanup of data older than {days_to_keep} days")

        from datetime import date, timedelta

        cutoff_date = date.today() - timedelta(days=days_to_keep)

        # 统计即将删除的数据
        count = get_macro_repository().count_records_before_date(cutoff_date)

        if count > 0:
            logger.warning(f"Cleanup would delete {count} records (cutoff={cutoff_date})")
            # 实际删除（谨慎操作）
            # old_records.delete()
        else:
            logger.info("No old records to clean up")

        return {
            'status': 'success',
            'cutoff_date': str(cutoff_date),
            'records_found': count,
            'records_deleted': 0  # 实际删除后更新
        }

    except Exception as exc:
        logger.error(f"Cleanup failed: {exc}")
        raise


# ==================== High-Frequency Data Sync Tasks ====================

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=900,
    soft_time_limit=850,
)
def sync_high_frequency_bonds(
    self,
    source: str = 'akshare',
    years_back: int = 1
) -> dict:
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
    try:
        logger.info(f"Starting high-frequency bond data sync from {source}, years_back={years_back}")

        from datetime import timedelta

        # 高频债券指标
        bond_indicators = [
            'CN_BOND_10Y',
            'CN_BOND_5Y',
            'CN_BOND_2Y',
            'US_BOND_10Y',
            'CN_TERM_SPREAD_10Y2Y'
        ]

        end_date = date.today()
        start_date = end_date - timedelta(days=365 * years_back)

        use_case = build_sync_macro_data_use_case(source)

        request = SyncMacroDataRequest(
            start_date=start_date,
            end_date=end_date,
            indicators=bond_indicators
        )

        result = use_case.execute(request)

        logger.info(f"High-frequency bond sync completed: {result.synced_count} records")

        return {
            'status': 'success',
            'synced_count': result.synced_count,
            'errors': result.errors,
            'indicators': bond_indicators
        }

    except Exception as exc:
        logger.error(f"High-frequency bond sync failed: {exc}")
        raise


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=900,
    soft_time_limit=850,
)
def sync_high_frequency_commodities(
    self,
    source: str = 'akshare',
    years_back: int = 1
) -> dict:
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
    try:
        logger.info(f"Starting high-frequency commodity data sync from {source}")

        from datetime import timedelta

        commodity_indicators = ['CN_NHCI']

        end_date = date.today()
        start_date = end_date - timedelta(days=365 * years_back)

        use_case = build_sync_macro_data_use_case(source)

        request = SyncMacroDataRequest(
            start_date=start_date,
            end_date=end_date,
            indicators=commodity_indicators
        )

        result = use_case.execute(request)

        logger.info(f"High-frequency commodity sync completed: {result.synced_count} records")

        return {
            'status': 'success',
            'synced_count': result.synced_count,
            'errors': result.errors,
            'indicators': commodity_indicators
        }

    except Exception as exc:
        logger.error(f"High-frequency commodity sync failed: {exc}")
        raise


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
