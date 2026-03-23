"""
Celery Tasks for Regime Calculation.

异步任务：Regime 计算、变化通知等。
"""

from datetime import date
from typing import Any, Dict, Optional

from celery import shared_task
from celery.utils.log import get_task_logger

from apps.regime.application.current_regime import resolve_current_regime
from apps.regime.infrastructure.repositories import DjangoRegimeRepository

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def calculate_regime_task(
    self,
    sync_result: dict[str, Any] | None = None,
    as_of_date: str | None = None,
    use_pit: bool = True
) -> dict:
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
    try:
        # 检查前一步是否成功
        if sync_result and not sync_result.get('success', True):
            logger.warning(f"Previous sync step failed, skipping regime calculation: {sync_result.get('error')}")
            return {
                'status': 'skipped',
                'reason': 'sync_failed',
                'sync_result': sync_result
            }

        logger.info(f"Starting regime calculation for date={as_of_date}, use_pit={use_pit}")

        # 解析日期
        target_date = date.fromisoformat(as_of_date) if as_of_date else date.today()
        current = resolve_current_regime(as_of_date=target_date, use_pit=use_pit)
        logger.info(
            "Regime calculation completed: %s, confidence=%.2f",
            current.dominant_regime,
            current.confidence,
        )
        return {
            'status': 'success',
            'as_of_date': str(target_date),
            'dominant_regime': current.dominant_regime,
            'confidence': current.confidence,
            'distribution': {},
            'growth_z': 0.0,
            'inflation_z': 0.0,
            'warnings': current.warnings,
            'source': current.data_source,
            'is_fallback': current.is_fallback,
        }

    except Exception as exc:
        logger.error(f"Regime calculation failed: {exc}")
        raise


@shared_task
def notify_regime_change(regime_result: dict) -> dict:
    """
    发送 Regime 变化通知

    当 Regime 发生显著变化时发送通知。

    Args:
        regime_result: calculate_regime_task 的输出

    Returns:
        dict: 通知发送结果
    """
    try:
        if not regime_result.get('success') and regime_result.get('status') != 'success':
            logger.info(f"Regime calculation not successful, skipping notification: {regime_result.get('status')}")
            return {
                'status': 'skipped',
                'reason': 'regime_not_successful'
            }

        logger.info(f"Checking regime change for notification: {regime_result.get('dominant_regime')}")

        # 获取上一次的 Regime
        regime_repo = DjangoRegimeRepository()
        current_date = date.fromisoformat(regime_result['as_of_date'])
        last_snapshot = regime_repo.get_latest_snapshot(before_date=current_date)

        # 检查是否有显著变化
        if last_snapshot:
            regime_changed = last_snapshot.dominant_regime != regime_result['dominant_regime']
            confidence_dropped = regime_result['confidence'] < last_snapshot.confidence * 0.8

            if regime_changed:
                logger.warning(
                    f"REGIME CHANGE DETECTED: {last_snapshot.dominant_regime} -> {regime_result['dominant_regime']}"
                )
                # 这里可以集成邮件、钉钉、Slack 等通知渠道
                # send_alert_email(...)
                # send_dingtalk_message(...)

            if confidence_dropped:
                logger.warning(
                    f"CONFIDENCE DROPPED: {last_snapshot.confidence:.2f} -> {regime_result['confidence']:.2f}"
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


@shared_task
def check_regime_health() -> dict:
    """
    检查 Regime 计算健康状态

    定期检查最新的 Regime 计算，发现异常时告警。

    Returns:
        dict: 健康检查结果
    """
    try:
        logger.info("Checking regime calculation health")

        regime_repo = DjangoRegimeRepository()
        latest = regime_repo.get_latest_snapshot()

        if not latest:
            return {
                'status': 'error',
                'error': 'No regime data available'
            }

        # 检查数据新鲜度
        days_since = (date.today() - latest.observed_at).days
        is_stale = days_since > 7  # 超过 7 天视为过期

        # 检查置信度
        is_low_confidence = latest.confidence < 0.2

        health_status = 'healthy'
        if is_stale or is_low_confidence:
            health_status = 'warning'
            logger.warning(f"Regime health warning: stale={is_stale}, low_confidence={is_low_confidence}")

        return {
            'status': 'success',
            'health': health_status,
            'latest_date': str(latest.observed_at),
            'days_since': days_since,
            'dominant_regime': latest.dominant_regime,
            'confidence': latest.confidence,
            'is_stale': is_stale,
            'is_low_confidence': is_low_confidence
        }

    except Exception as exc:
        logger.error(f"Regime health check failed: {exc}")
        raise

