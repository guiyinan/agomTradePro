"""
每日净值记录服务

Application层:
- 记录账户每日净值数据
- 计算并更新绩效指标
- 支持净值曲线查询和最大回撤计算
"""
import logging
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from apps.simulated_trading.application.ports import DailyNetValueRepositoryProtocol
from apps.simulated_trading.domain.entities import SimulatedAccount
from apps.simulated_trading.infrastructure.repositories import (
    DjangoDailyNetValueRepository,
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)

logger = logging.getLogger(__name__)


class DailyNetValueService:
    """
    每日净值记录服务

    职责:
    1. 记录账户每日净值（现金+持仓市值）
    2. 计算日收益率、累计收益率、回撤
    3. 更新账户绩效指标
    4. 提供净值曲线查询
    """

    def __init__(
        self,
        account_repo: DjangoSimulatedAccountRepository | None = None,
        position_repo: DjangoPositionRepository | None = None,
        trade_repo: DjangoTradeRepository | None = None,
        daily_net_value_repo: DailyNetValueRepositoryProtocol | None = None,
    ):
        self.account_repo = account_repo or DjangoSimulatedAccountRepository()
        self.position_repo = position_repo or DjangoPositionRepository()
        self.trade_repo = trade_repo or DjangoTradeRepository()
        self.daily_net_value_repo = daily_net_value_repo or DjangoDailyNetValueRepository()

    def record_and_update_performance(
        self,
        account_id: int,
        record_date: date
    ) -> dict[str, float]:
        """
        记录当日净值并更新绩效指标

        流程:
        1. 获取账户和持仓
        2. 计算当日净值
        3. 记录净值数据
        4. 计算绩效指标
        5. 更新账户实体

        Args:
            account_id: 账户ID
            record_date: 记录日期

        Returns:
            绩效指标字典
        """
        # 1. 获取账户
        account = self.account_repo.get_by_id(account_id)
        if not account:
            logger.error(f"账户不存在: {account_id}")
            return {}

        # 2. 获取持仓和交易数量
        positions = self.position_repo.get_by_account(account_id)

        # 3. 获取上一交易日净值
        prev_net_value = self._get_previous_net_value(account_id, record_date)
        # 4. 计算日收益率
        if prev_net_value and prev_net_value > 0:
            daily_return = ((float(account.total_value) - prev_net_value) / prev_net_value) * 100
        else:
            daily_return = 0.0

        # 5. 计算累计收益率
        cumulative_return = ((float(account.total_value) - float(account.initial_capital)) /
                            float(account.initial_capital)) * 100

        # 6. 计算回撤
        # 回撤 = (历史最高点 - 当前值) / 历史最高点 * 100
        # 如果当前值创新高，回撤为 0
        max_net_value = self._get_max_net_value_before_date(account_id, record_date)
        current_net_value = float(account.total_value)

        if max_net_value and max_net_value > current_net_value:
            # 当前值低于历史最高，计算回撤
            drawdown = ((max_net_value - current_net_value) / max_net_value) * 100
        else:
            # 当前值创新高或没有历史数据，回撤为 0
            drawdown = 0.0

        # 7. 获取当日交易次数
        daily_trades_count = self._get_daily_trades_count(account_id, record_date)

        # 8. 创建或更新净值记录
        self.daily_net_value_repo.upsert_daily_record(
            account_id=account_id,
            record_date=record_date,
            payload={
                "net_value": account.total_value,
                "cash": account.current_cash,
                "market_value": account.current_market_value,
                "daily_return": daily_return,
                "cumulative_return": cumulative_return,
                "drawdown": drawdown,
                "total_trades": daily_trades_count,
                "positions_count": len(positions),
            }
        )

        # 9. 重新计算并更新账户绩效指标
        metrics = self._recalculate_performance_metrics(account_id, record_date)

        # 10. 更新账户实体
        updated_account = replace(
            account,
            total_return=metrics.get('total_return', cumulative_return),
            annual_return=metrics.get('annual_return', 0.0),
            max_drawdown=metrics.get('max_drawdown', drawdown),
            sharpe_ratio=metrics.get('sharpe_ratio', 0.0),
            win_rate=metrics.get('win_rate', 0.0),
            winning_trades=metrics.get('winning_trades', 0)
        )
        self.account_repo.save(updated_account)

        return metrics

    def get_equity_curve(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None
    ) -> list[dict]:
        """
        获取净值曲线数据

        Args:
            account_id: 账户ID
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            净值曲线数据列表 [{date, net_value, daily_return, cumulative_return, drawdown}, ...]
        """
        records = self.daily_net_value_repo.list_daily_records(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )

        return [
            {
                "date": record["record_date"].isoformat(),
                "net_value": float(record["net_value"]),
                "cash": float(record["cash"]),
                "market_value": float(record["market_value"]),
                "daily_return": record["daily_return"],
                "cumulative_return": record["cumulative_return"],
                "drawdown": record["drawdown"],
                "total_trades": record["total_trades"],
                "positions_count": record["positions_count"],
            }
            for record in records
        ]

    def _get_previous_net_value(self, account_id: int, current_date: date) -> float | None:
        """获取上一交易日的净值"""
        try:
            prev_record = self.daily_net_value_repo.get_latest_record_before(account_id, current_date)
            return float(prev_record["net_value"]) if prev_record else None
        except Exception:
            return None

    def _get_previous_cumulative_return(self, account_id: int, current_date: date) -> float:
        """获取上一交易日的累计收益率"""
        try:
            prev_record = self.daily_net_value_repo.get_latest_record_before(account_id, current_date)
            return float(prev_record["cumulative_return"]) if prev_record else 0.0
        except Exception:
            return 0.0

    def _get_max_net_value_before_date(self, account_id: int, before_date: date) -> float | None:
        """获取指定日期之前的最大净值"""
        try:
            return self.daily_net_value_repo.get_max_net_value_before(account_id, before_date)
        except Exception:
            return None

    def _get_daily_trades_count(self, account_id: int, trade_date: date) -> int:
        """获取当日交易次数"""
        try:
            return self.trade_repo.count_by_execution_date(account_id, trade_date)
        except Exception:
            return 0

    def _recalculate_performance_metrics(
        self,
        account_id: int,
        as_of_date: date
    ) -> dict[str, float]:
        """
        重新计算绩效指标（基于净值曲线）

        使用净值曲线计算：
        - 总收益率：最新净值 / 初始净值 - 1
        - 年化收益率：(1 + 总收益率)^(365/天数) - 1
        - 最大回撤：净值曲线中的最大回撤
        - 夏普比率：年化收益 / 年化波动率
        - 胜率：盈利交易数 / 总交易数

        Args:
            account_id: 账户ID
            as_of_date: 计算截止日期

        Returns:
            绩效指标字典
        """
        metrics = {}

        # 获取账户信息
        account = self.account_repo.get_by_id(account_id)
        if not account:
            return metrics

        # 获取净值曲线
        net_value_records = self.daily_net_value_repo.list_daily_records(
            account_id=account_id,
            end_date=as_of_date,
        )

        if not net_value_records:
            return metrics

        # 1. 总收益率
        initial_value = float(account.initial_capital)
        final_value = float(net_value_records[-1]["net_value"])
        total_return = ((final_value - initial_value) / initial_value * 100) if initial_value > 0 else 0.0
        metrics['total_return'] = total_return

        # 2. 年化收益率
        days = (net_value_records[-1]["record_date"] - account.start_date).days
        if days > 0:
            annual_return = ((1 + total_return / 100) ** (365.0 / days) - 1) * 100
        else:
            annual_return = 0.0
        metrics['annual_return'] = annual_return

        # 3. 最大回撤（基于净值曲线）
        max_drawdown = self._calculate_max_drawdown_from_records(net_value_records)
        metrics['max_drawdown'] = max_drawdown

        # 4. 夏普比率
        sharpe_ratio = self._calculate_sharpe_ratio_from_records(net_value_records)
        metrics['sharpe_ratio'] = sharpe_ratio

        # 5. 胜率和盈利交易数
        win_rate, winning_trades = self._calculate_win_rate(account_id)
        metrics['win_rate'] = win_rate
        metrics['winning_trades'] = winning_trades

        return metrics

    def _calculate_max_drawdown_from_records(self, records: list[dict[str, object]]) -> float:
        """
        从净值记录计算最大回撤

        最大回撤 = max((峰值 - 当前值) / 峰值)

        Args:
            records: 净值记录列表（按日期排序）

        Returns:
            最大回撤（百分比）
        """
        if len(records) < 2:
            return 0.0

        max_drawdown = 0.0
        peak_value = float(records[0]["net_value"])

        for record in records:
            current_value = float(record["net_value"])

            # 更新峰值
            if current_value > peak_value:
                peak_value = current_value

            # 计算当前回撤
            if peak_value > 0:
                drawdown = ((peak_value - current_value) / peak_value) * 100
                max_drawdown = max(max_drawdown, drawdown)

        return max_drawdown

    def _calculate_sharpe_ratio_from_records(self, records: list[dict[str, object]]) -> float:
        """
        从净值记录计算夏普比率

        夏普比率 = (年化收益率 - 无风险利率) / 年化波动率

        Args:
            records: 净值记录列表（按日期排序）

        Returns:
            夏普比率
        """
        if len(records) < 2:
            return 0.0

        # 计算日收益率序列
        daily_returns = []
        for i in range(1, len(records)):
            prev_value = float(records[i - 1]["net_value"])
            curr_value = float(records[i]["net_value"])

            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                daily_returns.append(daily_return)

        if not daily_returns:
            return 0.0

        # 计算均值和标准差
        import statistics
        mean_return = statistics.mean(daily_returns)
        std_return = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0

        if std_return == 0:
            return 0.0

        # 年化
        risk_free_rate = 0.03  # 假设无风险利率3%
        annual_return = mean_return * 252
        annual_volatility = std_return * (252 ** 0.5)

        if annual_volatility == 0:
            return 0.0

        sharpe = (annual_return - risk_free_rate) / annual_volatility
        return sharpe

    def _calculate_win_rate(self, account_id: int) -> tuple[float, int]:
        """
        计算胜率

        Args:
            account_id: 账户ID

        Returns:
            (胜率, 盈利交易数)
        """
        try:
            trades = [
                trade
                for trade in self.trade_repo.get_by_account(account_id)
                if trade.action.value == 'sell'
            ]

            if not trades:
                return 0.0, 0

            winning_trades = sum(1 for t in trades if t.realized_pnl and t.realized_pnl > 0)
            win_rate = (winning_trades / len(trades)) * 100

            return win_rate, winning_trades

        except Exception as e:
            logger.error(f"计算胜率失败: {e}")
            return 0.0, 0
