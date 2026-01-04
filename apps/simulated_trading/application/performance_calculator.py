"""
绩效计算服务

Application层:
- 计算账户绩效指标
- 更新账户绩效数据
- 支持历史净值曲线
"""
import logging
from typing import List, Dict, Optional
from datetime import date, datetime
import numpy as np
from pandas import DataFrame
from dataclasses import replace

from apps.simulated_trading.domain.entities import SimulatedAccount, Position
from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
    DjangoPositionRepository
)

logger = logging.getLogger(__name__)


class PerformanceCalculator:
    """
    绩效计算器

    计算账户的关键绩效指标：
    - 总收益率
    - 年化收益率
    - 最大回撤
    - 夏普比率
    - 胜率
    """

    def __init__(self):
        self.account_repo = DjangoSimulatedAccountRepository()
        self.trade_repo = DjangoTradeRepository()
        self.position_repo = DjangoPositionRepository()

    def calculate_and_update_performance(
        self,
        account_id: int,
        trade_date: date
    ) -> Dict[str, float]:
        """
        计算并更新账户绩效

        Args:
            account_id: 账户ID
            trade_date: 计算日期

        Returns:
            绩效指标字典
        """
        # 1. 获取账户
        account = self.account_repo.get_by_id(account_id)
        if not account:
            logger.error(f"账户不存在: {account_id}")
            return {}

        # 2. 计算绩效指标
        metrics = self._calculate_metrics(account, trade_date)

        # 3. 更新账户
        updated_account = replace(
            account,
            total_return=metrics.get('total_return', 0.0),
            annual_return=metrics.get('annual_return', 0.0),
            max_drawdown=metrics.get('max_drawdown', 0.0),
            sharpe_ratio=metrics.get('sharpe_ratio', 0.0),
            win_rate=metrics.get('win_rate', 0.0),
            winning_trades=metrics.get('winning_trades', 0)
        )
        self.account_repo.save(updated_account)

        logger.info(
            f"更新账户绩效: {account.account_name} - "
            f"总收益率: {account.total_return:.2f}%, "
            f"最大回撤: {account.max_drawdown:.2f}%, "
            f"夏普比率: {account.sharpe_ratio:.2f}"
        )

        return metrics

    def _calculate_metrics(
        self,
        account: SimulatedAccount,
        trade_date: date
    ) -> Dict[str, float]:
        """计算绩效指标"""
        metrics = {}

        # 1. 总收益率
        metrics['total_return'] = self._calculate_total_return(account)

        # 2. 年化收益率
        metrics['annual_return'] = self._calculate_annual_return(account, trade_date)

        # 3. 最大回撤
        metrics['max_drawdown'] = self._calculate_max_drawdown(account)

        # 4. 夏普比率
        metrics['sharpe_ratio'] = self._calculate_sharpe_ratio(account)

        # 5. 胜率和盈利交易数
        win_rate, winning_trades = self._calculate_win_rate(account)
        metrics['win_rate'] = win_rate
        metrics['winning_trades'] = winning_trades

        return metrics

    def _calculate_total_return(self, account: SimulatedAccount) -> float:
        """
        计算总收益率

        total_return = (total_value - initial_capital) / initial_capital * 100
        """
        if account.initial_capital > 0:
            return ((account.total_value - account.initial_capital) / account.initial_capital) * 100
        return 0.0

    def _calculate_annual_return(
        self,
        account: SimulatedAccount,
        trade_date: date
    ) -> float:
        """
        计算年化收益率

        annual_return = (1 + total_return/100)^(365/days) - 1
        """
        if account.initial_capital <= 0:
            return 0.0

        days = (trade_date - account.start_date).days
        if days <= 0:
            return 0.0

        total_return = account.total_return / 100.0  # 转为小数
        annual_return = ((1 + total_return) ** (365.0 / days) - 1) * 100

        return annual_return

    def _calculate_max_drawdown(self, account: SimulatedAccount) -> float:
        """
        计算最大回撤

        max_drawdown = max((peak - value) / peak * 100)
        """
        try:
            # 获取交易历史，按时间顺序
            trades = self.trade_repo.get_by_date_range(
                account.account_id,
                account.start_date,
                date.today()
            )

            if not trades:
                return 0.0

            # 构建净值曲线
            net_value_series = []
            cash = account.initial_capital
            positions = {}  # {asset_code: quantity}

            for trade in sorted(trades, key=lambda t: t.execution_date):
                if trade.action.value == 'buy':
                    # 买入：现金减少，持仓增加
                    cash -= trade.total_cost
                    positions[trade.asset_code] = positions.get(trade.asset_code, 0) + trade.quantity
                else:  # sell
                    # 卖出：现金增加，持仓减少
                    cash += trade.amount - trade.total_cost  # 净收入
                    positions[trade.asset_code] = positions.get(trade.asset_code, 0) - trade.quantity

                # 计算当前总资产（简化：只用现金估算）
                # TODO: 应该用持仓市值，但需要历史价格数据
                net_value = cash
                net_value_series.append(net_value)

            if len(net_value_series) < 2:
                return 0.0

            # 计算最大回撤
            net_value_array = np.array(net_value_series)
            peak_array = np.maximum.accumulate(net_value_array)
            drawdown_array = (peak_array - net_value_array) / peak_array * 100
            max_dd = np.max(drawdown_array) if len(drawdown_array) > 0 else 0.0

            return max_dd

        except Exception as e:
            logger.error(f"计算最大回撤失败: {e}")
            return 0.0

    def _calculate_sharpe_ratio(self, account: SimulatedAccount) -> float:
        """
        计算夏普比率

        sharpe = (annual_return - risk_free_rate) / annual_volatility
        """
        try:
            # 获取交易历史
            trades = self.trade_repo.get_by_date_range(
                account.account_id,
                account.start_date,
                date.today()
            )

            if len(trades) < 2:
                return 0.0

            # 计算每笔交易的收益率序列
            returns = []
            for trade in trades:
                if trade.realized_pnl_pct is not None:
                    returns.append(trade.realized_pnl_pct)

            if len(returns) < 2:
                return 0.0

            # 年化收益率
            mean_return = np.mean(returns)
            std_return = np.std(returns)

            if std_return == 0:
                return 0.0

            # 假设无风险利率为3%
            risk_free_rate = 3.0

            # 夏普比率（年化）
            # 简化计算：使用交易收益率的均值/标准差
            sharpe = (mean_return * 252 ** 0.5) / (std_return * 252 ** 0.5) if std_return > 0 else 0

            return sharpe

        except Exception as e:
            logger.error(f"计算夏普比率失败: {e}")
            return 0.0

    def _calculate_win_rate(self, account: SimulatedAccount) -> tuple:
        """
        计算胜率

        win_rate = winning_trades / total_trades * 100

        Returns:
            (win_rate, winning_trades)
        """
        try:
            trades = self.trade_repo.get_by_date_range(
                account.account_id,
                account.start_date,
                date.today()
            )

            if not trades:
                return 0.0, 0

            # 统计盈利交易
            winning_trades = sum(
                1 for t in trades
                if t.realized_pnl and t.realized_pnl > 0
            )

            win_rate = (winning_trades / len(trades)) * 100

            return win_rate, winning_trades

        except Exception as e:
            logger.error(f"计算胜率失败: {e}")
            return 0.0, 0

    def get_equity_curve(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        获取净值曲线数据

        Args:
            account_id: 账户ID
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            [{date, net_value, cash, market_value}, ...]
        """
        try:
            trades = self.trade_repo.get_by_date_range(
                account_id,
                start_date,
                end_date
            )

            # 按日期分组统计
            equity_data = {}
            cash = 0
            for trade in trades:
                trade_date = trade.execution_date
                if trade_date not in equity_data:
                    equity_data[trade_date] = {
                        'date': trade_date.isoformat(),
                        'trades_count': 0,
                        'pnl': 0.0
                    }

                if trade.action.value == 'buy':
                    equity_data[trade_date]['trades_count'] += 1
                    equity_data[trade_date]['pnl'] -= trade.total_cost
                else:  # sell
                    equity_data[trade_date]['trades_count'] += 1
                    equity_data[trade_date]['pnl'] += (trade.amount - trade.total_cost)

            # 转换为列表并排序
            result = []
            for date_str, data in sorted(equity_data.items()):
                result.append({
                    'date': data['date'],
                    'net_value': 0.0,  # TODO: 需要累计计算
                    'trades_count': data['trades_count'],
                    'daily_pnl': data['pnl']
                })

            return result

        except Exception as e:
            logger.error(f"获取净值曲线失败: {e}")
            return []
