"""
Domain Services for Attribution Analysis.

Pure business logic for analyzing backtest results and attributing PnL.
Only uses Python standard library (no pandas/numpy).
"""

import math
from datetime import date
from typing import List, Dict, Optional, Tuple

from .entities import (
    LossSource,
    RegimeTransition,
    RegimePeriod,
    PeriodPerformance,
    AttributionResult,
    AttributionConfig
)


def analyze_attribution(
    backtest_result,
    regime_history: List[Dict],
    asset_returns: Dict[str, List[Tuple[date, float]]],
    config: Optional[AttributionConfig] = None
) -> AttributionResult:
    """
    执行归因分析

    Args:
        backtest_result: 回测结果 (BacktestResult)
        regime_history: Regime 历史记录
        asset_returns: 各资产收益率历史 {asset_class: [(date, return), ...]}
        config: 分析配置

    Returns:
        AttributionResult: 归因分析结果
    """
    if config is None:
        config = AttributionConfig()

    # 1. 构建 Regime 周期
    periods = _build_regime_periods(regime_history)

    # 2. 计算各周期表现
    period_performances = _calculate_period_performances(
        periods,
        backtest_result.equity_curve,
        asset_returns
    )

    # 3. 归因分析（启发式分解）
    timing_pnl, selection_pnl, interaction_pnl = _heuristic_pnl_decomposition(period_performances)

    # 4. 识别损失来源
    loss_source, loss_amount, loss_periods = _identify_loss_source(period_performances)

    # 5. 生成经验总结
    lesson, suggestions = _generate_lessons(period_performances, loss_source)

    # 6. 计算交易成本
    cost_pnl = _calculate_total_transaction_cost(backtest_result.trades)

    # 7. 构建周期归因详情
    period_attributions = _build_period_attributions(period_performances)

    return AttributionResult(
        total_return=backtest_result.total_return,
        regime_timing_pnl=timing_pnl,
        asset_selection_pnl=selection_pnl,
        interaction_pnl=interaction_pnl,
        transaction_cost_pnl=cost_pnl,
        loss_source=loss_source,
        loss_amount=loss_amount,
        loss_periods=loss_periods,
        lesson_learned=lesson,
        improvement_suggestions=suggestions,
        period_attributions=period_attributions
    )


def _build_regime_periods(regime_history: List[Dict]) -> List[RegimePeriod]:
    """构建 Regime 周期"""
    if not regime_history:
        return []

    periods = []
    current_regime = None
    current_start = None
    current_confidence = 0.0

    for i, entry in enumerate(regime_history):
        regime = entry.get("regime")
        confidence = entry.get("confidence", 0.0)
        entry_date = entry.get("date")

        if current_regime is None:
            current_regime = regime
            current_start = entry_date
            current_confidence = confidence
        elif regime != current_regime:
            # Regime 变化，保存上一个周期
            periods.append(RegimePeriod(
                start_date=current_start,
                end_date=entry_date,
                regime=current_regime,
                confidence=current_confidence
            ))
            current_regime = regime
            current_start = entry_date
            current_confidence = confidence

    # 添加最后一个周期
    if current_regime and current_start:
        periods.append(RegimePeriod(
            start_date=current_start,
            end_date=regime_history[-1].get("date", current_start),
            regime=current_regime,
            confidence=current_confidence
        ))

    return periods


def _calculate_period_performances(
    periods: List[RegimePeriod],
    equity_curve: List[Tuple[date, float]],
    asset_returns: Dict[str, List[Tuple[date, float]]]
) -> List[PeriodPerformance]:
    """计算各周期表现"""
    performances = []

    equity_dict = dict(equity_curve)

    for period in periods:
        # 获取周期起止的组合价值
        start_value = equity_dict.get(period.start_date)
        end_value = equity_dict.get(period.end_date)

        if start_value is None or end_value is None:
            continue

        portfolio_return = (end_value - start_value) / start_value

        # 获取各资产收益（简化：取首尾日期）
        asset_period_returns = {}
        for asset, returns in asset_returns.items():
            # 找到周期内的收益率
            period_returns = [
                r for d, r in returns
                if period.start_date <= d <= period.end_date
            ]
            if period_returns:
                # 简化：使用平均收益
                asset_period_returns[asset] = sum(period_returns) / len(period_returns)
            else:
                asset_period_returns[asset] = 0.0

        benchmark_return = sum(asset_period_returns.values()) / len(asset_period_returns) if asset_period_returns else 0.0
        best_return = max(asset_period_returns.values()) if asset_period_returns else 0.0
        worst_return = min(asset_period_returns.values()) if asset_period_returns else 0.0

        performances.append(PeriodPerformance(
            period=period,
            portfolio_return=portfolio_return,
            benchmark_return=benchmark_return,
            best_asset_return=best_return,
            worst_asset_return=worst_return,
            asset_returns=asset_period_returns
        ))

    return performances


def _heuristic_pnl_decomposition(performances: List[PeriodPerformance]) -> Tuple[float, float, float]:
    """
    启发式收益分解（非 Brinson 模型）

    ⚠️ 注意：此函数使用简化的启发式规则分解收益，而非严格的 Brinson 模型

    分解规则：
    - 择时收益：正收益的 30% 归因于 Regime 择时
    - 选资产收益：超额收益的 50% 归因于资产选择
    - 交互收益：剩余部分

    Args:
        performances: 周期收益列表

    Returns:
        (timing_pnl, selection_pnl, interaction_pnl): 择时、选资产、交互收益

    语义定义:
        这是一个简化的归因方法，用于快速识别收益来源
        如需严格归因，应使用完整的 Brinson 或多因子模型
    """
    if not performances:
        return 0.0, 0.0, 0.0

    total_return = sum(p.portfolio_return for p in performances)

    # 择时收益：在正确 Regime 时的超额收益（启发式：30%）
    timing_pnl = 0.0
    for perf in performances:
        # 如果在正确 Regime 下，应该获得正收益
        if perf.portfolio_return > 0:
            timing_pnl += perf.portfolio_return * 0.3  # 假设 30% 归因于择时

    # 选资产收益：选择表现最好 vs 平均（启发式：50%）
    selection_pnl = 0.0
    for perf in performances:
        excess_return = perf.portfolio_return - perf.benchmark_return
        if excess_return > 0:
            selection_pnl += excess_return * 0.5  # 50% 归因于选资产

    # 交互收益：剩余部分
    interaction_pnl = total_return - timing_pnl - selection_pnl

    return timing_pnl, selection_pnl, interaction_pnl


def _identify_loss_source(
    performances: List[PeriodPerformance]
) -> Tuple[LossSource, float, List[RegimePeriod]]:
    """识别损失来源"""
    loss_periods = []

    for perf in performances:
        if perf.portfolio_return < 0:
            loss_periods.append(perf.period)

    if not loss_periods:
        return LossSource.UNKNOWN, 0.0, []

    total_loss = sum(
        p.portfolio_return for p in performances
        if p.portfolio_return < 0
    )

    # 判断主要损失来源
    low_confidence_count = sum(
        1 for p in performances
        if p.portfolio_return < 0 and p.period.confidence < 0.3
    )

    if low_confidence_count > len(loss_periods) / 2:
        source = LossSource.REGIME_TIMING_ERROR
    elif total_loss < -0.05:  # 损失超过 5%
        source = LossSource.MARKET_VOLATILITY
    else:
        source = LossSource.ASSET_SELECTION_ERROR

    return source, total_loss, loss_periods


def _generate_lessons(
    performances: List[PeriodPerformance],
    loss_source: LossSource
) -> Tuple[str, List[str]]:
    """生成经验总结"""
    suggestions = []

    if loss_source == LossSource.REGIME_TIMING_ERROR:
        lesson = "主要损失来源于 Regime 判断错误，特别是在低置信度时期。"
        suggestions = [
            "提高 Regime 判断的置信度阈值",
            "在置信度较低时减少仓位",
            "考虑增加数据源验证 Regime 判断",
        ]
    elif loss_source == LossSource.ASSET_SELECTION_ERROR:
        lesson = "主要损失来源于资产选择不当。"
        suggestions = [
            "优化准入矩阵的权重配置",
            "增加资产类别分散风险",
            "考虑动态调整资产权重",
        ]
    elif loss_source == LossSource.MARKET_VOLATILITY:
        lesson = "主要损失来源于市场剧烈波动。"
        suggestions = [
            "增加止损机制",
            "降低杠杆或仓位",
            "引入波动率目标控制",
        ]
    else:
        lesson = "整体表现良好，继续优化。"
        suggestions = [
            "保持当前策略",
            "关注极端市场情况",
        ]

    return lesson, suggestions


def _calculate_total_transaction_cost(trades: List) -> float:
    """计算总交易成本"""
    return sum(trade.cost for trade in trades)


def _build_period_attributions(performances: List[PeriodPerformance]) -> List[Dict]:
    """构建周期归因详情"""
    attributions = []

    for perf in performances:
        attributions.append({
            "start_date": perf.period.start_date,
            "end_date": perf.period.end_date,
            "regime": perf.period.regime,
            "confidence": perf.period.confidence,
            "portfolio_return": perf.portfolio_return,
            "benchmark_return": perf.benchmark_return,
            "excess_return": perf.portfolio_return - perf.benchmark_return,
            "asset_returns": perf.asset_returns,
        })

    return attributions


class AttributionAnalyzer:
    """
    归因分析器

    提供更高级的归因分析功能。
    """

    def __init__(self, config: Optional[AttributionConfig] = None):
        self.config = config or AttributionConfig()

    def analyze_regime_accuracy(
        self,
        regime_history: List[Dict],
        actual_regime_history: List[Dict]
    ) -> Dict:
        """
        分析 Regime 判断准确率

        Args:
            regime_history: 预测的 Regime 历史
            actual_regime_history: 实际发生的 Regime 历史

        Returns:
            Dict: 准确率统计
        """
        if not regime_history or not actual_regime_history:
            return {
                "total_periods": 0,
                "correct_predictions": 0,
                "accuracy": 0.0
            }

        correct = 0
        total = min(len(regime_history), len(actual_regime_history))

        for i in range(total):
            predicted = regime_history[i].get("regime")
            actual = actual_regime_history[i].get("regime")
            if predicted == actual:
                correct += 1

        return {
            "total_periods": total,
            "correct_predictions": correct,
            "accuracy": correct / total if total > 0 else 0.0,
            "regime_confusion_matrix": self._build_confusion_matrix(
                regime_history, actual_regime_history
            )
        }

    def _build_confusion_matrix(
        self,
        predicted: List[Dict],
        actual: List[Dict]
    ) -> Dict[str, Dict[str, int]]:
        """构建混淆矩阵"""
        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]
        matrix = {r: {} for r in regimes}

        for p in regimes:
            matrix[p] = {a: 0 for a in regimes}

        total = min(len(predicted), len(actual))
        for i in range(total):
            p_regime = predicted[i].get("regime")
            a_regime = actual[i].get("regime")
            if p_regime in matrix and a_regime in matrix[p_regime]:
                matrix[p_regime][a_regime] += 1

        return matrix

    def calculate_information_ratio(
        self,
        backtest_result,
        benchmark_returns: List[float]
    ) -> Optional[float]:
        """
        计算信息比率

        Args:
            backtest_result: 回测结果
            benchmark_returns: 基准收益率序列

        Returns:
            Optional[float]: 信息比率
        """
        if len(backtest_result.equity_curve) < 2 or not benchmark_returns:
            return None

        # 计算超额收益
        excess_returns = []
        for i in range(1, len(backtest_result.equity_curve)):
            prev_val = backtest_result.equity_curve[i - 1][1]
            curr_val = backtest_result.equity_curve[i][1]

            portfolio_return = (curr_val - prev_val) / prev_val
            benchmark_return = benchmark_returns[i - 1] if i - 1 < len(benchmark_returns) else 0

            excess_returns.append(portfolio_return - benchmark_return)

        if not excess_returns:
            return None

        # 计算均值和标准差
        mean_excess = sum(excess_returns) / len(excess_returns)
        variance = sum((r - mean_excess) ** 2 for r in excess_returns) / len(excess_returns)
        std_excess = math.sqrt(variance)

        if std_excess == 0:
            return None

        # 年化
        return mean_excess * 252 / (std_excess * math.sqrt(252))
