"""
Celery Tasks for Backtest Module.

异步执行回测任务。
"""

import logging
from datetime import date
from typing import Any, Dict, Optional

from celery import shared_task
from django.utils import timezone

from ..domain.entities import DEFAULT_PUBLICATION_LAGS, BacktestConfig, PITDataConfig
from ..domain.services import BacktestEngine, PITDataProcessor
from ..infrastructure.repositories import DjangoBacktestRepository

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=600,
    time_limit=3600,
    soft_time_limit=3300,
)
def run_backtest_task(
    self,
    backtest_id: int,
    config_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    异步执行回测任务

    Args:
        backtest_id: 回测 ID
        config_dict: 回测配置字典

    Returns:
        Dict: 任务结果
    """
    repository = DjangoBacktestRepository()
    errors = []
    warnings = []

    try:
        # 1. 获取回测记录
        backtest = repository.get_backtest_by_id(backtest_id)
        if not backtest:
            raise ValueError(f"Backtest {backtest_id} not found")

        # 2. 创建配置
        config = BacktestConfig(
            start_date=date.fromisoformat(config_dict['start_date']),
            end_date=date.fromisoformat(config_dict['end_date']),
            initial_capital=config_dict['initial_capital'],
            rebalance_frequency=config_dict['rebalance_frequency'],
            use_pit_data=config_dict.get('use_pit_data', False),
            transaction_cost_bps=config_dict.get('transaction_cost_bps', 10.0),
        )

        # 3. 标记为运行中
        repository.update_status(backtest_id, 'running')

        # 4. 获取数据获取函数（需要在实际使用时注入）
        # 这里使用模拟数据，实际应用中需要从外部传入
        def get_regime(as_of_date: date) -> dict | None:
            """
            获取指定日期的 Regime 数据

            实际应用中应该从数据库查询或调用 Regime 服务
            """
            from apps.regime.infrastructure.repositories import DjangoRegimeRepository
            regime_repo = DjangoRegimeRepository()
            snapshot = regime_repo.get_regime_by_date(as_of_date)
            if snapshot:
                return {
                    'dominant_regime': snapshot.dominant_regime,
                    'confidence': snapshot.confidence,
                    'growth_momentum_z': snapshot.growth_momentum_z,
                    'inflation_momentum_z': snapshot.inflation_momentum_z,
                    'distribution': snapshot.distribution,
                }
            return None

        def get_asset_price(asset_class: str, as_of_date: date) -> float | None:
            """
            获取指定资产在指定日期的价格

            实际应用中应该从数据库查询或调用外部数据源
            """
            from shared.config.secrets import get_secrets

            from ..infrastructure.adapters import create_default_price_adapter

            try:
                token = get_secrets().data_sources.tushare_token
            except Exception:
                token = None

            adapter = create_default_price_adapter(tushare_token=token)
            return adapter.get_price(asset_class, as_of_date)

        # 5. 创建 PIT 处理器（如果需要）
        pit_processor = None
        if config.use_pit_data:
            pit_processor = PITDataProcessor(DEFAULT_PUBLICATION_LAGS)

        # 6. 创建并运行回测引擎
        engine = BacktestEngine(
            config=config,
            get_regime_func=get_regime,
            get_asset_price_func=get_asset_price,
            pit_processor=pit_processor,
        )

        result = engine.run()
        warnings.extend(result.warnings)

        # 7. 保存结果
        repository.save_result(backtest_id, result)

        logger.info(f"Backtest {backtest_id} completed successfully via Celery")

        return {
            'backtest_id': backtest_id,
            'status': 'completed',
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'max_drawdown': result.max_drawdown,
            'sharpe_ratio': result.sharpe_ratio,
        }

    except Exception as e:
        logger.exception(f"Backtest task {backtest_id} failed: {e}")

        # 标记为失败
        repository.update_status(backtest_id, 'failed', str(e))

        # 重试逻辑
        if self.request.retries < self.max_retries:
            try:
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
            except Exception as retry_error:
                logger.warning(f"Retry {self.request.retries + 1} scheduled for backtest {backtest_id}")

        return {
            'backtest_id': backtest_id,
            'status': 'failed',
            'error': str(e),
        }


@shared_task(
    name='backtest.cleanup_old_backtests',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def cleanup_old_backtests(self, days_old: int = 90) -> int:
    """
    清理旧的回测记录

    Args:
        days_old: 保留天数，超过此天数的已完成回测将被删除

    Returns:
        int: 删除的记录数
    """
    from datetime import timedelta

    from django.utils import timezone

    repository = DjangoBacktestRepository()
    cutoff_date = timezone.now() - timedelta(days=days_old)

    # 获取所有回测
    backtests = repository.get_all_backtests()

    deleted_count = 0
    for backtest in backtests:
        # 只删除已完成的旧回测
        if backtest.status == 'completed' and backtest.created_at < cutoff_date:
            if repository.delete_backtest(backtest.id):
                deleted_count += 1
                logger.info(f"Deleted old backtest {backtest.id}")

    logger.info(f"Cleanup completed: {deleted_count} old backtests deleted")
    return deleted_count


@shared_task(
    name='backtest.generate_backtest_report',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def generate_backtest_report(self, backtest_id: int) -> dict[str, Any]:
    """
    生成回测报告

    Args:
        backtest_id: 回测 ID

    Returns:
        Dict: 报告数据
    """
    repository = DjangoBacktestRepository()
    backtest = repository.get_backtest_by_id(backtest_id)

    if not backtest:
        return {'error': f'Backtest {backtest_id} not found'}

    if backtest.status != 'completed':
        return {'error': f'Backtest {backtest_id} is not completed'}

    # 转换为 Domain 实体
    domain_result = DjangoBacktestRepository.to_domain_entity(backtest)

    # 生成报告
    report = {
        'summary': domain_result.to_summary_dict(),
        'regime_analysis': _analyze_regime_performance(domain_result.regime_history),
        'trade_analysis': _analyze_trades(domain_result.trades),
        'risk_metrics': {
            'max_drawdown': domain_result.max_drawdown,
            'sharpe_ratio': domain_result.sharpe_ratio,
        },
    }

    return report


def _analyze_regime_performance(regime_history: list) -> dict[str, Any]:
    """分析各 Regime 下的表现"""
    if not regime_history:
        return {}

    regime_returns = {}
    for entry in regime_history:
        regime = entry.get('regime', 'Unknown')
        value = entry.get('portfolio_value', 0)
        if regime not in regime_returns:
            regime_returns[regime] = []
        regime_returns[regime].append(value)

    analysis = {}
    for regime, values in regime_returns.items():
        if len(values) >= 2:
            total_return = (values[-1] - values[0]) / values[0] if values[0] > 0 else 0
            analysis[regime] = {
                'count': len(values),
                'total_return': total_return,
                'avg_value': sum(values) / len(values),
            }

    return analysis


def _analyze_trades(trades: list) -> dict[str, Any]:
    """分析交易记录"""
    if not trades:
        return {}

    buy_trades = [t for t in trades if t.action == 'buy']
    sell_trades = [t for t in trades if t.action == 'sell']

    total_cost = sum(t.cost for t in trades)
    total_notional = sum(t.notional for t in trades)

    return {
        'total_trades': len(trades),
        'buy_trades': len(buy_trades),
        'sell_trades': len(sell_trades),
        'total_cost': total_cost,
        'total_notional': total_notional,
        'cost_ratio': total_cost / total_notional if total_notional > 0 else 0,
    }
