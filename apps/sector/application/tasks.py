"""
板块分析模块 - Celery 定时任务

遵循项目架构约束：
- 编排用例执行
- 不包含业务逻辑
"""

from celery import shared_task
from datetime import date, timedelta

from .use_cases import UpdateSectorDataUseCase, AnalyzeSectorRotationUseCase
from ..infrastructure.repositories import DjangoSectorRepository
from ..infrastructure.adapters.akshare_sector_adapter import AKShareSectorAdapter


@shared_task(
    name='sector.update_daily_data',
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def update_daily_sector_data(self, level: str = 'SW1'):
    """
    每日更新板块指数数据

    建议调度：每日收盘后执行（18:00）

    Args:
        level: 板块级别（SW1/SW2/SW3）

    Returns:
        更新结果字典
    """
    try:
        # 初始化
        sector_repo = DjangoSectorRepository()
        adapter = AKShareSectorAdapter()
        use_case = UpdateSectorDataUseCase(sector_repo, adapter)

        # 获取最近一周的数据
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        # 执行更新
        from .use_cases import UpdateSectorDataRequest
        result = use_case.execute(
            UpdateSectorDataRequest(
                level=level,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
        )

        return {
            'success': result.success,
            'updated_count': result.updated_count,
            'error': result.error
        }

    except Exception as e:
        return {
            'success': False,
            'updated_count': 0,
            'error': str(e)
        }


@shared_task(
    name='sector.analyze_rotation',
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def analyze_sector_rotation(self, regime: str = None):
    """
    分析板块轮动

    建议调度：每日收盘后执行（18:30）

    Args:
        regime: Regime 名称（如果不提供，自动获取最新）

    Returns:
        分析结果字典
    """
    try:
        # 初始化
        sector_repo = DjangoSectorRepository()
        use_case = AnalyzeSectorRotationUseCase(sector_repo)

        # 执行分析
        from .use_cases import AnalyzeSectorRotationRequest
        result = use_case.execute(
            AnalyzeSectorRotationRequest(
                regime=regime,
                lookback_days=20,
                top_n=10
            )
        )

        if not result.success:
            return {
                'success': False,
                'error': result.error
            }

        # 格式化结果
        top_sectors = [
            {
                'rank': s.rank,
                'sector_code': s.sector_code,
                'sector_name': s.sector_name,
                'total_score': round(s.total_score, 2),
                'momentum_score': round(s.momentum_score, 2),
                'rs_score': round(s.relative_strength_score, 2),
                'regime_fit_score': round(s.regime_fit_score, 2)
            }
            for s in result.top_sectors
        ]

        return {
            'success': True,
            'regime': result.regime,
            'analysis_date': result.analysis_date.isoformat(),
            'top_sectors': top_sectors
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
