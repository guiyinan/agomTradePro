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
from typing import Optional

from celery import shared_task
from celery.utils.log import get_task_logger

from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)
from apps.macro.infrastructure.repositories import DjangoMacroRepository

logger = get_task_logger(__name__)


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

    定时检查各指标的最新数据日期，发现延迟时告警。

    Returns:
        dict: 数据新鲜度报告
    """
    try:
        logger.info("Checking data freshness")

        repository = DjangoMacroRepository()

        # 检查关键指标
        indicators = ['PMI', 'CPI', 'M2', 'PPI']
        stale_indicators = []

        for indicator in indicators:
            latest = repository.get_latest_observation_date(indicator)
            if latest:
                days_lag = (date.today() - latest).days

                # 根据指标特点设置不同的延迟阈值
                thresholds = {
                    'PMI': 45,    # 月度数据，45天
                    'CPI': 45,
                    'M2': 45,
                    'PPI': 45
                }

                if days_lag > thresholds.get(indicator, 60):
                    stale_indicators.append({
                        'indicator': indicator,
                        'latest_date': str(latest),
                        'days_lag': days_lag,
                        'threshold': thresholds[indicator]
                    })
                    logger.warning(f"Indicator {indicator} is stale: {days_lag} days")

        if stale_indicators:
            # 触发告警
            send_data_freshness_alert.delay(stale_indicators)

        return {
            'status': 'success',
            'stale_indicators': stale_indicators,
            'all_fresh': len(stale_indicators) == 0
        }

    except Exception as exc:
        logger.error(f"Data freshness check failed: {exc}")
        raise


@shared_task(time_limit=300, soft_time_limit=280)
def send_data_freshness_alert(stale_indicators: list) -> dict:
    """
    发送数据新鲜度告警

    Args:
        stale_indicators: 过期指标列表

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
                f"latest={item['latest_date']} "
                f"lag={item['days_lag']} days "
                f"(threshold={item['threshold']})"
            )

        return {
            'status': 'alerted',
            'count': len(stale_indicators)
        }

    except Exception as exc:
        logger.error(f"Failed to send alert: {exc}")
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

        from django.db.models import Count

        from apps.macro.infrastructure.models import MacroIndicator

        cutoff_date = date.today() - timedelta(days=days_to_keep)

        # 统计即将删除的数据
        old_records = MacroIndicator._default_manager.filter(observed_at__lt=cutoff_date)
        count = old_records.count()

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
