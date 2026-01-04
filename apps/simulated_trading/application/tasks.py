"""
模拟盘交易 Celery 任务

Application层异步任务：
- 每日自动交易执行
- 持仓价格更新
- 绩效定期重算
"""
import logging
from datetime import date, datetime
from typing import Dict, Any, Optional
from dataclasses import replace

from celery import shared_task
from celery.schedules import crontab

from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoPositionRepository,
    DjangoTradeRepository,
)
from apps.simulated_trading.infrastructure.market_data_provider import MarketDataProvider
from apps.simulated_trading.application.asset_pool_query_service import AssetPoolQueryService

logger = logging.getLogger(__name__)


# ============================================================================
# 核心定时任务
# ============================================================================

@shared_task(bind=True, max_retries=3)
def daily_auto_trading_task(
    self,
    trade_date: Optional[str] = None,
    account_ids: Optional[list] = None,
) -> Dict[str, Any]:
    """
    每日自动交易任务

    Celery Beat 配置建议：
    - 执行时间：每个交易日 15:30（收盘后）
    - crontab: hour=15, minute=30, day_of_week='mon-fri'

    Args:
        trade_date: 交易日期（YYYY-MM-DD，默认今天）
        account_ids: 指定账户ID列表（None表示全部活跃账户）

    Returns:
        任务结果字典
    """
    # 1. 确定交易日期
    target_date = date.fromisoformat(trade_date) if trade_date else date.today()

    logger.info(f"=" * 60)
    logger.info(f"模拟盘自动交易任务开始: {target_date}")
    logger.info(f"=" * 60)

    try:
        # 2. 初始化依赖
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        trade_repo = DjangoTradeRepository()

        buy_use_case = ExecuteBuyOrderUseCase(account_repo, position_repo, trade_repo)
        sell_use_case = ExecuteSellOrderUseCase(account_repo, position_repo, trade_repo)
        performance_use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)

        market_data = MarketDataProvider(cache_ttl_minutes=60)  # 1小时缓存
        asset_pool_service = AssetPoolQueryService()

        # 3. 创建引擎
        engine = AutoTradingEngine(
            account_repo=account_repo,
            position_repo=position_repo,
            trade_repo=trade_repo,
            buy_use_case=buy_use_case,
            sell_use_case=sell_use_case,
            performance_use_case=performance_use_case,
            asset_pool_service=asset_pool_service,
            market_data_provider=market_data,
        )

        # 4. 执行交易
        results = engine.run_daily_trading(target_date)

        # 5. 汇总统计
        total_accounts = len(results)
        total_buy_count = sum(r['buy_count'] for r in results.values())
        total_sell_count = sum(r['sell_count'] for r in results.values())

        logger.info(f"=" * 60)
        logger.info(f"模拟盘自动交易任务完成")
        logger.info(f"  处理账户: {total_accounts} 个")
        logger.info(f"  总买入: {total_buy_count} 笔")
        logger.info(f"  总卖出: {total_sell_count} 笔")
        logger.info(f"=" * 60)

        return {
            'success': True,
            'trade_date': target_date.isoformat(),
            'total_accounts': total_accounts,
            'results': results,
            'summary': {
                'total_buy_count': total_buy_count,
                'total_sell_count': total_sell_count,
            }
        }

    except Exception as e:
        logger.exception(f"自动交易任务执行失败: {e}")

        # 重试逻辑
        if self.request.retries < self.max_retries:
            try:
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
            except Exception as retry_error:
                logger.warning(f"任务将在 {2 ** self.request.retries} 分钟后重试")

        return {
            'success': False,
            'trade_date': target_date.isoformat(),
            'error': str(e),
        }


@shared_task
def update_position_prices_task(account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    更新持仓价格任务

    每日收盘后更新所有持仓的当前价格，用于计算浮盈浮亏。

    建议执行时间：每个交易日 16:00（收盘后30分钟）

    Args:
        account_id: 指定账户ID（None表示全部账户）

    Returns:
        更新结果
    """
    logger.info(f"开始更新持仓价格: account_id={account_id}")

    try:
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        market_data = MarketDataProvider()

        # 获取账户列表
        if account_id:
            accounts = [account_repo.get_by_id(account_id)]
            if not accounts[0]:
                return {'success': False, 'error': f'账户不存在: {account_id}'}
        else:
            accounts = account_repo.get_active_accounts()

        updated_count = 0
        error_count = 0

        for account in accounts:
            positions = position_repo.get_by_account(account.account_id)

            for position in positions:
                try:
                    # 获取最新价格
                    current_price = market_data.get_latest_price(position.asset_code)

                    if current_price is None:
                        logger.warning(f"无法获取 {position.asset_code} 价格，跳过")
                        error_count += 1
                        continue

                    # 更新持仓价格和市值
                    from apps.simulated_trading.domain.entities import Position
                    updated_position = Position(
                        position_id=position.position_id,
                        account_id=position.account_id,
                        asset_code=position.asset_code,
                        asset_name=position.asset_name,
                        asset_type=position.asset_type,
                        quantity=position.quantity,
                        available_quantity=position.available_quantity,
                        avg_cost=position.avg_cost,
                        total_cost=position.total_cost,
                        current_price=current_price,
                        market_value=position.quantity * current_price,
                        unrealized_pnl=(current_price - position.avg_cost) * position.quantity,
                        unrealized_pnl_pct=((current_price - position.avg_cost) / position.avg_cost) * 100
                        if position.avg_cost > 0 else 0.0,
                        first_buy_date=position.first_buy_date,
                        last_update_date=date.today(),
                        signal_id=position.signal_id,
                        entry_reason=position.entry_reason,
                    )
                    position_repo.save(updated_position)
                    updated_count += 1

                except Exception as e:
                    logger.error(f"更新持仓 {position.asset_code} 失败: {e}")
                    error_count += 1

            # 更新账户总市值
            positions = position_repo.get_by_account(account.account_id)
            total_market_value = sum(p.market_value for p in positions)
            updated_account = replace(
                account,
                current_market_value=total_market_value,
                total_value=account.current_cash + total_market_value
            )
            account_repo.save(updated_account)

        logger.info(f"持仓价格更新完成: {updated_count} 个成功, {error_count} 个失败")

        return {
            'success': True,
            'updated_count': updated_count,
            'error_count': error_count,
        }

    except Exception as e:
        logger.exception(f"更新持仓价格任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


@shared_task
def calculate_all_performance_task(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """
    全量绩效计算任务

    重新计算所有活跃账户的绩效指标。

    建议执行时间：每周日凌晨 2:00

    Args:
        trade_date: 计算日期（默认今天）

    Returns:
        计算结果
    """
    target_date = date.fromisoformat(trade_date) if trade_date else date.today()

    logger.info(f"开始全量绩效计算: {target_date}")

    try:
        calculator = PerformanceCalculator()
        account_repo = DjangoSimulatedAccountRepository()
        accounts = account_repo.get_active_accounts()

        results = []
        for account in accounts:
            try:
                metrics = calculator.calculate_and_update_performance(
                    account_id=account.account_id,
                    trade_date=target_date
                )
                results.append({
                    'account_id': account.account_id,
                    'account_name': account.account_name,
                    'total_return': metrics.get('total_return', 0.0),
                    'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                    'max_drawdown': metrics.get('max_drawdown', 0.0),
                    'win_rate': metrics.get('win_rate', 0.0),
                })
            except Exception as e:
                logger.error(f"计算账户 {account.account_id} 绩效失败: {e}")

        logger.info(f"全量绩效计算完成: {len(results)} 个账户")

        return {
            'success': True,
            'trade_date': target_date.isoformat(),
            'account_count': len(results),
            'results': results,
        }

    except Exception as e:
        logger.exception(f"全量绩效计算任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


# ============================================================================
# 维护任务
# ============================================================================

@shared_task
def cleanup_inactive_accounts_task(inactive_days: int = 180) -> Dict[str, Any]:
    """
    清理不活跃账户任务

    停用长期无交易的模拟账户。

    建议执行时间：每周日凌晨 3:00

    Args:
        inactive_days: 不活跃天数阈值

    Returns:
        清理结果
    """
    from datetime import timedelta

    logger.info(f"开始清理不活跃账户: {inactive_days} 天无交易")

    try:
        account_repo = DjangoSimulatedAccountRepository()
        cutoff_date = date.today() - timedelta(days=inactive_days)

        accounts = account_repo.get_active_accounts()
        deactivated_count = 0

        for account in accounts:
            # 检查最后交易日期
            if account.last_trade_date and account.last_trade_date < cutoff_date:
                # 停用账户
                updated_account = replace(
                    account,
                    is_active=False,
                    auto_trading_enabled=False
                )
                account_repo.save(updated_account)
                deactivated_count += 1
                logger.info(f"停用不活跃账户: {account.account_name} (最后交易: {account.last_trade_date})")

        logger.info(f"清理完成: {deactivated_count} 个账户被停用")

        return {
            'success': True,
            'deactivated_count': deactivated_count,
        }

    except Exception as e:
        logger.exception(f"清理不活跃账户任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


@shared_task
def send_performance_summary_task(account_ids: Optional[list] = None) -> Dict[str, Any]:
    """
    发送绩效摘要任务

    生成并发送账户绩效摘要（可集成邮件/消息推送）。

    建议执行时间：每个交易日 17:00

    Args:
        account_ids: 指定账户ID列表（None表示全部活跃账户）

    Returns:
        发送结果
    """
    logger.info(f"开始生成绩效摘要")

    try:
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        trade_repo = DjangoTradeRepository()

        # 获取账户列表
        if account_ids:
            accounts = []
            for acc_id in account_ids:
                acc = account_repo.get_by_id(acc_id)
                if acc:
                    accounts.append(acc)
        else:
            accounts = account_repo.get_active_accounts()

        # 生成摘要
        use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)
        summaries = []

        for account in accounts:
            result = use_case.execute(account.account_id)
            summaries.append({
                'account_id': account.account_id,
                'account_name': account.account_name,
                'total_value': float(account.total_value),
                'total_return': result['performance'].get('total_return', 0.0),
                'max_drawdown': result['performance'].get('max_drawdown', 0.0),
                'sharpe_ratio': result['performance'].get('sharpe_ratio', 0.0),
                'win_rate': result['performance'].get('win_rate', 0.0),
                'total_trades': result['total_trades'],
                'total_positions': result['total_positions'],
            })

        logger.info(f"绩效摘要生成完成: {len(summaries)} 个账户")

        # TODO: 实现邮件/消息推送
        # 目前只记录日志，实际部署时需要集成邮件服务

        return {
            'success': True,
            'summaries': summaries,
        }

    except Exception as e:
        logger.exception(f"发送绩效摘要任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }
