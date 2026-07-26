"""
板块分析模块 - Celery 定时任务

遵循项目架构约束：
- 编排用例执行
- 不包含业务逻辑
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Protocol, TypedDict, TypeVar, cast

from celery import shared_task

from .repository_provider import get_sector_adapter, get_sector_repository
from .use_cases import (
    AnalyzeSectorRotationRequest,
    AnalyzeSectorRotationUseCase,
    UpdateSectorDataRequest,
    UpdateSectorDataUseCase,
)

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
    """Narrow Celery's untyped decorator while preserving task result types."""

    decorator = shared_task(*decorator_args, **decorator_kwargs)
    return cast(
        Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]],
        decorator,
    )


class SectorDataUpdateTaskResult(TypedDict):
    """Serialized sector update result returned to Celery callers."""

    success: bool
    updated_count: int
    error: str | None
    error_code: str | None


class SectorScoreTaskPayload(TypedDict):
    """Serialized sector ranking row returned to Celery callers."""

    rank: int
    sector_code: str
    sector_name: str
    total_score: float
    momentum_score: float
    rs_score: float
    regime_fit_score: float


class SectorRotationTaskResult(TypedDict):
    """Serialized sector rotation result returned to Celery callers."""

    success: bool
    regime: str
    analysis_date: str
    top_sectors: list[SectorScoreTaskPayload]
    error: str | None
    error_code: str | None
    status: str
    data_source: str
    warning_message: str | None
    warning_detail: str | None


@_typed_shared_task(
    name="sector.update_daily_data",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def update_daily_sector_data(
    _task: object,
    level: str = "SW1",
) -> SectorDataUpdateTaskResult:
    """
    每日更新板块指数数据

    建议调度：每日收盘后执行（18:00）

    Args:
        level: 板块级别（SW1/SW2/SW3）

    Returns:
        更新结果字典
    """
    end_date = date.today()
    request = UpdateSectorDataRequest(
        level=level,
        start_date=(end_date - timedelta(days=7)).isoformat(),
        end_date=end_date.isoformat(),
    )
    sector_repo = get_sector_repository()
    adapter = get_sector_adapter()
    result = UpdateSectorDataUseCase(sector_repo, adapter).execute(request)

    return {
        "success": result.success,
        "updated_count": result.updated_count,
        "error": result.error,
        "error_code": result.error_code,
    }


@_typed_shared_task(
    name="sector.analyze_rotation",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def analyze_sector_rotation(
    _task: object,
    regime: str | None = None,
) -> SectorRotationTaskResult:
    """
    分析板块轮动

    建议调度：每日收盘后执行（18:30）

    Args:
        regime: Regime 名称（如果不提供，自动获取最新）

    Returns:
        分析结果字典
    """
    request = AnalyzeSectorRotationRequest(
        regime=regime,
        lookback_days=20,
        top_n=10,
    )
    result = AnalyzeSectorRotationUseCase(get_sector_repository()).execute(request)
    top_sectors = [
        SectorScoreTaskPayload(
            rank=score.rank,
            sector_code=score.sector_code,
            sector_name=score.sector_name,
            total_score=round(score.total_score, 2),
            momentum_score=round(score.momentum_score, 2),
            rs_score=round(score.relative_strength_score, 2),
            regime_fit_score=round(score.regime_fit_score, 2),
        )
        for score in result.top_sectors
    ]
    return {
        "success": result.success,
        "regime": result.regime,
        "analysis_date": result.analysis_date.isoformat(),
        "top_sectors": top_sectors,
        "error": result.error,
        "error_code": result.error_code,
        "status": result.status,
        "data_source": result.data_source,
        "warning_message": result.warning_message,
        "warning_detail": result.warning_detail,
    }
