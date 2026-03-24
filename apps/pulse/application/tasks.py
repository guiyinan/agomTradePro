"""Pulse Celery Tasks"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="pulse.calculate_weekly")
def calculate_weekly_pulse():
    """每周五收盘后计算 Pulse 脉搏，Celery Beat 调度。"""
    from apps.pulse.application.use_cases import CalculatePulseUseCase

    use_case = CalculatePulseUseCase()
    result = use_case.execute()

    if result:
        logger.info(f"Weekly pulse calculated: {result.composite_score:.3f}")
        return {"success": True, "composite_score": result.composite_score}
    else:
        logger.warning("Weekly pulse calculation failed")
        return {"success": False}
