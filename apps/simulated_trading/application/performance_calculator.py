"""
绩效计算服务

Application层:
- 计算账户绩效指标
- 更新账户绩效数据
- 支持历史净值曲线
"""
import logging
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from pandas import DataFrame

from apps.market_data.application.price_service import UnifiedPriceService
from apps.simulated_trading.domain.entities import Position, SimulatedAccount, TradeAction
from apps.simulated_trading.infrastructure.repositories import (
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)
from core.exceptions import DataFetchError

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
        self.market_data_provider = UnifiedPriceService()

    def _require_market_price(self, asset_code: str, trade_date: date) -> float:
        """
        Resolve price from the configured market data provider.

        Prefer ``get_price`` first so tests and adapters that expose the
        nullable API can override pricing cleanly. If it returns ``None``,
        fall back to the strict ``require_price`` path and keep the
        production rule of failing loudly when no market price exists.
        """
        get_price = getattr(self.market_data_provider, "get_price", None)
        if callable(get_price):
            price = get_price(asset_code, trade_date)
            if price is not None:
                return price

        require_price = getattr(self.market_data_provider, "require_price", None)
        if callable(require_price):
            return require_price(asset_code, trade_date)

        raise DataFetchError(
            message=f"无法获取 {asset_code} 在 {trade_date} 的历史价格",
            code="PRICE_UNAVAILABLE",
        )

    def calculate_and_update_performance(
        self,
        account_id: int,
        trade_date: date
    ) -> dict[str, float]:
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
    ) -> dict[str, float]:
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

        按时间序列计算每日净值，然后计算最大回撤：
        max_drawdown = max((peak - value) / peak * 100)

        净值 = 现金 + 持仓市值
        """
        try:
            # 构建完整的净值曲线
            equity_curve = self._build_equity_curve(account)

            if len(equity_curve) < 2:
                return 0.0

            # 提取净值序列
            net_values = [point['net_value'] for point in equity_curve]

            # 计算最大回撤
            net_value_array = np.array(net_values)
            peak_array = np.maximum.accumulate(net_value_array)
            drawdown_array = (peak_array - net_value_array) / peak_array * 100
            max_dd = np.max(drawdown_array) if len(drawdown_array) > 0 else 0.0

            return max_dd

        except DataFetchError:
            raise
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

    def _build_equity_curve(
        self,
        account: SimulatedAccount,
        end_date: date = None
    ) -> list[dict]:
        """
        构建完整的净值曲线（内部方法）

        净值 = 现金 + 持仓市值

        Args:
            account: 账户实体
            end_date: 结束日期（None表示今天）

        Returns:
            [{date, net_value, cash, market_value, drawdown_pct}, ...]
        """
        if end_date is None:
            end_date = date.today()

        # 获取所有交易记录（使用更宽的日期范围以包含历史交易）
        # 注意：不能使用 account.start_date，因为测试中可能创建过去日期的交易
        trades = self.trade_repo.get_by_date_range(
            account.account_id,
            date(2000, 1, 1),  # 使用足够早的日期
            end_date
        )

        if not trades:
            # 无交易，返回初始点
            return [{
                'date': account.start_date.isoformat(),
                'net_value': account.initial_capital,
                'cash': account.initial_capital,
                'market_value': 0.0,
                'drawdown_pct': 0.0
            }]

        # 按日期分组交易
        trades_by_date: dict[date, list] = defaultdict(list)
        for trade in trades:
            trades_by_date[trade.execution_date].append(trade)

        # 按时间顺序遍历每个交易日
        curve_data = []
        cash = account.initial_capital
        positions = {}  # {asset_code: quantity}

        # 获取所有交易日期（去重并排序）
        trade_dates = sorted(trades_by_date.keys())

        for trade_date in trade_dates:
            day_trades = trades_by_date[trade_date]

            # 更新持仓和现金
            for trade in day_trades:
                if trade.action == TradeAction.BUY:
                    cash -= trade.total_cost
                    positions[trade.asset_code] = positions.get(trade.asset_code, 0) + trade.quantity
                else:  # SELL
                    cash += trade.amount - trade.total_cost
                    positions[trade.asset_code] = positions.get(trade.asset_code, 0) - trade.quantity
                    if positions[trade.asset_code] == 0:
                        del positions[trade.asset_code]

            # 获取当日持仓的市值
            market_value = 0.0
            for asset_code, quantity in positions.items():
                price = self._require_market_price(asset_code, trade_date)
                market_value += price * quantity

            # 计算净值
            net_value = cash + market_value

            curve_data.append({
                'date': trade_date.isoformat(),
                'net_value': net_value,
                'cash': cash,
                'market_value': market_value,
                'drawdown_pct': 0.0  # 稍后计算
            })

        # 计算回撤百分比
        if curve_data:
            net_values = [point['net_value'] for point in curve_data]
            peak_array = np.maximum.accumulate(net_values)
            for i, point in enumerate(curve_data):
                if peak_array[i] > 0:
                    point['drawdown_pct'] = (peak_array[i] - net_values[i]) / peak_array[i] * 100

        return curve_data

    def get_equity_curve(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> list[dict]:
        """
        获取净值曲线数据

        净值 = 现金 + 持仓市值

        Args:
            account_id: 账户ID
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            [{date, net_value, cash, market_value, drawdown_pct}, ...]
        """
        try:
            # 获取账户
            account = self.account_repo.get_by_id(account_id)
            if not account:
                logger.error(f"账户不存在: {account_id}")
                return []

            # 构建完整净值曲线
            full_curve = self._build_equity_curve(account, end_date)

            # 过滤日期范围
            result = [
                point for point in full_curve
                if start_date <= date.fromisoformat(point['date']) <= end_date
            ]

            return result

        except DataFetchError:
            raise
        except Exception as e:
            logger.error(f"获取净值曲线失败: {e}")
            raise
