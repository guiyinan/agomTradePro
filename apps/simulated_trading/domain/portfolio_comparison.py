"""Pure calculations for comparing two investment portfolios."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

from apps.simulated_trading.domain.entities import PerformanceReport, ValuationTimelinePoint


@dataclass(frozen=True)
class PortfolioComparisonAccount:
    """Identify one portfolio in a comparison."""

    account_id: int
    account_name: str


@dataclass(frozen=True)
class PortfolioComparisonHolding:
    """Provide one current holding with optional valuation and industry evidence."""

    asset_code: str
    asset_name: str
    industry: str | None
    market_value: float | None


@dataclass(frozen=True)
class PortfolioComparisonMetric:
    """Show one left/right metric and its arithmetic difference."""

    key: str
    metric_label: str
    unit: str
    left: float | None
    right: float | None
    difference: float | None


@dataclass(frozen=True)
class PortfolioComparisonCurvePoint:
    """Align two normalized cash-flow-aware curves on one observation date."""

    date: date
    left: float | None
    right: float | None


@dataclass(frozen=True)
class PortfolioHoldingComparisonRow:
    """Compare one current holding across two portfolios."""

    asset_code: str
    asset_name: str
    industry: str | None
    left_weight_percentage: float | None
    right_weight_percentage: float | None
    difference_percentage_points: float | None


@dataclass(frozen=True)
class PortfolioIndustryComparisonRow:
    """Compare one current industry allocation across two portfolios."""

    industry: str
    left_weight_percentage: float | None
    right_weight_percentage: float | None
    difference_percentage_points: float | None


@dataclass(frozen=True)
class PortfolioOverlapSummaryRow:
    """Expose holding overlap to portable summary charts."""

    overlap_label: str
    overlap_percentage: float | None


@dataclass(frozen=True)
class PortfolioHoldingsComparison:
    """Summarize current holding overlap and industry allocation differences."""

    overlap_percentage: float | None
    shared_count: int
    left_only_count: int
    right_only_count: int
    valuation_known: bool
    classification_known: bool
    rows: list[PortfolioHoldingComparisonRow]
    industry_rows: list[PortfolioIndustryComparisonRow]
    overlap_rows: list[PortfolioOverlapSummaryRow]


@dataclass(frozen=True)
class PortfolioComparisonResult:
    """Return the complete read-only two-portfolio comparison."""

    outcome: Literal["success", "partial"]
    left_account: PortfolioComparisonAccount
    right_account: PortfolioComparisonAccount
    relative_twr_percentage_points: float | None
    metrics: list[PortfolioComparisonMetric]
    curve: list[PortfolioComparisonCurvePoint]
    holdings: PortfolioHoldingsComparison
    warnings: list[str]


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 6)


def _metric(
    key: str,
    label: str,
    unit: str,
    left: float | None,
    right: float | None,
) -> PortfolioComparisonMetric:
    return PortfolioComparisonMetric(key, label, unit, left, right, _difference(left, right))


def _metrics(
    left: PerformanceReport,
    right: PerformanceReport,
) -> list[PortfolioComparisonMetric]:
    return [
        _metric("twr", "时间加权收益率", "percent", left.returns.twr, right.returns.twr),
        _metric("mwr", "资金加权收益率", "percent", left.returns.mwr, right.returns.mwr),
        _metric(
            "annualized_twr",
            "年化时间加权收益率",
            "percent",
            left.returns.annualized_twr,
            right.returns.annualized_twr,
        ),
        _metric(
            "max_drawdown",
            "最大回撤",
            "percent",
            left.risk.max_drawdown,
            right.risk.max_drawdown,
        ),
        _metric(
            "volatility",
            "年化波动率",
            "percent",
            left.risk.volatility,
            right.risk.volatility,
        ),
        _metric("sharpe", "夏普比率", "ratio", left.ratios.sharpe, right.ratios.sharpe),
        _metric("sortino", "索提诺比率", "ratio", left.ratios.sortino, right.ratios.sortino),
    ]


def _curve(
    left: list[ValuationTimelinePoint],
    right: list[ValuationTimelinePoint],
) -> list[PortfolioComparisonCurvePoint]:
    left_by_date = {point.date: point for point in left}
    right_by_date = {point.date: point for point in right}

    def normalized(point: ValuationTimelinePoint | None) -> float | None:
        if point is None or not point.correction_coverage_known or point.twr_cumulative is None:
            return None
        value = 100.0 + point.twr_cumulative
        return round(value, 6) if math.isfinite(value) else None

    return [
        PortfolioComparisonCurvePoint(
            date=observation_date,
            left=normalized(left_by_date.get(observation_date)),
            right=normalized(right_by_date.get(observation_date)),
        )
        for observation_date in sorted(set(left_by_date) | set(right_by_date))
    ]


def _weights(
    holdings: list[PortfolioComparisonHolding],
) -> tuple[dict[str, float], bool]:
    known = all(
        holding.market_value is not None
        and math.isfinite(holding.market_value)
        and holding.market_value >= 0
        for holding in holdings
    )
    if not known:
        return {}, False
    values = {holding.asset_code: float(holding.market_value or 0.0) for holding in holdings}
    total = sum(values.values())
    if total <= 0:
        return {}, True
    return {code: value / total * 100.0 for code, value in values.items()}, True


def _holding_comparison(
    left: list[PortfolioComparisonHolding],
    right: list[PortfolioComparisonHolding],
) -> PortfolioHoldingsComparison:
    left_by_code = {holding.asset_code: holding for holding in left}
    right_by_code = {holding.asset_code: holding for holding in right}
    left_weights, left_known = _weights(left)
    right_weights, right_known = _weights(right)
    shared = set(left_by_code) & set(right_by_code)
    overlap = (
        round(sum(min(left_weights[code], right_weights[code]) for code in shared), 6)
        if left_known and right_known and left_weights and right_weights
        else None
    )
    rows: list[PortfolioHoldingComparisonRow] = []
    for code in sorted(set(left_by_code) | set(right_by_code)):
        left_holding = left_by_code.get(code)
        right_holding = right_by_code.get(code)
        sample = left_holding or right_holding
        assert sample is not None
        left_weight = left_weights.get(code) if left_known else None
        right_weight = right_weights.get(code) if right_known else None
        rows.append(
            PortfolioHoldingComparisonRow(
                asset_code=code,
                asset_name=sample.asset_name,
                industry=sample.industry,
                left_weight_percentage=left_weight,
                right_weight_percentage=right_weight,
                difference_percentage_points=_difference(left_weight, right_weight),
            )
        )

    industry_names = sorted(
        {
            (
                holding.industry.strip()
                if holding.industry and holding.industry.strip()
                else "行业未知"
            )
            for holding in (*left, *right)
        }
    )
    industry_rows = [
        PortfolioIndustryComparisonRow(
            industry=industry,
            left_weight_percentage=(
                round(
                    sum(
                        left_weights.get(holding.asset_code, 0.0)
                        for holding in left
                        if (holding.industry or "行业未知").strip() == industry
                    ),
                    6,
                )
                if left_known
                else None
            ),
            right_weight_percentage=(
                round(
                    sum(
                        right_weights.get(holding.asset_code, 0.0)
                        for holding in right
                        if (holding.industry or "行业未知").strip() == industry
                    ),
                    6,
                )
                if right_known
                else None
            ),
            difference_percentage_points=None,
        )
        for industry in industry_names
    ]
    industry_rows = [
        PortfolioIndustryComparisonRow(
            industry=row.industry,
            left_weight_percentage=row.left_weight_percentage,
            right_weight_percentage=row.right_weight_percentage,
            difference_percentage_points=_difference(
                row.left_weight_percentage, row.right_weight_percentage
            ),
        )
        for row in industry_rows
    ]
    return PortfolioHoldingsComparison(
        overlap_percentage=overlap,
        shared_count=len(shared),
        left_only_count=len(set(left_by_code) - set(right_by_code)),
        right_only_count=len(set(right_by_code) - set(left_by_code)),
        valuation_known=left_known and right_known,
        classification_known=all(
            holding.industry is not None and bool(holding.industry.strip())
            for holding in (*left, *right)
        ),
        rows=rows,
        industry_rows=industry_rows,
        overlap_rows=[PortfolioOverlapSummaryRow("共同持仓权重重合度", overlap)],
    )


def compare_portfolio_data(
    *,
    left_account: PortfolioComparisonAccount,
    right_account: PortfolioComparisonAccount,
    left_report: PerformanceReport,
    right_report: PerformanceReport,
    left_timeline: list[ValuationTimelinePoint],
    right_timeline: list[ValuationTimelinePoint],
    left_holdings: list[PortfolioComparisonHolding],
    right_holdings: list[PortfolioComparisonHolding],
) -> PortfolioComparisonResult:
    """Compare performance, normalized curves, current holdings and industries."""

    if left_account.account_id == right_account.account_id:
        raise ValueError("请选择两个不同的投资组合")
    if left_report.period != right_report.period:
        raise ValueError("两个投资组合必须使用相同的对比区间")

    warnings = [
        *(f"{left_account.account_name}：{warning}" for warning in left_report.warnings),
        *(f"{right_account.account_name}：{warning}" for warning in right_report.warnings),
    ]
    if not left_timeline:
        warnings.append(f"{left_account.account_name}没有所选区间的净值历史")
    if not right_timeline:
        warnings.append(f"{right_account.account_name}没有所选区间的净值历史")
    if any(not point.correction_coverage_known for point in (*left_timeline, *right_timeline)):
        warnings.append("部分净值的费用更正覆盖未知，对应曲线点不予展示")

    holdings = _holding_comparison(left_holdings, right_holdings)
    if not holdings.valuation_known:
        warnings.append("部分当前持仓估值未知，持仓重合度和权重差异保留为未知")
    if not holdings.classification_known:
        warnings.append("部分资产缺少行业分类，已归入“行业未知”")
    relative_twr = _difference(left_report.returns.twr, right_report.returns.twr)
    outcome: Literal["success", "partial"] = "partial" if warnings else "success"
    return PortfolioComparisonResult(
        outcome=outcome,
        left_account=left_account,
        right_account=right_account,
        relative_twr_percentage_points=relative_twr,
        metrics=_metrics(left_report, right_report),
        curve=_curve(left_timeline, right_timeline),
        holdings=holdings,
        warnings=warnings,
    )
