"""Pulse Celery Tasks"""

import logging
from collections.abc import Callable
from typing import Protocol, TypeVar, cast

from celery import shared_task

logger = logging.getLogger(__name__)
TaskFunction = TypeVar("TaskFunction", bound=Callable[..., object])


class SharedTaskDecorator(Protocol):
    """Typed projection of Celery's untyped shared-task decorator factory."""

    def __call__(self, *, name: str) -> Callable[[TaskFunction], TaskFunction]: ...


typed_shared_task = cast(SharedTaskDecorator, shared_task)


@typed_shared_task(name="pulse.calculate_weekly")
def calculate_weekly_pulse() -> dict[str, bool | float]:
    """每周五收盘后计算 Pulse 脉搏，Celery Beat 调度。"""
    from apps.pulse.application.use_cases import CalculatePulseUseCase

    use_case = CalculatePulseUseCase()
    result = use_case.execute()

    if result:
        logger.info("Weekly pulse calculated: %.3f", result.composite_score)
        return {"success": True, "composite_score": result.composite_score}
    else:
        logger.warning("Weekly pulse calculation failed")
        return {"success": False}
