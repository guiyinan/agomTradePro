"""
Account Application - Stress Testing Use Cases

压力测试用例。
"""

import logging
from decimal import Decimal
from typing import List, Dict, Optional
from datetime import datetime, date
from dataclasses import dataclass
import statistics

logger = logging.getLogger(__name__)


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
        initial_value = Decimal('1000000')
        equity_curve = [float(initial_value)]
        for r in portfolio_returns:
            equity_curve.append(equity_curve[-1] * (1 + r))

        final_value = Decimal(str(round(equity_curve[-1], 2)))
        total_return = Decimal(str(round(
            (float(final_value) - float(initial_value)) / float(initial_value), 6
        )))

        max_dd, recovery = VaRService.calculate_max_drawdown(equity_curve)
        volatility = statistics.stdev(portfolio_returns) if len(portfolio_returns) > 1 else 0.0
        var_95 = VaRService.calculate_historical_var(portfolio_returns, 0.95)
        var_99 = VaRService.calculate_historical_var(portfolio_returns, 0.99)

        # 生成建议
        recommendations = self._generate_recommendations(
            total_return, max_dd, volatility
        )

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

    def _get_portfolio_positions(
        self, portfolio_id: int
    ) -> List[Dict]:
        """获取组合持仓及权重"""
        from apps.account.infrastructure.models import PositionModel

        positions = PositionModel._default_manager.filter(
            portfolio_id=portfolio_id,
            market_value__gt=0,
        ).values('asset_code', 'market_value')

        if not positions:
            return []

        total_value = sum(float(p['market_value']) for p in positions)
        if total_value <= 0:
            return []

        return [
            {
                'asset_code': p['asset_code'],
                'weight': float(p['market_value']) / total_value,
            }
            for p in positions
        ]

    def _simulate_portfolio_returns(
        self,
        positions: List[Dict],
        start_date: date,
        end_date: date,
    ) -> List[float]:
        """模拟组合在历史场景中的收益率序列"""
        try:
            from apps.equity.infrastructure.adapters import TushareStockAdapter
            adapter = TushareStockAdapter()
        except Exception as e:
            logger.warning(f"无法初始化 TushareStockAdapter: {e}")
            return []

        # 获取每个持仓的日线收益率
        stock_returns = {}
        common_dates = None

        for pos in positions:
            try:
                df = adapter.fetch_daily_data(
                    pos['asset_code'], start_date, end_date
                )
                if df is None or df.empty:
                    continue

                # 以 trade_date 为 index，pct_chg 为值
                daily = {}
                for _, row in df.iterrows():
                    d = row['trade_date'].date() if hasattr(row['trade_date'], 'date') else row['trade_date']
                    daily[d] = row['pct_chg'] / 100.0

                if daily:
                    stock_returns[pos['asset_code']] = daily
                    dates_set = set(daily.keys())
                    common_dates = dates_set if common_dates is None else common_dates & dates_set

            except Exception as e:
                logger.debug(f"获取 {pos['asset_code']} 历史数据失败: {e}")
                continue

        if not stock_returns or not common_dates:
            return []

        # 按权重计算组合日收益率
        sorted_dates = sorted(common_dates)
        weight_map = {p['asset_code']: p['weight'] for p in positions}

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
    ) -> List[str]:
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
