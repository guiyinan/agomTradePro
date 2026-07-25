"""
Account Application - Stress Testing Use Cases

压力测试用例。
"""

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, TypedDict

from apps.account.application.repository_provider import get_account_position_repository

logger = logging.getLogger(__name__)


class PositionWeight(TypedDict):
    """Validated position input used by the stress-test calculation."""

    asset_code: str
    weight: float


class PositionWeightRepository(Protocol):
    """Port for loading the minimum position data needed by stress tests."""

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[dict[str, Any]]:
        """Return asset codes and portfolio weights."""


@dataclass(frozen=True)
class StressTestScenario:
    """压力测试情景"""

    scenario_id: str  # 情景ID
    name: str  # 情景名称
    description: str  # 描述
    start_date: date  # 开始日期
    end_date: date  # 结束日期


@dataclass(frozen=True)
class StressTestResult:
    """压力测试结果"""

    scenario_id: str  # 情景ID
    scenario_name: str  # 情景名称
    initial_value: Decimal  # 初始资产
    final_value: Decimal  # 最终资产
    total_return: Decimal  # 总收益率
    max_drawdown: float  # 最大回撤
    recovery_days: int  # 恢复天数
    volatility: float  # 波动率
    var_95: float  # 95% VaR
    var_99: float  # 99% VaR
    recommendations: list[str]  # 改进建议


class HistoricalScenarioService:
    """
    历史情景服务

    定义历史极端情景供压力测试使用。
    """

    # 预定义历史情景
    SCENARIOS = {
        "2015_crash": StressTestScenario(
            scenario_id="2015_crash",
            name="2015股灾",
            description="2015年6月-8月股市暴跌",
            start_date=date(2015, 6, 12),
            end_date=date(2015, 8, 26),
        ),
        "2020_covid": StressTestScenario(
            scenario_id="2020_covid",
            name="2020疫情冲击",
            description="2020年1月-3月COVID-19疫情冲击",
            start_date=date(2020, 1, 14),
            end_date=date(2020, 3, 23),
        ),
        "2018_trade_war": StressTestScenario(
            scenario_id="2018_trade_war",
            name="2018贸易战",
            description="2018年全年中美贸易战",
            start_date=date(2018, 1, 2),
            end_date=date(2018, 12, 28),
        ),
    }

    @classmethod
    def get_scenario(cls, scenario_id: str) -> StressTestScenario | None:
        """获取情景定义"""
        return cls.SCENARIOS.get(scenario_id)

    @classmethod
    def get_all_scenarios(cls) -> list[StressTestScenario]:
        """获取所有情景"""
        return list(cls.SCENARIOS.values())


class VaRService:
    """
    VaR 计算服务

    计算风险价值。
    """

    @staticmethod
    def calculate_historical_var(
        returns: list[float],
        confidence: float = 0.95,
    ) -> float:
        """
        计算历史模拟法 VaR

        Args:
            returns: 收益率序列
            confidence: 置信度（如 0.95 表示 95%）

        Returns:
            VaR 值（负数表示损失）
        """
        if not math.isfinite(confidence) or not 0 < confidence < 1:
            raise ValueError("VaR 置信度必须是 0 到 1 之间的有限数")
        if not returns:
            return 0.0
        if any(not math.isfinite(value) for value in returns):
            raise ValueError("VaR 收益率序列必须全部为有限数")

        # 排序收益率
        sorted_returns = sorted(returns)

        # 计算分位数
        index = int((1 - confidence) * len(sorted_returns))
        var = sorted_returns[index] if index < len(sorted_returns) else sorted_returns[-1]

        return var

    @staticmethod
    def calculate_max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
        """
        计算最大回撤

        Args:
            equity_curve: 净值曲线

        Returns:
            (max_drawdown, recovery_days): 最大回撤和恢复天数
        """
        if not equity_curve:
            return 0.0, 0
        if any(not math.isfinite(value) or value < 0 for value in equity_curve):
            raise ValueError("净值曲线必须全部为非负有限数")

        max_drawdown = 0.0
        peak = equity_curve[0]
        recovery_days = 0
        max_recovery_days = 0

        for _i, value in enumerate(equity_curve):
            if value > peak:
                peak = value
                recovery_days = 0
            else:
                drawdown = (peak - value) / peak if peak > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                recovery_days += 1
                if recovery_days > max_recovery_days:
                    max_recovery_days = recovery_days

        return max_drawdown, max_recovery_days


class StressTestingUseCase:
    """
    压力测试用例

    对投资组合进行历史情景压力测试。
    """

    def __init__(
        self,
        position_repo: PositionWeightRepository | None = None,
    ) -> None:
        self.position_repo = position_repo or get_account_position_repository()

    def run_historical_scenario_test(
        self,
        portfolio_id: int,
        scenario_id: str,
    ) -> StressTestResult:
        """
        运行历史情景压力测试

        Args:
            portfolio_id: 投资组合ID
            scenario_id: 情景ID

        Returns:
            StressTestResult: 压力测试结果
        """
        scenario = HistoricalScenarioService.get_scenario(scenario_id)
        if not scenario:
            raise ValueError(f"情景 {scenario_id} 不存在")

        # 获取组合持仓
        positions = self._get_portfolio_positions(portfolio_id)
        if not positions:
            raise ValueError(f"组合 {portfolio_id} 没有持仓")

        # 获取持仓在场景期间的历史日线收益率
        portfolio_returns = self._simulate_portfolio_returns(
            positions, scenario.start_date, scenario.end_date
        )

        if not portfolio_returns:
            raise ValueError("无法获取场景期间的历史行情数据")

        # 计算指标
        initial_value = Decimal("1000000")
        equity_curve = [float(initial_value)]
        for r in portfolio_returns:
            equity_curve.append(equity_curve[-1] * (1 + r))

        final_value = Decimal(str(round(equity_curve[-1], 2)))
        total_return = Decimal(
            str(round((float(final_value) - float(initial_value)) / float(initial_value), 6))
        )

        max_dd, recovery = VaRService.calculate_max_drawdown(equity_curve)
        volatility = statistics.stdev(portfolio_returns) if len(portfolio_returns) > 1 else 0.0
        var_95 = VaRService.calculate_historical_var(portfolio_returns, 0.95)
        var_99 = VaRService.calculate_historical_var(portfolio_returns, 0.99)

        # 生成建议
        recommendations = self._generate_recommendations(total_return, max_dd, volatility)

        return StressTestResult(
            scenario_id=scenario_id,
            scenario_name=scenario.name,
            initial_value=initial_value,
            final_value=final_value,
            total_return=total_return,
            max_drawdown=max_dd,
            recovery_days=recovery,
            volatility=volatility,
            var_95=var_95,
            var_99=var_99,
            recommendations=recommendations,
        )

    def _get_portfolio_positions(self, portfolio_id: int) -> list[PositionWeight]:
        """获取组合持仓及权重"""
        raw_positions = self.position_repo.list_portfolio_position_weights(portfolio_id)
        positions: list[PositionWeight] = []
        seen_codes: set[str] = set()
        for raw_position in raw_positions:
            asset_code = raw_position.get("asset_code")
            weight_value = raw_position.get("weight")
            if not isinstance(asset_code, str) or not asset_code.strip():
                raise ValueError("压力测试持仓缺少有效资产代码")
            asset_code = asset_code.strip()
            if asset_code in seen_codes:
                raise ValueError(f"压力测试持仓包含重复资产代码: {asset_code}")
            if isinstance(weight_value, bool):
                raise ValueError(f"持仓 {asset_code} 的权重无效")
            if not isinstance(weight_value, (str, int, float, Decimal)):
                raise ValueError(f"持仓 {asset_code} 的权重无效")
            try:
                weight = float(weight_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"持仓 {asset_code} 的权重无效") from exc
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError(f"持仓 {asset_code} 的权重必须为正有限数")
            positions.append({"asset_code": asset_code, "weight": weight})
            seen_codes.add(asset_code)
        return positions

    def _simulate_portfolio_returns(
        self,
        positions: list[PositionWeight],
        start_date: date,
        end_date: date,
    ) -> list[float]:
        """模拟组合在历史场景中的收益率序列"""
        try:
            from apps.account.application.business_provider_gateway import (
                get_tushare_stock_adapter,
            )

            adapter = get_tushare_stock_adapter()
        except Exception as e:
            logger.warning(f"无法初始化 TushareStockAdapter: {e}")
            return []

        # 获取每个持仓的日线收益率
        stock_returns: dict[str, dict[date, float]] = {}
        common_dates: set[date] | None = None

        for pos in positions:
            try:
                df = adapter.fetch_daily_data(pos["asset_code"], start_date, end_date)
                if df is None or df.empty:
                    continue

                # 以 trade_date 为 index，pct_chg 为值
                daily: dict[date, float] = {}
                for _, row in df.iterrows():
                    trade_date_value = row["trade_date"]
                    trade_date = (
                        trade_date_value.date()
                        if hasattr(trade_date_value, "date")
                        else trade_date_value
                    )
                    if not isinstance(trade_date, date):
                        raise ValueError("行情交易日无效")
                    pct_change_value = row["pct_chg"]
                    if isinstance(pct_change_value, bool):
                        raise ValueError("行情涨跌幅无效")
                    pct_change = float(pct_change_value) / 100.0
                    if not math.isfinite(pct_change) or pct_change < -1:
                        raise ValueError("行情涨跌幅必须为有限数且不得低于 -100%")
                    daily[trade_date] = pct_change

                if daily:
                    stock_returns[pos["asset_code"]] = daily
                    dates_set = set(daily.keys())
                    common_dates = (
                        dates_set if common_dates is None else common_dates.intersection(dates_set)
                    )

            except Exception as e:
                logger.debug(f"获取 {pos['asset_code']} 历史数据失败: {e}")
                continue

        if not stock_returns or not common_dates:
            return []

        # 按权重计算组合日收益率
        sorted_dates = sorted(common_dates)
        weight_map = {p["asset_code"]: p["weight"] for p in positions}

        portfolio_returns = []
        for d in sorted_dates:
            daily_return = 0.0
            weight_sum = 0.0
            for code, returns in stock_returns.items():
                if d in returns and code in weight_map:
                    daily_return += weight_map[code] * returns[d]
                    weight_sum += weight_map[code]

            if weight_sum > 0:
                # 归一化权重
                portfolio_returns.append(daily_return / weight_sum)

        return portfolio_returns

    @staticmethod
    def _generate_recommendations(
        total_return: Decimal, max_drawdown: float, volatility: float
    ) -> list[str]:
        """根据测试结果生成改进建议"""
        recommendations = []

        if float(total_return) < -0.20:
            recommendations.append("建议增加政策档位变化的快速响应机制")
        if max_drawdown > 0.30:
            recommendations.append("建议设置动态止损以限制极端损失")
        if volatility > 0.03:
            recommendations.append("建议增加对冲工具以降低组合Beta")
        if max_drawdown > 0.20 and float(total_return) < -0.10:
            recommendations.append("建议分散持仓以降低集中度风险")

        if not recommendations:
            recommendations.append("组合在该场景下表现尚可，继续保持当前策略")

        return recommendations

    def run_all_scenarios(
        self,
        portfolio_id: int,
    ) -> list[StressTestResult]:
        """
        运行所有情景的压力测试

        Args:
            portfolio_id: 投资组合ID

        Returns:
            List[StressTestResult]: 所情景测试结果
        """
        results = []
        scenarios = HistoricalScenarioService.get_all_scenarios()

        for scenario in scenarios:
            result = self.run_historical_scenario_test(portfolio_id, scenario.scenario_id)
            results.append(result)

        return results
