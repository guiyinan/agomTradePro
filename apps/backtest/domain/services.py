"""
Domain Services for Backtesting Engine.

Pure business logic for backtesting strategy performance.
Only uses Python standard library (no pandas/numpy).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

# 从 entities 导入数据类
from .entities import (
    BacktestConfig,
    BacktestResult,
    PortfolioState,
    RebalanceResult,
    Trade,
)

# 默认无风险利率（从配置读取失败时使用）
DEFAULT_RISK_FREE_RATE = 0.03


class PITDataProcessor:
    """
    Point-in-Time 数据处理器（增强版）

    确保回测时只使用当时已经发布的数据，避免未来函数。

    功能:
    1. 处理发布滞后：数据观测后需要一段时间才发布
    2. 数据版本追踪：支持获取"as-of"某个日期可用的数据版本
    3. 数据过滤：从候选数据中筛选出在指定日期已发布的数据

    局限性 (已标记为回测结果):
    - 当前版本不处理数据修订（如 GDP 初值 vs 终值）
    - 假设发布滞后是固定的，不考虑特殊情况（如节假日）
    - 数据修订需要额外的版本管理系统

    用户可在回测结果中看到 pit_revision_warning 字段获取此警告。
    """

    def __init__(self, publication_lags: dict[str, timedelta]):
        """
        Args:
            publication_lags: {indicator_code: lag_timedelta}
                             例如: {"PMI": timedelta(days=35), "CPI": timedelta(days=10)}
        """
        self.publication_lags = publication_lags

    def get_publication_date(
        self,
        observed_at: date,
        indicator_code: str
    ) -> date:
        """
        获取数据观测日期对应的发布日期

        Args:
            observed_at: 数据观测日期（报告期）
            indicator_code: 指标代码

        Returns:
            date: 数据发布日期

        示例:
            PMI 在 1月31日观测，滞后35天，发布日期为 3月7日
        """
        lag = self.publication_lags.get(indicator_code, timedelta(days=0))
        return observed_at + lag

    def get_available_as_of_date(
        self,
        observed_at: date,
        indicator_code: str
    ) -> date:
        """
        Backward-compatible alias for publication date lookup.

        Kept for older callers/tests that still use the previous API name.
        """
        return self.get_publication_date(observed_at, indicator_code)

    def is_data_available(
        self,
        observed_at: date,
        indicator_code: str,
        as_of_date: date
    ) -> bool:
        """
        检查数据在指定日期是否可用

        Args:
            observed_at: 数据观测日期
            indicator_code: 指标代码
            as_of_date: 查询日期（回测当前日期）

        Returns:
            bool: 数据是否可用

        示例:
            PMI(1月) 在3月7日发布，回测日期为3月1日时不可用
            PMI(1月) 在3月7日发布，回测日期为3月10日时可用
        """
        published_at = self.get_publication_date(observed_at, indicator_code)
        return published_at <= as_of_date

    def filter_data_by_availability(
        self,
        data_points: list[tuple[date, float]],  # [(observed_at, value), ...]
        indicator_code: str,
        as_of_date: date
    ) -> list[tuple[date, float]]:
        """
        筛选出在指定日期已发布的所有数据点

        Args:
            data_points: 数据点列表，格式为 [(观测日期, 值), ...]
            indicator_code: 指标代码
            as_of_date: 回测当前日期

        Returns:
            List[Tuple[date, float]]: 已发布的数据点列表

        示例:
            回测日期为2024-03-10，PMI滞后35天
            [(2024-01-31, 50.1), (2024-02-29, 49.8)]  # 1月和2月数据都已发布
            [(2024-03-31, 51.2)]  # 3月数据尚未发布（5月5日才发布）
        """
        available = []
        for observed_at, value in data_points:
            if self.is_data_available(observed_at, indicator_code, as_of_date):
                available.append((observed_at, value))
        return available

    def get_latest_available_value(
        self,
        data_points: list[tuple[date, float]],
        indicator_code: str,
        as_of_date: date
    ) -> tuple[date, float] | None:
        """
        获取指定日期可用的最新数据点

        Args:
            data_points: 数据点列表，按观测日期排序
            indicator_code: 指标代码
            as_of_date: 回测当前日期

        Returns:
            Optional[Tuple[date, float]]: 最新的可用数据点，如果没有则返回 None

        示例:
            回测日期为2024-03-10，PMI滞后35天
            返回 (2024-02-29, 49.8)  # 2月数据是最新可用的
        """
        available = self.filter_data_by_availability(data_points, indicator_code, as_of_date)
        return available[-1] if available else None

    def warn_if_revision_not_supported(self) -> str:
        """
        生成关于数据修订的警告信息

        Returns:
            str: 警告信息

        注意:
            此方法用于提醒用户当前版本不支持数据修订处理
            经济数据（如GDP）经常在初次发布后进行修订
            在历史回测中，应该使用当时可用的数据版本，而非最终修订值
        """
        return (
            "⚠️  PIT数据处理器警告:\n"
            "当前版本不支持数据修订追踪。\n"
            "经济数据（如GDP、PMI等）常在初次发布后修订，\n"
            "严格的历史回测应使用当时可用的数据版本。\n"
            "如需数据修订支持，请实现版本管理系统。"
        )


class BacktestEngine:
    """
    回测引擎

    职责：
    1. 按时间步进模拟交易
    2. 在每个再平衡点计算目标权重
    3. 应用准入规则过滤
    4. 计算交易成本和收益
    """

    def __init__(
        self,
        config: BacktestConfig,
        get_regime_func: Callable[[date], dict | None],
        get_asset_price_func: Callable[[str, date], float | None],
        pit_processor: PITDataProcessor | None = None,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ):
        """
        Args:
            config: 回测配置
            get_regime_func: 获取 Regime 的函数 (date) -> Dict
            get_asset_price_func: 获取资产价格的函数 (asset_class, date) -> float
            pit_processor: Point-in-Time 数据处理器
            risk_free_rate: Annual risk-free rate used for Sharpe calculation
        """
        self.config = config
        self.get_regime = get_regime_func
        self.get_price = get_asset_price_func
        self.pit_processor = pit_processor
        self.risk_free_rate = risk_free_rate

        # 内部状态
        self._cash = config.initial_capital
        self._positions: dict[str, float] = {}  # asset_class -> shares
        self._trades: list[Trade] = []
        self._equity_curve: list[tuple[date, float]] = []
        self._regime_history: list[dict] = []

    def run(self) -> BacktestResult:
        """
        运行回测

        Returns:
            BacktestResult: 回测结果
        """
        # 收集警告信息
        warnings = []

        # 添加 PIT 数据修订警告
        if self.config.use_pit_data and self.pit_processor:
            warnings.append(
                "⚠️ PIT 数据警告: 当前版本不支持数据修订追踪。"
                "经济数据（如GDP、PMI等）常在初次发布后修订，"
                "严格的历史回测应使用当时可用的数据版本。"
            )

        # 生成再平衡日期
        rebalance_dates = self._generate_rebalance_dates()

        # 初始状态
        current_date = self.config.start_date
        self._equity_curve.append((current_date, self.config.initial_capital))

        # 按时间步进
        for rebalance_date in rebalance_dates:
            # 执行再平衡
            result = self._rebalance(rebalance_date)
            if result:
                self._regime_history.append({
                    "date": rebalance_date.isoformat(),  # 转换为字符串以便 JSON 序列化
                    "regime": result.regime,
                    "confidence": result.regime_confidence,
                    "portfolio_value": result.portfolio_value
                })

            # 记录权益曲线
            portfolio_value = self._calculate_portfolio_value(rebalance_date)
            self._equity_curve.append((rebalance_date, portfolio_value))

        # 计算最终结果
        final_value = self._equity_curve[-1][1] if self._equity_curve else self.config.initial_capital
        total_return = (final_value / self.config.initial_capital) - 1

        return BacktestResult(
            config=self.config,
            final_value=final_value,
            total_return=total_return,
            annualized_return=self._calculate_annual_return(total_return),
            sharpe_ratio=self._calculate_sharpe_ratio(),
            max_drawdown=self._calculate_max_drawdown(),
            trades=self._trades,
            equity_curve=self._equity_curve,
            regime_history=self._regime_history,
            warnings=warnings
        )

    def _generate_rebalance_dates(self) -> list[date]:
        """生成再平衡日期"""
        dates = []
        current = self.config.start_date

        while current <= self.config.end_date:
            dates.append(current)

            # 计算下一个再平衡日期
            if self.config.rebalance_frequency == "monthly":
                # 下个月第一天 - 使用标准库函数处理边界
                if current.month == 12:
                    year = current.year + 1
                    month = 1
                else:
                    year = current.year
                    month = current.month + 1
                current = date(year, month, 1)
            elif self.config.rebalance_frequency == "quarterly":
                # 下季度第一天
                year = current.year + ((current.month + 3) // 12)
                month = ((current.month - 1 + 3) % 12) + 1
                current = date(year, month, 1)
            else:  # yearly
                # 下一年第一天
                current = date(current.year + 1, 1, 1)

        return dates

    def _rebalance(self, as_of_date: date) -> RebalanceResult | None:
        """
        执行再平衡

        Args:
            as_of_date: 再平衡日期

        Returns:
            Optional[RebalanceResult]: 再平衡结果
        """
        # 1. 获取当前 Regime
        regime_data = self.get_regime(as_of_date)
        if not regime_data:
            return None

        regime = regime_data.get("dominant_regime")
        confidence = regime_data.get("confidence", 0.0)

        # 2. 计算旧权重（再平衡前的权重）
        old_weights = self._calculate_current_weights(as_of_date)

        # 3. 计算目标权重（根据准入规则）
        target_weights = self._calculate_target_weights(regime, confidence)

        # 4. 获取当前组合价值
        current_portfolio_value = self._calculate_portfolio_value(as_of_date)

        # 5. 计算目标持仓
        trades = []
        new_positions = {}

        for asset_class, target_weight in target_weights.items():
            target_value = current_portfolio_value * target_weight
            price = self.get_price(asset_class, as_of_date)

            if price is None or price <= 0:
                continue

            target_shares = target_value / price
            current_shares = self._positions.get(asset_class, 0)

            # 计算交易
            shares_diff = target_shares - current_shares
            if abs(shares_diff) > 0.0001:  # 避免微小交易
                action = "buy" if shares_diff > 0 else "sell"
                notional = abs(shares_diff) * price
                cost = self._calculate_transaction_cost(notional)

                trade = Trade(
                    trade_date=as_of_date,
                    asset_class=asset_class,
                    action=action,
                    shares=abs(shares_diff),
                    price=price,
                    notional=notional,
                    cost=cost
                )
                trades.append(trade)

                # 更新现金和持仓
                if shares_diff > 0:
                    self._cash -= (notional + cost)
                else:
                    self._cash += (notional - cost)

                new_positions[asset_class] = target_shares
            else:
                new_positions[asset_class] = current_shares

        # 处理不再持有的资产
        for asset_class in list(self._positions.keys()):
            if asset_class not in target_weights:
                price = self.get_price(asset_class, as_of_date)
                if price and price > 0:
                    shares = self._positions[asset_class]
                    notional = shares * price
                    cost = self._calculate_transaction_cost(notional)

                    trade = Trade(
                        trade_date=as_of_date,
                        asset_class=asset_class,
                        action="sell",
                        shares=shares,
                        price=price,
                        notional=notional,
                        cost=cost
                    )
                    trades.append(trade)

                    self._cash += (notional - cost)

        self._positions = new_positions
        self._trades.extend(trades)

        return RebalanceResult(
            date=as_of_date,
            regime=regime,
            regime_confidence=confidence,
            old_weights=old_weights,
            new_weights=target_weights,
            trades=trades,
            portfolio_value=current_portfolio_value
        )

    def _calculate_current_weights(self, as_of_date: date) -> dict[str, float]:
        """
        计算当前组合的权重

        Args:
            as_of_date: 计算权重的日期

        Returns:
            Dict[str, float]: 当前权重 {asset_class: weight}
        """
        portfolio_value = self._calculate_portfolio_value(as_of_date)

        if portfolio_value <= 0:
            return {}

        weights = {}
        # 计算持仓资产的权重
        for asset_class, shares in self._positions.items():
            price = self.get_price(asset_class, as_of_date)
            if price and price > 0:
                market_value = shares * price
                weights[asset_class] = market_value / portfolio_value

        # 计算现金权重
        if self._cash > 0:
            weights["CASH"] = self._cash / portfolio_value

        return weights

    def _calculate_target_weights(
        self,
        regime: str,
        confidence: float
    ) -> dict[str, float]:
        """
        计算目标权重（应用准入规则）

        Args:
            regime: 当前 Regime
            confidence: 置信度

        Returns:
            Dict[str, float]: 目标权重 {asset_class: weight}
        """
        # 基础配置：等权分配给 PREFERRED 资产
        from apps.regime.domain.asset_eligibility import (
            Eligibility,
            check_eligibility,
            get_eligibility_matrix,
        )

        eligible_assets = []
        eligibility_matrix = get_eligibility_matrix()
        for asset_class in eligibility_matrix.keys():
            eligibility = check_eligibility(asset_class, regime)
            if eligibility == Eligibility.PREFERRED:
                eligible_assets.append(asset_class)
            elif eligibility == Eligibility.HOSTILE:
                # 敌对环境，不持有
                continue
            elif eligibility == Eligibility.NEUTRAL:
                # 低置信度时，中性资产也不持有
                if confidence < 0.3:
                    continue
                eligible_assets.append(asset_class)

        # 等权分配
        if not eligible_assets:
            # 没有合适资产，全部持有现金
            return {"CASH": 1.0}

        weight = 1.0 / len(eligible_assets)
        return dict.fromkeys(eligible_assets, weight)

    def _calculate_transaction_cost(self, notional: float) -> float:
        """计算交易成本"""
        return notional * (self.config.transaction_cost_bps / 10000)

    def _calculate_portfolio_value(self, as_of_date: date) -> float:
        """计算组合总价值"""
        total = self._cash
        for asset_class, shares in self._positions.items():
            price = self.get_price(asset_class, as_of_date)
            if price and price > 0:
                total += shares * price
        return total

    def _calculate_annual_return(self, total_return: float) -> float:
        """计算年化收益"""
        days = (self.config.end_date - self.config.start_date).days
        years = days / 365.25
        if years <= 0:
            return 0.0
        return (1 + total_return) ** (1 / years) - 1

    def _calculate_sharpe_ratio(self) -> float | None:
        """计算夏普比率"""
        if len(self._equity_curve) < 2:
            return None

        # 计算日收益率
        returns = []
        for i in range(1, len(self._equity_curve)):
            prev_value = self._equity_curve[i - 1][1]
            curr_value = self._equity_curve[i][1]
            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                returns.append(daily_return)

        if not returns:
            return None

        # 计算均值和标准差
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)

        # 年化（假设 252 个交易日）
        annualized_mean = mean_return * 252
        annualized_std = std_return * math.sqrt(252)

        if annualized_std == 0:
            return None

        return (annualized_mean - self.risk_free_rate) / annualized_std

    def _calculate_max_drawdown(self) -> float:
        """计算最大回撤"""
        if not self._equity_curve:
            return 0.0

        peak = self._equity_curve[0][1]
        max_drawdown = 0.0

        for _, value in self._equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return max_drawdown
