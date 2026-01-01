"""
Account Application - Stress Testing Use Cases

压力测试用例。
"""

from decimal import Decimal
from typing import List, Dict, Optional
from datetime import datetime, date
from dataclasses import dataclass
import statistics


@dataclass
class StressTestScenario:
    """压力测试情景"""
    scenario_id: str           # 情景ID
    name: str                  # 情景名称
    description: str           # 描述
    start_date: date           # 开始日期
    end_date: date             # 结束日期


@dataclass
class StressTestResult:
    """压力测试结果"""
    scenario_id: str           # 情景ID
    scenario_name: str         # 情景名称
    initial_value: Decimal     # 初始资产
    final_value: Decimal       # 最终资产
    total_return: Decimal      # 总收益率
    max_drawdown: float        # 最大回撤
    recovery_days: int         # 恢复天数
    volatility: float          # 波动率
    var_95: float              # 95% VaR
    var_99: float              # 99% VaR
    recommendations: List[str]  # 改进建议


class HistoricalScenarioService:
    """
    历史情景服务

    定义历史极端情景供压力测试使用。
    """

    # 预定义历史情景
    SCENARIOS = {
        '2015_crash': StressTestScenario(
            scenario_id='2015_crash',
            name='2015股灾',
            description='2015年6月-8月股市暴跌',
            start_date=date(2015, 6, 12),
            end_date=date(2015, 8, 26),
        ),
        '2020_covid': StressTestScenario(
            scenario_id='2020_covid',
            name='2020疫情冲击',
            description='2020年1月-3月COVID-19疫情冲击',
            start_date=date(2020, 1, 14),
            end_date=date(2020, 3, 23),
        ),
        '2018_trade_war': StressTestScenario(
            scenario_id='2018_trade_war',
            name='2018贸易战',
            description='2018年全年中美贸易战',
            start_date=date(2018, 1, 2),
            end_date=date(2018, 12, 28),
        ),
    }

    @classmethod
    def get_scenario(cls, scenario_id: str) -> Optional[StressTestScenario]:
        """获取情景定义"""
        return cls.SCENARIOS.get(scenario_id)

    @classmethod
    def get_all_scenarios(cls) -> List[StressTestScenario]:
        """获取所有情景"""
        return list(cls.SCENARIOS.values())


class VaRService:
    """
    VaR 计算服务

    计算风险价值。
    """

    @staticmethod
    def calculate_historical_var(
        returns: List[float],
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
        if not returns:
            return 0.0

        # 排序收益率
        sorted_returns = sorted(returns)

        # 计算分位数
        index = int((1 - confidence) * len(sorted_returns))
        var = sorted_returns[index] if index < len(sorted_returns) else sorted_returns[-1]

        return var

    @staticmethod
    def calculate_max_drawdown(equity_curve: List[float]) -> tuple:
        """
        计算最大回撤

        Args:
            equity_curve: 净值曲线

        Returns:
            (max_drawdown, recovery_days): 最大回撤和恢复天数
        """
        if not equity_curve:
            return 0.0, 0

        max_drawdown = 0.0
        peak = equity_curve[0]
        recovery_days = 0
        max_recovery_days = 0
        in_drawdown = False

        for i, value in enumerate(equity_curve):
            if value > peak:
                peak = value
                in_drawdown = False
                recovery_days = 0
            else:
                drawdown = (peak - value) / peak if peak > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                in_drawdown = True
                recovery_days += 1
                if recovery_days > max_recovery_days:
                    max_recovery_days = recovery_days

        return max_drawdown, max_recovery_days


class StressTestingUseCase:
    """
    压力测试用例

    对投资组合进行历史情景压力测试。
    """

    def __init__(self):
        pass

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

        # TODO: 获取该时间段的历史数据，模拟回测
        # 这里返回模拟结果
        return StressTestResult(
            scenario_id=scenario_id,
            scenario_name=scenario.name,
            initial_value=Decimal('1000000'),
            final_value=Decimal('850000'),
            total_return=Decimal('-0.15'),
            max_drawdown=0.35,
            recovery_days=180,
            volatility=0.45,
            var_95=-0.08,
            var_99=-0.12,
            recommendations=[
                "建议增加政策档位变化的快速响应机制",
                "建议设置动态止损以限制极端损失",
                "建议增加对冲工具以降低组合Beta",
            ],
        )

    def run_all_scenarios(
        self,
        portfolio_id: int,
    ) -> List[StressTestResult]:
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
