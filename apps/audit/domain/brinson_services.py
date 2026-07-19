"""Brinson attribution domain services for Audit.

Pure business logic decomposing excess returns with the standard Brinson model.
Only uses Python standard library (no pandas/numpy).
"""

import logging
from datetime import date, timedelta

from .entities import BrinsonAttributionResult

logger = logging.getLogger(__name__)

__all__ = [
    "calculate_brinson_attribution",
]


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
