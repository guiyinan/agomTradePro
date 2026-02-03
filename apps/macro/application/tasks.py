"""
Celery Tasks for Macro Data Synchronization.

异步任务：宏观数据同步、Regime 计算、数据更新检查等。
"""

from celery import shared_task, chain
from celery.utils.log import get_task_logger
from typing import Optional
from datetime import date, timedelta

from apps.macro.application.use_cases import SyncMacroDataUseCase
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.application.use_cases import CalculateRegimeUseCase, CalculateRegimeRequest
from apps.regime.application.tasks import calculate_regime_task, notify_regime_change
from shared.config.secrets import get_secrets

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def sync_macro_data(
    self,
    source: str = 'akshare',
    indicator: Optional[str] = None,
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

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(repository)

        # 计算日期范围
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        # 构建请求对象
        from apps.macro.application.use_cases import SyncMacroDataRequest
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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def calculate_regime(
    self,
    as_of_date: Optional[str] = None,
    use_pit: bool = True
) -> dict:
    """
    计算 Regime 判定任务

    定时任务，基于最新宏观数据计算 Regime 象限。

    Args:
        as_of_date: 分析时点 (YYYY-MM-DD，None 表示今天)
        use_pit: 是否使用 Point-in-Time 数据

    Returns:
        dict: Regime 计算结果
    """
    try:
        logger.info(f"Starting regime calculation for date={as_of_date}, use_pit={use_pit}")

        repository = DjangoMacroRepository()
        use_case = CalculateRegimeUseCase(repository)

        # 解析日期
        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()

        # 执行计算
        request = CalculateRegimeRequest(
            as_of_date=target_date,
            use_pit=use_pit,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source="akshare"
        )

        response = use_case.execute(request)

        if response.success:
            snapshot = response.snapshot
            logger.info(f"Regime calculation completed: {snapshot.dominant_regime}")

            return {
                'status': 'success',
                'as_of_date': str(target_date),
                'dominant_regime': snapshot.dominant_regime,
                'confidence': snapshot.confidence,
                'distribution': snapshot.regime_distribution,
                'warnings': response.warnings
            }
        else:
            logger.error(f"Regime calculation failed: {response.error}")
            return {
                'status': 'error',
                'error': response.error
            }

    except Exception as exc:
        logger.error(f"Regime calculation failed: {exc}")
        raise


@shared_task
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


@shared_task
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


@shared_task
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

        from apps.macro.infrastructure.models import MacroIndicator
        from django.db.models import Count
        from datetime import date, timedelta

        cutoff_date = date.today() - timedelta(days=days_to_keep)

        # 统计即将删除的数据
        old_records = MacroIndicator.objects.filter(observed_at__lt=cutoff_date)
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
    retry_backoff=True
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

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(repository)

        from apps.macro.application.use_cases import SyncMacroDataRequest
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
    retry_backoff=True
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

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(repository)

        from apps.macro.application.use_cases import SyncMacroDataRequest
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


@shared_task
def generate_daily_regime_signal(
    as_of_date: Optional[str] = None
) -> dict:
    """
    生成日度 Regime 信号任务

    基于高频指标生成每日 Regime 信号，减少判定滞后。
    建议运行时间：每个交易日 17:00（高频数据同步后）

    Args:
        as_of_date: 分析时点 (YYYY-MM-DD，None 表示今天)

    Returns:
        dict: 日度信号结果
    """
    try:
        from apps.regime.application.use_cases import HighFrequencySignalRequest, HighFrequencySignalUseCase

        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()

        logger.info(f"Generating daily regime signal for {target_date}")

        repository = DjangoMacroRepository()
        use_case = HighFrequencySignalUseCase(repository)

        request = HighFrequencySignalRequest(
            as_of_date=target_date,
            lookback_days=30
        )

        result = use_case.execute(request)

        if result.success:
            logger.info(
                f"Daily regime signal generated: {result.signal_direction}, "
                f"strength={result.signal_strength:.2f}, "
                f"confidence={result.confidence:.2f}"
            )

            # 检查是否有警告信号
            if result.warning_signals:
                logger.warning(f"Warning signals detected: {result.warning_signals}")

            return {
                'status': 'success',
                'as_of_date': str(target_date),
                'signal_direction': result.signal_direction,
                'signal_strength': result.signal_strength,
                'confidence': result.confidence,
                'contributing_indicators': result.contributing_indicators,
                'warning_signals': result.warning_signals
            }
        else:
            logger.error(f"Daily regime signal generation failed: {result.error}")
            return {
                'status': 'error',
                'error': result.error
            }

    except Exception as exc:
        logger.error(f"Daily regime signal generation failed: {exc}")
        raise


@shared_task
def recalculate_regime_with_daily_signal(
    as_of_date: Optional[str] = None,
    use_pit: bool = True
) -> dict:
    """
    重新计算 Regime（融合日度信号）

    结合传统月度指标和高频日度指标重新计算 Regime。
    建议运行时间：每个交易日 17:30

    Args:
        as_of_date: 分析时点 (YYYY-MM-DD，None 表示今天)
        use_pit: 是否使用 Point-in-Time 数据

    Returns:
        dict: Regime 计算结果（融合日度信号）
    """
    try:
        from apps.regime.application.use_cases import (
            CalculateRegimeUseCase, CalculateRegimeRequest,
            HighFrequencySignalUseCase, HighFrequencySignalRequest,
            ResolveSignalConflictUseCase, ResolveSignalConflictRequest
        )

        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()

        logger.info(f"Recalculating regime with daily signal for {target_date}")

        repository = DjangoMacroRepository()

        # 1. 计算传统月度 Regime
        monthly_use_case = CalculateRegimeUseCase(repository)
        monthly_request = CalculateRegimeRequest(
            as_of_date=target_date,
            use_pit=use_pit,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source="akshare"
        )
        monthly_response = monthly_use_case.execute(monthly_request)

        # 2. 生成日度信号
        daily_use_case = HighFrequencySignalUseCase(repository)
        daily_request = HighFrequencySignalRequest(
            as_of_date=target_date,
            lookback_days=30
        )
        daily_response = daily_use_case.execute(daily_request)

        if not monthly_response.success:
            return {
                'status': 'error',
                'error': f"Monthly regime calculation failed: {monthly_response.error}"
            }

        if not daily_response.success:
            # 日度信号失败，直接返回月度结果
            logger.warning(f"Daily signal generation failed, using monthly only: {daily_response.error}")
            return {
                'status': 'success',
                'as_of_date': str(target_date),
                'final_regime': monthly_response.snapshot.dominant_regime,
                'final_confidence': monthly_response.snapshot.confidence,
                'source': 'MONTHLY_ONLY',
                'monthly_signal': monthly_response.snapshot.dominant_regime,
                'daily_signal': None
            }

        # 3. 解决信号冲突
        resolver = ResolveSignalConflictUseCase()
        conflict_request = ResolveSignalConflictRequest(
            daily_signal=daily_response.signal_direction,
            daily_confidence=daily_response.confidence,
            daily_duration_days=1,  # TODO: 追踪实际持续天数
            monthly_signal=monthly_response.snapshot.dominant_regime,
            monthly_confidence=monthly_response.snapshot.confidence
        )
        resolution = resolver.execute(conflict_request)

        logger.info(
            f"Regime recalculation completed: final={resolution.final_signal}, "
            f"reason={resolution.resolution_reason}"
        )

        return {
            'status': 'success',
            'as_of_date': str(target_date),
            'final_regime': resolution.final_signal,
            'final_confidence': resolution.final_confidence,
            'source': resolution.source,
            'resolution_reason': resolution.resolution_reason,
            'monthly_signal': monthly_response.snapshot.dominant_regime,
            'monthly_confidence': monthly_response.snapshot.confidence,
            'daily_signal': daily_response.signal_direction,
            'daily_confidence': daily_response.confidence,
            'daily_contributors': daily_response.contributing_indicators,
            'warning_signals': daily_response.warning_signals
        }

    except Exception as exc:
        logger.error(f"Regime recalculation with daily signal failed: {exc}")
        raise


# Celery Beat 调度配置建议
# 在 Django Admin 的 Periodic Tasks 中配置：
#
# 1. sync_macro_data:
#    - Crontab: 每日 00:00
#    - Args: {"source": "akshare"}
#
# 2. calculate_regime:
#    - Crontab: 每日 00:30 (在数据同步后执行)
#    - Args: {"use_pit": true}
#
# 3. check_data_freshness:
#    - Interval: 每 6 小时
#    - Args: {}
#
# 4. cleanup_old_data:
#    - Crontab: 每月 1 日 02:00
#    - Args: {"days_to_keep": 3650}
#
# 5. sync_and_calculate_regime (推荐使用):
#    - Crontab: 每日 00:00
#    - Args: {"source": "akshare", "use_pit": true}
#    - 说明：这个编排任务会自动依次执行 sync -> calculate -> notify


@shared_task
def sync_and_calculate_regime(
    source: str = 'akshare',
    indicator: Optional[str] = None,
    days_back: int = 30,
    use_pit: bool = True,
    as_of_date: Optional[str] = None
) -> dict:
    """
    编排任务：宏观数据同步 + Regime 计算 + 通知

    使用 Celery chain 编排完整的任务流：
    1. sync_macro_data - 同步宏观数据
    2. calculate_regime_task - 计算 Regime（接收 sync 结果）
    3. notify_regime_change - 发送变化通知

    Args:
        source: 数据源 ('akshare' 或 'tushare')
        indicator: 指标代码 (None 表示同步所有)
        days_back: 回溯天数（用于数据同步）
        use_pit: 是否使用 Point-in-Time 数据
        as_of_date: 分析时点 (YYYY-MM-DD，None 表示今天)

    Returns:
        dict: 编排任务的结果
    """
    try:
        logger.info(
            f"Starting orchestrated workflow: sync -> calculate -> notify, "
            f"source={source}, use_pit={use_pit}"
        )

        # 计算日期范围
        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()

        # 创建任务链
        workflow = chain(
            sync_macro_data.s(source=source, indicator=indicator, days_back=days_back),
            calculate_regime_task.s(as_of_date=as_of_date or target_date.isoformat(), use_pit=use_pit),
            notify_regime_change.s()
        )

        # 异步执行任务链
        result = workflow.apply_async()

        logger.info(f"Orchestrated workflow started, task ID: {result.id}")

        return {
            'status': 'started',
            'task_id': result.id,
            'workflow': 'sync_macro_data -> calculate_regime_task -> notify_regime_change',
            'source': source,
            'as_of_date': as_of_date or target_date.isoformat()
        }

    except Exception as exc:
        logger.error(f"Failed to start orchestrated workflow: {exc}")
        raise
