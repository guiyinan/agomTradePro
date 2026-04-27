"""
Domain Services for Attribution Analysis.

Pure business logic for analyzing backtest results and attributing PnL.
Only uses Python standard library (no pandas/numpy).
"""

import logging
import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .entities import (
    AttributionConfig,
    AttributionMethod,
    AttributionResult,
    BrinsonAttributionResult,
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    LossSource,
    OperationLog,
    PeriodPerformance,
    RecommendedAction,
    RegimePeriod,
    RegimeSnapshot,
    RegimeTransition,
    SignalEvent,
)

logger = logging.getLogger(__name__)


def analyze_attribution(
    backtest_result,
    regime_history: list[dict],
    asset_returns: dict[str, list[tuple[date, float]]],
    config: AttributionConfig | None = None,
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
        periods, backtest_result.equity_curve, asset_returns
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
        attribution_method=config.attribution_method,  # 使用配置中的归因方法
        loss_source=loss_source,
        loss_amount=loss_amount,
        loss_periods=loss_periods,
        lesson_learned=lesson,
        improvement_suggestions=suggestions,
        period_attributions=period_attributions,
    )


def _build_regime_periods(regime_history: list[dict]) -> list[RegimePeriod]:
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
            periods.append(
                RegimePeriod(
                    start_date=current_start,
                    end_date=entry_date,
                    regime=current_regime,
                    confidence=current_confidence,
                )
            )
            current_regime = regime
            current_start = entry_date
            current_confidence = confidence

    # 添加最后一个周期
    if current_regime and current_start:
        periods.append(
            RegimePeriod(
                start_date=current_start,
                end_date=regime_history[-1].get("date", current_start),
                regime=current_regime,
                confidence=current_confidence,
            )
        )

    return periods


def _calculate_period_performances(
    periods: list[RegimePeriod],
    equity_curve: list[tuple[date, float]],
    asset_returns: dict[str, list[tuple[date, float]]],
) -> list[PeriodPerformance]:
    """计算各周期表现"""
    performances = []

    if not equity_curve:
        return performances

    try:
        sorted_curve = sorted(equity_curve, key=lambda x: x[0])
    except TypeError:
        return performances

    def _get_value_on_or_after(target_date: date):
        for d, v in sorted_curve:
            if d >= target_date:
                return v
        return None

    def _get_value_on_or_before(target_date: date):
        for d, v in reversed(sorted_curve):
            if d <= target_date:
                return v
        return None

    for period in periods:
        # 获取周期起止的组合价值
        start_value = _get_value_on_or_after(period.start_date)
        end_value = _get_value_on_or_before(period.end_date)

        if start_value is None or end_value is None:
            continue

        portfolio_return = (end_value - start_value) / start_value

        # 获取各资产收益（简化：取首尾日期）
        asset_period_returns = {}
        for asset, returns in asset_returns.items():
            # 找到周期内的收益率
            period_returns = [r for d, r in returns if period.start_date <= d <= period.end_date]
            if period_returns:
                # 简化：使用平均收益
                asset_period_returns[asset] = sum(period_returns) / len(period_returns)
            else:
                asset_period_returns[asset] = 0.0

        benchmark_return = (
            sum(asset_period_returns.values()) / len(asset_period_returns)
            if asset_period_returns
            else 0.0
        )
        best_return = max(asset_period_returns.values()) if asset_period_returns else 0.0
        worst_return = min(asset_period_returns.values()) if asset_period_returns else 0.0

        performances.append(
            PeriodPerformance(
                period=period,
                portfolio_return=portfolio_return,
                benchmark_return=benchmark_return,
                best_asset_return=best_return,
                worst_asset_return=worst_return,
                asset_returns=asset_period_returns,
            )
        )

    return performances


def _heuristic_pnl_decomposition(
    performances: list[PeriodPerformance],
) -> tuple[float, float, float]:
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
    performances: list[PeriodPerformance],
) -> tuple[LossSource, float, list[RegimePeriod]]:
    """识别损失来源"""
    loss_periods = []

    for perf in performances:
        if perf.portfolio_return < 0:
            loss_periods.append(perf.period)

    if not loss_periods:
        return LossSource.UNKNOWN, 0.0, []

    total_loss = sum(p.portfolio_return for p in performances if p.portfolio_return < 0)

    # 判断主要损失来源
    low_confidence_count = sum(
        1 for p in performances if p.portfolio_return < 0 and p.period.confidence < 0.3
    )

    if low_confidence_count > len(loss_periods) / 2:
        source = LossSource.REGIME_TIMING_ERROR
    elif total_loss < -0.05:  # 损失超过 5%
        source = LossSource.MARKET_VOLATILITY
    else:
        source = LossSource.ASSET_SELECTION_ERROR

    return source, total_loss, loss_periods


def _generate_lessons(
    performances: list[PeriodPerformance], loss_source: LossSource
) -> tuple[str, list[str]]:
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


def _calculate_total_transaction_cost(trades: list) -> float:
    """计算总交易成本"""
    return sum(trade.cost for trade in trades)


def _build_period_attributions(performances: list[PeriodPerformance]) -> list[dict]:
    """构建周期归因详情"""
    attributions = []

    for perf in performances:
        attributions.append(
            {
                "start_date": perf.period.start_date,
                "end_date": perf.period.end_date,
                "regime": perf.period.regime,
                "confidence": perf.period.confidence,
                "portfolio_return": perf.portfolio_return,
                "benchmark_return": perf.benchmark_return,
                "excess_return": perf.portfolio_return - perf.benchmark_return,
                "asset_returns": perf.asset_returns,
            }
        )

    return attributions


def calculate_brinson_attribution(
    portfolio_returns: dict[str, list[tuple[date, float]]],
    benchmark_returns: dict[str, list[tuple[date, float]]],
    portfolio_weights: dict[str, dict[date, float]],
    benchmark_weights: dict[str, dict[date, float]],
    evaluation_period: tuple[date, date],
) -> BrinsonAttributionResult:
    """
    计算 Brinson 归因

    使用标准 Brinson 模型将超额收益分解为：
    1. Allocation Effect（配置效应）：资产配置偏离基准的贡献
    2. Selection Effect（选股效应）：同类资产内选股能力的贡献
    3. Interaction Effect（交互效应）：配置和选股的交互影响

    Args:
        portfolio_returns: 组合各资产收益率序列 {asset_class: [(date, return), ...]}
        benchmark_returns: 基准各资产收益率序列 {asset_class: [(date, return), ...]}
        portfolio_weights: 组合各资产权重 {asset_class: {date: weight}}
        benchmark_weights: 基准各资产权重 {asset_class: {date: weight}}
        evaluation_period: 评估期间 (start_date, end_date)

    Returns:
        BrinsonAttributionResult: Brinson 归因分析结果

    公式:
        Allocation Effect = Σ(wp_i - wb_i) * (rb_i - rb)
        Selection Effect = Σ wb_i * (rp_i - rb_i)
        Interaction Effect = Σ(wp_i - wb_i) * (rp_i - rb_i)

        其中:
        - wp_i: 组合中资产 i 的权重
        - wb_i: 基准中资产 i 的权重
        - rp_i: 组合中资产 i 的收益
        - rb_i: 基准中资产 i 的收益
        - rb: 基准整体收益 = Σ wb_i * rb_i
    """
    start_date, end_date = evaluation_period

    # 1. 计算整体收益率
    portfolio_return = _calculate_weighted_return(
        portfolio_returns, portfolio_weights, evaluation_period
    )
    benchmark_return = _calculate_weighted_return(
        benchmark_returns, benchmark_weights, evaluation_period
    )
    excess_return = portfolio_return - benchmark_return

    # 2. 获取所有涉及的资产类别
    all_assets = set(portfolio_returns.keys()) | set(benchmark_returns.keys())

    # 3. 计算各资产在评估期间的收益率
    portfolio_asset_returns = {}
    benchmark_asset_returns = {}
    benchmark_asset_weights = {}
    portfolio_asset_weights = {}

    for asset in all_assets:
        # 组合资产收益率
        if asset in portfolio_returns:
            portfolio_asset_returns[asset] = _calculate_average_return(
                portfolio_returns[asset], start_date, end_date
            )
        else:
            portfolio_asset_returns[asset] = 0.0

        # 基准资产收益率
        if asset in benchmark_returns:
            benchmark_asset_returns[asset] = _calculate_average_return(
                benchmark_returns[asset], start_date, end_date
            )
        else:
            benchmark_asset_returns[asset] = 0.0

        # 基准权重（使用期间平均权重）
        if asset in benchmark_weights:
            benchmark_asset_weights[asset] = _calculate_average_weight(
                benchmark_weights[asset], start_date, end_date
            )
        else:
            benchmark_asset_weights[asset] = 0.0

        # 组合权重（使用期间平均权重）
        if asset in portfolio_weights:
            portfolio_asset_weights[asset] = _calculate_average_weight(
                portfolio_weights[asset], start_date, end_date
            )
        else:
            portfolio_asset_weights[asset] = 0.0

    # 4. 计算 Brinson 分解
    allocation_effect = 0.0
    selection_effect = 0.0
    interaction_effect = 0.0

    sector_breakdown = {}

    for asset in all_assets:
        wp = portfolio_asset_weights[asset]
        wb = benchmark_asset_weights[asset]
        rp = portfolio_asset_returns[asset]
        rb = benchmark_asset_returns[asset]

        # Allocation Effect: (wp - wb) * (rb - benchmark_return)
        allocation_contribution = (wp - wb) * (rb - benchmark_return)
        allocation_effect += allocation_contribution

        # Selection Effect: wb * (rp - rb)
        selection_contribution = wb * (rp - rb)
        selection_effect += selection_contribution

        # Interaction Effect: (wp - wb) * (rp - rb)
        interaction_contribution = (wp - wb) * (rp - rb)
        interaction_effect += interaction_contribution

        # 记录各资产类别的分解
        sector_breakdown[asset] = {
            "allocation": allocation_contribution,
            "selection": selection_contribution,
            "interaction": interaction_contribution,
            "portfolio_weight": wp,
            "benchmark_weight": wb,
            "portfolio_return": rp,
            "benchmark_return": rb,
        }

    # 5. 计算归因总和（用于验证）
    attribution_sum = allocation_effect + selection_effect + interaction_effect

    # 6. 生成分时段分解（按月）
    period_breakdown = _generate_brinson_period_breakdown(
        portfolio_returns,
        benchmark_returns,
        portfolio_weights,
        benchmark_weights,
        start_date,
        end_date,
    )

    return BrinsonAttributionResult(
        benchmark_return=benchmark_return,
        portfolio_return=portfolio_return,
        excess_return=excess_return,
        allocation_effect=allocation_effect,
        selection_effect=selection_effect,
        interaction_effect=interaction_effect,
        attribution_sum=attribution_sum,
        period_breakdown=period_breakdown,
        sector_breakdown=sector_breakdown,
    )


def _calculate_weighted_return(
    returns: dict[str, list[tuple[date, float]]],
    weights: dict[str, dict[date, float]],
    evaluation_period: tuple[date, date],
) -> float:
    """计算加权收益率"""
    start_date, end_date = evaluation_period

    total_return = 0.0

    for asset, return_series in returns.items():
        # 计算该资产的平均收益率
        asset_return = _calculate_average_return(return_series, start_date, end_date)

        # 获取该资产的平均权重
        if asset in weights:
            asset_weight = _calculate_average_weight(weights[asset], start_date, end_date)
        else:
            asset_weight = 0.0

        total_return += asset_weight * asset_return

    return total_return


def _calculate_average_return(
    return_series: list[tuple[date, float]],
    start_date: date,
    end_date: date,
) -> float:
    """计算期间平均收益率"""
    relevant_returns = [r for d, r in return_series if start_date <= d <= end_date]

    if not relevant_returns:
        return 0.0

    return sum(relevant_returns) / len(relevant_returns)


def _calculate_average_weight(
    weight_dict: dict[date, float],
    start_date: date,
    end_date: date,
) -> float:
    """计算期间平均权重"""
    relevant_weights = [w for d, w in weight_dict.items() if start_date <= d <= end_date]

    if not relevant_weights:
        return 0.0

    return sum(relevant_weights) / len(relevant_weights)


def _generate_brinson_period_breakdown(
    portfolio_returns: dict[str, list[tuple[date, float]]],
    benchmark_returns: dict[str, list[tuple[date, float]]],
    portfolio_weights: dict[str, dict[date, float]],
    benchmark_weights: dict[str, dict[date, float]],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """生成分时段的 Brinson 分解"""
    period_breakdown = []

    # 简化：按月分解
    current_date = start_date
    period_num = 1

    while current_date < end_date:
        # 计算该月的结束日期
        month_end = date(current_date.year, current_date.month + 1, 1) - timedelta(days=1)
        period_end = min(month_end, end_date)

        # 计算该期间的 Brinson 分解
        try:
            period_result = calculate_brinson_attribution(
                portfolio_returns=portfolio_returns,
                benchmark_returns=benchmark_returns,
                portfolio_weights=portfolio_weights,
                benchmark_weights=benchmark_weights,
                evaluation_period=(current_date, period_end),
            )

            period_breakdown.append(
                {
                    "period": f"Period {period_num}",
                    "start_date": current_date,
                    "end_date": period_end,
                    "portfolio_return": period_result.portfolio_return,
                    "benchmark_return": period_result.benchmark_return,
                    "excess_return": period_result.excess_return,
                    "allocation_effect": period_result.allocation_effect,
                    "selection_effect": period_result.selection_effect,
                    "interaction_effect": period_result.interaction_effect,
                }
            )
        except Exception as exc:
            logger.debug(
                "Skipping Brinson period %s -> %s due to attribution error: %s",
                current_date,
                period_end,
                exc,
            )

        # 移动到下个月
        if current_date.month == 12:
            current_date = date(current_date.year + 1, 1, 1)
        else:
            current_date = date(current_date.year, current_date.month + 1, 1)
        period_num += 1

    return period_breakdown


class AttributionAnalyzer:
    """
    归因分析器

    提供更高级的归因分析功能。
    """

    def __init__(self, config: AttributionConfig | None = None):
        self.config = config or AttributionConfig()

    def analyze_regime_accuracy(
        self, regime_history: list[dict], actual_regime_history: list[dict]
    ) -> dict:
        """
        分析 Regime 判断准确率

        Args:
            regime_history: 预测的 Regime 历史
            actual_regime_history: 实际发生的 Regime 历史

        Returns:
            Dict: 准确率统计
        """
        if not regime_history or not actual_regime_history:
            return {"total_periods": 0, "correct_predictions": 0, "accuracy": 0.0}

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
            ),
        }

    def _build_confusion_matrix(
        self, predicted: list[dict], actual: list[dict]
    ) -> dict[str, dict[str, int]]:
        """构建混淆矩阵"""
        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]
        matrix = {r: {} for r in regimes}

        for p in regimes:
            matrix[p] = dict.fromkeys(regimes, 0)

        total = min(len(predicted), len(actual))
        for i in range(total):
            p_regime = predicted[i].get("regime")
            a_regime = actual[i].get("regime")
            if p_regime in matrix and a_regime in matrix[p_regime]:
                matrix[p_regime][a_regime] += 1

        return matrix

    def calculate_information_ratio(
        self, backtest_result, benchmark_returns: list[float]
    ) -> float | None:
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


# ============ 指标表现评估服务 ============


class IndicatorPerformanceAnalyzer:
    """
    指标表现分析器（纯业务逻辑）

    评估单个指标对 Regime 判断的预测能力。
    """

    def __init__(self, threshold_config: IndicatorThresholdConfig):
        """
        初始化分析器

        Args:
            threshold_config: 指标阈值配置
        """
        self.threshold_config = threshold_config

    def analyze_performance(
        self,
        indicator_code: str,
        indicator_values: list[tuple[date, float]],
        regime_history: list[RegimeSnapshot],
        evaluation_start: date,
        evaluation_end: date,
    ) -> IndicatorPerformanceReport:
        """
        分析指标表现

        步骤：
        1. 生成信号序列（基于阈值）
        2. 对比 Regime 历史，计算混淆矩阵
        3. 计算统计指标（precision/recall/F1）
        4. 计算领先时间
        5. 计算子样本期稳定性
        6. 生成建议

        Args:
            indicator_code: 指标代码
            indicator_values: 指标历史值 [(date, value), ...]
            regime_history: Regime 判定历史
            evaluation_start: 评估起始日期
            evaluation_end: 评估结束日期

        Returns:
            IndicatorPerformanceReport: 指标表现报告
        """
        # 1. 生成信号序列
        signals = self._generate_signals(indicator_values, evaluation_start, evaluation_end)

        # 2. 将 regime_history 转为字典方便查找
        regime_dict = {r.observed_at: r for r in regime_history}

        # 3. 计算混淆矩阵
        tp, fp, tn, fn = self._calculate_confusion_matrix(
            signals, regime_dict, evaluation_start, evaluation_end
        )

        # 4. 计算统计指标
        precision, recall, f1_score, accuracy = self._calculate_metrics(tp, fp, tn, fn)

        # 5. 计算领先时间
        lead_time_mean, lead_time_std = self._calculate_lead_time(
            signals, regime_dict, evaluation_start, evaluation_end
        )

        # 6. 计算稳定性
        pre_2015_corr, post_2015_corr, stability_score = self._calculate_stability(
            indicator_values, regime_dict, evaluation_start, evaluation_end
        )

        # 7. 计算衰减率和信号强度
        decay_rate, signal_strength = self._calculate_decay_and_strength(
            signals, regime_dict, evaluation_start, evaluation_end
        )

        # 8. 生成建议
        recommended_action, recommended_weight, confidence = self._generate_recommendation(
            f1_score, stability_score, decay_rate, signal_strength
        )

        return IndicatorPerformanceReport(
            indicator_code=indicator_code,
            evaluation_period_start=evaluation_start,
            evaluation_period_end=evaluation_end,
            true_positive_count=tp,
            false_positive_count=fp,
            true_negative_count=tn,
            false_negative_count=fn,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            accuracy=accuracy,
            lead_time_mean=lead_time_mean,
            lead_time_std=lead_time_std,
            pre_2015_correlation=pre_2015_corr,
            post_2015_correlation=post_2015_corr,
            stability_score=stability_score,
            # Report contract uses enum names ("KEEP"/"INCREASE"/"DECREASE"/"REMOVE").
            recommended_action=recommended_action.name,
            recommended_weight=recommended_weight,
            confidence_level=confidence,
            decay_rate=decay_rate,
            signal_strength=signal_strength,
        )

    def _generate_signals(
        self,
        indicator_values: list[tuple[date, float]],
        start_date: date,
        end_date: date,
    ) -> list[SignalEvent]:
        """
        基于阈值生成信号

        信号规则：
        - value > level_high: BULLISH（看多）
        - value < level_low: BEARISH（看空）
        - 中间区域: NEUTRAL（中性）

        Args:
            indicator_values: 指标历史值
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[SignalEvent]: 信号事件列表
        """
        signals = []
        level_low = self.threshold_config.level_low
        level_high = self.threshold_config.level_high
        # Macro data may be published 1-2 days after period end; keep a small grace window.
        effective_end = end_date + timedelta(days=3)

        for obs_date, value in indicator_values:
            if not (start_date <= obs_date <= effective_end):
                continue

            if value is None:
                continue

            # 确定信号类型
            if level_high is not None and value > level_high:
                signal_type = "BULLISH"
                threshold_used = level_high
            elif level_low is not None and value < level_low:
                signal_type = "BEARISH"
                threshold_used = level_low
            else:
                signal_type = "NEUTRAL"
                threshold_used = (level_low + level_high) / 2 if level_low and level_high else 0.0

            # 计算置信度（基于距离阈值的程度）
            if signal_type == "BULLISH" and level_high is not None:
                confidence = min(1.0, (value - level_high) / abs(level_high) * 0.5 + 0.5)
            elif signal_type == "BEARISH" and level_low is not None:
                confidence = min(1.0, (level_low - value) / abs(level_low) * 0.5 + 0.5)
            else:
                confidence = 0.5

            signals.append(
                SignalEvent(
                    indicator_code=self.threshold_config.indicator_code,
                    signal_date=obs_date,
                    signal_type=signal_type,
                    signal_value=value,
                    threshold_used=threshold_used,
                    confidence=confidence,
                )
            )

        return signals

    def _calculate_confusion_matrix(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[int, int, int, int]:
        """
        计算混淆矩阵

        将信号与实际 Regime 对比：
        - 真阳性 (TP): 预测扩张/过热，实际确实是扩张/过热
        - 假阳性 (FP): 预测扩张/过热，实际是通缩/滞胀
        - 真阴性 (TN): 预测通缩/滞胀，实际确实是通缩/滞胀
        - 假阴性 (FN): 预测通缩/滞胀，实际是扩张/过热

        Args:
            signals: 信号事件列表
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (tp, fp, tn, fn): 混淆矩阵四个值
        """
        tp = fp = tn = fn = 0

        for signal in signals:
            # 找到最近的 Regime 判定
            regime = regime_dict.get(signal.signal_date)
            if regime is None:
                # 找最近的日期
                closest_date = min(
                    (d for d in regime_dict.keys() if d <= signal.signal_date), default=None
                )
                if closest_date:
                    regime = regime_dict[closest_date]
                else:
                    continue

            # 定义扩张/过热 vs 通缩/滞胀
            is_bullish_signal = signal.signal_type in ("BULLISH", "NEUTRAL_POSITIVE")
            is_expansion_regime = regime.dominant_regime in ("Recovery", "Overheat")

            if is_bullish_signal and is_expansion_regime:
                tp += 1
            elif is_bullish_signal and not is_expansion_regime:
                fp += 1
            elif not is_bullish_signal and not is_expansion_regime:
                tn += 1
            else:  # not is_bullish_signal and is_expansion_regime
                fn += 1

        return tp, fp, tn, fn

    def _calculate_metrics(
        self,
        tp: int,
        fp: int,
        tn: int,
        fn: int,
    ) -> tuple[float, float, float, float]:
        """
        计算统计指标

        Args:
            tp, fp, tn, fn: 混淆矩阵值

        Returns:
            (precision, recall, f1_score, accuracy)
        """
        total = tp + fp + tn + fn
        if total == 0:
            return 0.0, 0.0, 0.0, 0.0

        # Precision = TP / (TP + FP)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

        # Recall = TP / (TP + FN)
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        # F1 Score = 2 * Precision * Recall / (Precision + Recall)
        if precision + recall > 0:
            f1_score = 2 * precision * recall / (precision + recall)
        else:
            f1_score = 0.0

        # Accuracy = (TP + TN) / Total
        accuracy = (tp + tn) / total if total > 0 else 0.0

        return precision, recall, f1_score, accuracy

    def _calculate_lead_time(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[float, float]:
        """
        计算领先时间

        计算信号领先于 Regime 变化的平均时间（月）

        Args:
            signals: 信号事件列表
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (mean_lead_time, std_lead_time): 平均领先时间和标准差
        """
        lead_times = []

        # 排序信号
        sorted_signals = sorted(signals, key=lambda s: s.signal_date)

        # 排序 Regime 历史
        sorted_regimes = sorted(regime_dict.items(), key=lambda x: x[0])

        # 检测 Regime 变化
        for i in range(1, len(sorted_regimes)):
            prev_date, prev_regime = sorted_regimes[i - 1]
            curr_date, curr_regime = sorted_regimes[i]

            # 检测 Regime 变化
            if prev_regime.dominant_regime != curr_regime.dominant_regime:
                # 找到变化前的信号
                regime_change_date = curr_date
                for signal in sorted_signals:
                    if signal.signal_date < regime_change_date:
                        # 计算领先时间（天 -> 月）
                        lead_days = (regime_change_date - signal.signal_date).days
                        lead_months = lead_days / 30.0  # 近似

                        # 只统计合理的领先时间（0-12个月）
                        if 0 <= lead_months <= 12:
                            lead_times.append(lead_months)
                    break

        if not lead_times:
            return 0.0, 0.0

        # 计算均值和标准差
        mean_lead = sum(lead_times) / len(lead_times)
        variance = sum((t - mean_lead) ** 2 for t in lead_times) / len(lead_times)
        std_lead = math.sqrt(variance)

        return mean_lead, std_lead

    def _calculate_stability(
        self,
        indicator_values: list[tuple[date, float]],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[float | None, float | None, float]:
        """
        计算稳定性

        通过分段相关性评估指标在不同时期的表现稳定性。

        Args:
            indicator_values: 指标历史值
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (pre_2015_correlation, post_2015_correlation, stability_score)
        """
        cutoff_date = date(2015, 1, 1)

        # 分段
        pre_values = [(d, v) for d, v in indicator_values if start_date <= d < cutoff_date]
        post_values = [(d, v) for d, v in indicator_values if cutoff_date <= d <= end_date]

        # 计算相关性（简化：基于信号一致率）
        # 在实际应用中，这里应该使用 Pearson 或 Spearman 相关系数
        # 由于 Domain 层不能用 numpy，我们简化处理

        if len(pre_values) < 10 or len(post_values) < 10:
            return None, None, 0.5  # 数据不足

        # 简化的相关性计算（使用信号变化的一致性）
        pre_corr = self._calculate_simple_correlation(
            pre_values, regime_dict, start_date, cutoff_date
        )
        post_corr = self._calculate_simple_correlation(
            post_values, regime_dict, cutoff_date, end_date
        )

        # 稳定性分数 = 1 - |pre - post|
        if pre_corr is not None and post_corr is not None:
            stability_score = 1.0 - abs(pre_corr - post_corr)
            stability_score = max(0.0, min(1.0, stability_score))
        else:
            stability_score = 0.5

        return pre_corr, post_corr, stability_score

    def _calculate_simple_correlation(
        self,
        values: list[tuple[date, float]],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> float | None:
        """
        计算简化的相关性指标

        使用信号与 Regime 的一致率作为相关性代理
        """
        if not values:
            return None

        consistent = 0
        total = 0

        level_low = self.threshold_config.level_low
        level_high = self.threshold_config.level_high

        for obs_date, value in values:
            if not (start_date <= obs_date <= end_date):
                continue

            # 找到对应的 Regime
            regime = regime_dict.get(obs_date)
            if regime is None:
                continue

            # 判断指标方向
            is_high = value > level_high if level_high is not None else False
            is_low = value < level_low if level_low is not None else False

            # 判断 Regime 方向
            is_expansion = regime.dominant_regime in ("Recovery", "Overheat")

            # 检查一致性
            if (is_high and is_expansion) or (is_low and not is_expansion):
                consistent += 1
            total += 1

        if total == 0:
            return None

        return consistent / total

    def _calculate_decay_and_strength(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[float, float]:
        """
        计算信号衰减率和强度

        Args:
            signals: 信号事件列表
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (decay_rate, signal_strength)
        """
        if not signals:
            return 0.0, 0.0

        # 计算信号强度（平均置信度）
        signal_strength = sum(s.confidence for s in signals) / len(signals)

        # 计算衰减率（后期信号准确率下降程度）
        mid_point = len(signals) // 2
        early_signals = signals[:mid_point]
        late_signals = signals[mid_point:]

        early_accuracy = self._calculate_signal_accuracy(early_signals, regime_dict)
        late_accuracy = self._calculate_signal_accuracy(late_signals, regime_dict)

        if early_accuracy is not None and late_accuracy is not None:
            decay_rate = max(0.0, early_accuracy - late_accuracy)
        else:
            decay_rate = 0.0

        return decay_rate, signal_strength

    def _calculate_signal_accuracy(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
    ) -> float | None:
        """计算信号准确率"""
        if not signals:
            return None

        correct = 0
        for signal in signals:
            regime = regime_dict.get(signal.signal_date)
            if regime is None:
                continue

            is_bullish_signal = signal.signal_type in ("BULLISH", "NEUTRAL_POSITIVE")
            is_expansion_regime = regime.dominant_regime in ("Recovery", "Overheat")

            if is_bullish_signal == is_expansion_regime:
                correct += 1

        return correct / len(signals) if signals else None

    def _generate_recommendation(
        self,
        f1_score: float,
        stability_score: float,
        decay_rate: float,
        signal_strength: float,
    ) -> tuple[RecommendedAction, float, float]:
        """
        生成建议

        根据各项指标的表现，生成建议操作和权重调整。

        规则：
        - F1 >= 0.6: KEEP
        - 0.4 <= F1 < 0.6: DECREASE
        - F1 < 0.4: REMOVE
        - 稳定性 < 0.5: DECREASE
        - 衰减率 > 0.2: DECREASE

        Args:
            f1_score: F1 分数
            stability_score: 稳定性分数
            decay_rate: 衰减率
            signal_strength: 信号强度

        Returns:
            (recommended_action, recommended_weight, confidence_level)
        """
        # 获取配置阈值
        keep_min_f1 = self.threshold_config.keep_min_f1
        reduce_min_f1 = self.threshold_config.reduce_min_f1
        remove_max_f1 = self.threshold_config.remove_max_f1
        decay_threshold = self.threshold_config.decay_threshold

        base_weight = self.threshold_config.base_weight
        min_weight = self.threshold_config.min_weight
        max_weight = self.threshold_config.max_weight

        # 判断建议操作
        action = RecommendedAction.KEEP
        new_weight = base_weight

        if f1_score >= keep_min_f1 and stability_score >= 0.6 and decay_rate < decay_threshold:
            # 表现良好，保持或增加权重
            if f1_score > 0.8 and stability_score > 0.8:
                action = RecommendedAction.INCREASE
                proposed_weight = base_weight * 1.2
                if max_weight is None or max_weight <= base_weight:
                    new_weight = proposed_weight
                else:
                    new_weight = min(max_weight, proposed_weight)
            else:
                action = RecommendedAction.KEEP
                new_weight = base_weight
            confidence = f1_score * stability_score

        elif f1_score < remove_max_f1 or stability_score < 0.3 or decay_rate > decay_threshold * 2:
            # 表现很差，建议移除
            action = RecommendedAction.REMOVE
            new_weight = min_weight
            confidence = 1.0 - f1_score

        else:
            # 表现一般，降低权重
            action = RecommendedAction.DECREASE
            # 根据 F1 分数线性调整权重
            weight_factor = (f1_score - remove_max_f1) / (keep_min_f1 - remove_max_f1)
            new_weight = max(min_weight, base_weight * weight_factor)
            confidence = 0.5

        return action, new_weight, confidence


class ThresholdValidator:
    """
    阈值验证器

    验证历史阈值配置的表现。
    """

    def __init__(self):
        self.analyzers: dict[str, IndicatorPerformanceAnalyzer] = {}

    def add_indicator(self, indicator_code: str, threshold_config: IndicatorThresholdConfig):
        """添加指标分析器"""
        self.analyzers[indicator_code] = IndicatorPerformanceAnalyzer(threshold_config)

    def validate_all(
        self,
        indicators_data: dict[str, list[tuple[date, float]]],
        regime_history: list[RegimeSnapshot],
        evaluation_start: date,
        evaluation_end: date,
    ) -> list[IndicatorPerformanceReport]:
        """
        验证所有指标

        Args:
            indicators_data: 指标数据 {indicator_code: [(date, value), ...]}
            regime_history: Regime 历史
            evaluation_start: 评估起始日期
            evaluation_end: 评估结束日期

        Returns:
            List[IndicatorPerformanceReport]: 所有指标的表现报告
        """
        reports = []

        for indicator_code, analyzer in self.analyzers.items():
            if indicator_code not in indicators_data:
                continue

            try:
                report = analyzer.analyze_performance(
                    indicator_code=indicator_code,
                    indicator_values=indicators_data[indicator_code],
                    regime_history=regime_history,
                    evaluation_start=evaluation_start,
                    evaluation_end=evaluation_end,
                )
                reports.append(report)
            except Exception as e:
                # 记录错误但继续处理其他指标
                import logging

                logging.warning(f"Failed to analyze {indicator_code}: {e}")

        return reports


# ============ MCP/SDK 操作审计日志服务 ============


class OperationLogFactory:
    """
    操作日志工厂

    负责创建操作日志实体，封装创建逻辑和参数推断。
    """

    @staticmethod
    def create_from_mcp_call(
        request_id: str,
        tool_name: str,
        user_id: int | None = None,
        username: str = "anonymous",
        source: str | None = None,
        operation_type: str | None = None,
        module: str | None = None,
        action: str | None = None,
        request_params: dict | None = None,
        response_payload: Any | None = None,
        response_text: str = "",
        response_status: int = 200,
        response_message: str = "",
        error_code: str = "",
        exception_traceback: str = "",
        duration_ms: int | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
        client_id: str = "",
        mcp_role: str = "",
        sdk_version: str = "",
        resource_type: str = "",
        resource_id: str | None = None,
        mcp_client_id: str = "",
        request_method: str = "MCP",
        request_path: str = "",
    ) -> "OperationLog":
        """
        从 MCP 工具调用创建操作日志

        Args:
            request_id: 链路追踪ID
            tool_name: MCP 工具名
            user_id: 用户ID
            username: 用户名
            source: 来源（MCP/SDK/API），不传则自动推断
            operation_type: 操作类型，不传则自动推断
            module: 模块名，不传则自动推断
            action: 动作类型，不传则自动推断
            request_params: 请求参数（将被脱敏）
            response_payload: 结构化响应内容（将被脱敏）
            response_text: 响应文本快照
            response_status: 响应状态码
            response_message: 响应消息
            error_code: 错误代码
            exception_traceback: 异常堆栈
            duration_ms: 耗时（毫秒）
            ip_address: IP 地址
            user_agent: User Agent
            client_id: 客户端ID
            mcp_role: MCP 角色
            sdk_version: SDK 版本
            resource_type: 资源类型
            resource_id: 资源ID
            mcp_client_id: MCP 客户端 ID
            request_method: 请求方法
            request_path: 请求路径

        Returns:
            OperationLog: 操作日志实体
        """
        from .entities import (
            OperationAction,
            OperationLog,
            OperationSource,
            OperationType,
            infer_action_from_tool,
            infer_module_from_tool,
        )

        # 推断或使用传入的模块和动作
        if not module:
            module = infer_module_from_tool(tool_name)
        if not action:
            action_enum = infer_action_from_tool(tool_name)
            action = action_enum.value

        # 解析枚举值
        if source:
            source_enum = OperationSource(source.upper())
        else:
            source_enum = OperationSource.MCP

        if operation_type:
            operation_type_enum = OperationType(operation_type.upper())
        else:
            operation_type_enum = OperationType.MCP_CALL

        if isinstance(action, str):
            action_enum = OperationAction(action.upper())
        else:
            action_enum = action

        # 构建请求路径
        if not request_path:
            request_path = f"/mcp/tools/{tool_name}"

        return OperationLog.create(
            request_id=request_id,
            user_id=user_id,
            username=username,
            source=source_enum,
            operation_type=operation_type_enum,
            module=module,
            action=action_enum,
            mcp_tool_name=tool_name,
            request_params=request_params,
            response_payload=response_payload,
            response_text=response_text,
            response_status=response_status,
            response_message=response_message,
            error_code=error_code,
            exception_traceback=exception_traceback,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            client_id=client_id,
            resource_type=resource_type,
            resource_id=resource_id,
            mcp_client_id=mcp_client_id or client_id,
            mcp_role=mcp_role,
            sdk_version=sdk_version,
            request_method=request_method,
            request_path=request_path,
        )

    @staticmethod
    def create_from_api_call(
        request_id: str,
        user_id: int | None,
        username: str,
        request_method: str,
        request_path: str,
        request_params: dict | None = None,
        response_payload: Any | None = None,
        response_text: str = "",
        response_status: int = 200,
        response_message: str = "",
        error_code: str = "",
        exception_traceback: str = "",
        duration_ms: int | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
        client_id: str = "",
        resource_type: str = "",
        resource_id: str | None = None,
    ) -> "OperationLog":
        """
        从 API 调用创建操作日志

        Args:
            request_id: 链路追踪ID
            user_id: 用户ID
            username: 用户名
            request_method: 请求方法（GET/POST/PUT/DELETE）
            request_path: 请求路径
            request_params: 请求参数（将被脱敏）
            response_payload: 结构化响应内容（将被脱敏）
            response_text: 响应文本快照
            response_status: 响应状态码
            response_message: 响应消息
            error_code: 错误代码
            exception_traceback: 异常堆栈
            duration_ms: 耗时（毫秒）
            ip_address: IP 地址
            user_agent: User Agent
            client_id: 客户端ID
            resource_type: 资源类型
            resource_id: 资源ID

        Returns:
            OperationLog: 操作日志实体
        """
        from .entities import (
            OperationAction,
            OperationLog,
            OperationSource,
            OperationType,
            infer_module_from_tool,
        )

        # 从路径推断模块
        module = infer_module_from_tool(request_path)

        # 从请求方法推断动作
        action_map = {
            "GET": OperationAction.READ,
            "POST": OperationAction.CREATE,
            "PUT": OperationAction.UPDATE,
            "PATCH": OperationAction.UPDATE,
            "DELETE": OperationAction.DELETE,
        }
        action = action_map.get(request_method.upper(), OperationAction.READ)

        # 判断操作类型
        if action in (OperationAction.CREATE, OperationAction.UPDATE, OperationAction.DELETE):
            operation_type = OperationType.DATA_MODIFY
        else:
            operation_type = OperationType.API_ACCESS

        return OperationLog.create(
            request_id=request_id,
            user_id=user_id,
            username=username,
            source=OperationSource.API,
            operation_type=operation_type,
            module=module,
            action=action,
            request_method=request_method,
            request_path=request_path,
            request_params=request_params,
            response_payload=response_payload,
            response_text=response_text,
            response_status=response_status,
            response_message=response_message,
            error_code=error_code,
            exception_traceback=exception_traceback,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            client_id=client_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
