"""
Regime Orchestration Module.

编排函数：协调 macro 数据同步和 regime 计算的完整工作流。

将原来分散在 macro/tasks.py 中的 regime 编排逻辑移至此处，
实现 macro 模块与 regime 模块的解耦。

使用方式:
    # Celery chain
    from celery import chain
    from apps.regime.application.orchestration import (
        calculate_regime_after_sync,
        notify_regime_change_after_calculation,
    )

    # sync_macro_data 通过 DjangoMacroSyncTaskGateway 延迟解析
"""

from celery import shared_task, chain
from celery.utils.log import get_task_logger
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any, List

logger = get_task_logger(__name__)


# ============================================================================
# 高频信号任务 (从 macro/tasks.py 移入)
# ============================================================================

@shared_task(time_limit=900, soft_time_limit=850)
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
        from apps.regime.application.use_cases import (
            HighFrequencySignalRequest,
            HighFrequencySignalUseCase,
        )
        from apps.regime.infrastructure.macro_data_provider import (
            DjangoMacroDataProvider,
        )

        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()
        logger.info(f"Generating daily regime signal for {target_date}")

        # 使用新的提供者接口
        provider = DjangoMacroDataProvider()
        macro_repo = provider._get_repository()

        use_case = HighFrequencySignalUseCase(macro_repo)
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


@shared_task(time_limit=900, soft_time_limit=850)
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
            HighFrequencySignalUseCase,
            HighFrequencySignalRequest,
            ResolveSignalConflictUseCase,
            ResolveSignalConflictRequest,
        )
        from apps.regime.application.current_regime import resolve_current_regime
        from apps.regime.infrastructure.macro_data_provider import (
            DjangoMacroDataProvider,
        )

        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()
        logger.info(f"Recalculating regime with daily signal for {target_date}")

        # 使用新的提供者接口
        provider = DjangoMacroDataProvider()
        macro_repo = provider._get_repository()

        # 1. 获取月度 regime
        monthly_result = resolve_current_regime(as_of_date=target_date, use_pit=use_pit)

        # 2. 生成日度信号
        daily_use_case = HighFrequencySignalUseCase(macro_repo)
        daily_request = HighFrequencySignalRequest(
            as_of_date=target_date,
            lookback_days=30
        )
        daily_response = daily_use_case.execute(daily_request)

        if not daily_response.success:
            logger.warning(
                "Daily signal generation failed, using monthly only: %s",
                daily_response.error
            )
            return {
                'status': 'success',
                'as_of_date': str(target_date),
                'final_regime': monthly_result.dominant_regime,
                'final_confidence': monthly_result.confidence,
                'source': 'MONTHLY_ONLY',
                'monthly_signal': monthly_result.dominant_regime,
                'daily_signal': None
            }

        # 3. 解决信号冲突
        resolver = ResolveSignalConflictUseCase()
        conflict_request = ResolveSignalConflictRequest(
            daily_signal=daily_response.signal_direction,
            daily_confidence=daily_response.confidence,
            daily_duration_days=1,
            monthly_signal=monthly_result.dominant_regime,
            monthly_confidence=monthly_result.confidence
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
            'monthly_signal': monthly_result.dominant_regime,
            'monthly_confidence': monthly_result.confidence,
            'daily_signal': daily_response.signal_direction,
            'daily_confidence': daily_response.confidence,
            'daily_contributors': daily_response.contributing_indicators,
            'warning_signals': daily_response.warning_signals
        }

    except Exception as exc:
        logger.error(f"Regime recalculation with daily signal failed: {exc}")
        raise


# ============================================================================
# 编排任务
# ============================================================================

@shared_task(time_limit=900, soft_time_limit=850)
def calculate_regime_after_sync(
    sync_result: Optional[Dict[str, Any]] = None,
    as_of_date: Optional[str] = None,
    use_pit: bool = True
) -> dict:
    """
    在 macro 数据同步后计算 Regime

    设计为 Celery chain 的一部分，接收 sync_macro_data 的输出。

    Args:
        sync_result: sync_macro_data 任务的输出
        as_of_date: 分析时点 (YYYY-MM-DD，None 表示今天)
        use_pit: 是否使用 Point-in-Time 数据

    Returns:
        dict: Regime 计算结果
    """
    try:
        from apps.regime.application.current_regime import resolve_current_regime

        # 检查前一步是否成功
        if sync_result and not sync_result.get('success', True):
            logger.warning(
                f"Previous sync step failed, skipping regime calculation: "
                f"{sync_result.get('error')}"
            )
            return {
                'status': 'skipped',
                'reason': 'sync_failed',
                'sync_result': sync_result
            }

        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()
        logger.info(f"Starting regime calculation for date={as_of_date}, use_pit={use_pit}")

        result = resolve_current_regime(as_of_date=target_date, use_pit=use_pit)
        logger.info(f"Regime calculation completed: {result.dominant_regime}")

        return {
            'status': 'success',
            'as_of_date': str(target_date),
            'dominant_regime': result.dominant_regime,
            'confidence': result.confidence,
            'warnings': result.warnings,
            'data_source': result.data_source,
            'is_fallback': result.is_fallback,
        }

    except Exception as exc:
        logger.error(f"Regime calculation failed: {exc}")
        raise


@shared_task(time_limit=600, soft_time_limit=570)
def notify_regime_change_after_calculation(
    regime_result: Optional[Dict[str, Any]] = None
) -> dict:
    """
    在 Regime 计算后发送变化通知

    设计为 Celery chain 的最后一步。

    Args:
        regime_result: calculate_regime_after_sync 任务的输出

    Returns:
        dict: 通知发送结果
    """
    try:
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository

        if not regime_result or regime_result.get('status') != 'success':
            logger.info(
                f"Regime calculation not successful, skipping notification: "
                f"{regime_result.get('status') if regime_result else 'None'}"
            )
            return {
                'status': 'skipped',
                'reason': 'regime_not_successful'
            }

        logger.info(
            f"Checking regime change for notification: "
            f"{regime_result.get('dominant_regime')}"
        )

        regime_repo = DjangoRegimeRepository()
        current_date = date.fromisoformat(regime_result['as_of_date'])
        last_snapshot = regime_repo.get_latest_snapshot(before_date=current_date)

        # 检查是否有显著变化
        if last_snapshot:
            regime_changed = (
                last_snapshot.dominant_regime != regime_result['dominant_regime']
            )
            confidence_dropped = (
                regime_result['confidence'] < last_snapshot.confidence * 0.8
            )

            if regime_changed:
                logger.warning(
                    f"REGIME CHANGE DETECTED: {last_snapshot.dominant_regime} -> "
                    f"{regime_result['dominant_regime']}"
                )
                # TODO: 集成邮件/钉钉/Slack 通知

            if confidence_dropped:
                logger.warning(
                    f"CONFIDENCE DROPPED: {last_snapshot.confidence:.2f} -> "
                    f"{regime_result['confidence']:.2f}"
                )

        return {
            'status': 'success',
            'notified': True,
            'regime': regime_result.get('dominant_regime'),
            'confidence': regime_result.get('confidence')
        }

    except Exception as exc:
        logger.error(f"Failed to send regime change notification: {exc}")
        raise


@shared_task(time_limit=900, soft_time_limit=850)
def sync_macro_then_refresh_regime(
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
    2. calculate_regime_after_sync - 计算 Regime（接收 sync 结果）
    3. notify_regime_change_after_calculation - 发送变化通知

    这个任务替代了原来在 macro/tasks.py 中的 sync_and_calculate_regime，
    但编排逻辑现在由 regime 模块控制。

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

        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()

        from apps.regime.infrastructure.macro_sync_gateway import (
            DjangoMacroSyncTaskGateway,
        )

        gateway = DjangoMacroSyncTaskGateway()

        # 创建任务链
        workflow = chain(
            gateway.build_sync_signature(
                source=source,
                indicator=indicator,
                days_back=days_back,
            ),
            calculate_regime_after_sync.s(as_of_date=as_of_date or target_date.isoformat(), use_pit=use_pit),
            notify_regime_change_after_calculation.s()
        )

        # 异步执行任务链
        result = workflow.apply_async()

        logger.info(f"Orchestrated workflow started, task ID: {result.id}")

        return {
            'status': 'started',
            'task_id': result.id,
            'workflow': 'sync_macro_data -> calculate_regime_after_sync -> notify_regime_change_after_calculation',
            'source': source,
            'as_of_date': as_of_date or target_date.isoformat()
        }

    except Exception as exc:
        logger.error(f"Failed to start orchestrated workflow: {exc}")
        raise
