"""
Pure Python Domain Entity Factories

No Django/pandas/numpy dependencies - safe for Domain layer testing.
All factory functions return frozen dataclass instances with sensible defaults.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# Hedge Module Factories
# ============================================================
from apps.hedge.domain.entities import (
    CorrelationMetric,
    HedgeAlert,
    HedgeAlertType,
    HedgeMethod,
    HedgePair,
    HedgePerformance,
    HedgePortfolio,
)


def make_hedge_pair(
    name: str = "测试对冲",
    long_asset: str = "510300",
    hedge_asset: str = "511260",
    hedge_method: HedgeMethod = HedgeMethod.BETA,
    target_long_weight: float = 0.7,
    target_hedge_weight: float = 0.3,
    **kwargs: Any,
) -> HedgePair:
    return HedgePair(
        name=name,
        long_asset=long_asset,
        hedge_asset=hedge_asset,
        hedge_method=hedge_method,
        target_long_weight=target_long_weight,
        target_hedge_weight=target_hedge_weight,
        **kwargs,
    )


def make_correlation_metric(
    asset1: str = "510300",
    asset2: str = "511260",
    calc_date: date | None = None,
    window_days: int = 60,
    correlation: float = -0.5,
    **kwargs: Any,
) -> CorrelationMetric:
    return CorrelationMetric(
        asset1=asset1,
        asset2=asset2,
        calc_date=calc_date or date(2025, 1, 15),
        window_days=window_days,
        correlation=correlation,
        **kwargs,
    )


def make_hedge_portfolio(
    pair_name: str = "测试对冲",
    trade_date: date | None = None,
    long_weight: float = 0.7,
    hedge_weight: float = 0.3,
    hedge_ratio: float = 0.43,
    **kwargs: Any,
) -> HedgePortfolio:
    return HedgePortfolio(
        pair_name=pair_name,
        trade_date=trade_date or date(2025, 1, 15),
        long_weight=long_weight,
        hedge_weight=hedge_weight,
        hedge_ratio=hedge_ratio,
        **kwargs,
    )


def make_hedge_alert(
    pair_name: str = "测试对冲",
    alert_date: date | None = None,
    alert_type: HedgeAlertType = HedgeAlertType.CORRELATION_BREAKDOWN,
    message: str = "Correlation breakdown detected",
    **kwargs: Any,
) -> HedgeAlert:
    return HedgeAlert(
        pair_name=pair_name,
        alert_date=alert_date or date(2025, 1, 15),
        alert_type=alert_type,
        message=message,
        **kwargs,
    )


def make_hedge_performance(
    pair_name: str = "测试对冲",
    period_start: date | None = None,
    period_end: date | None = None,
    total_return: float = 0.08,
    annual_return: float = 0.10,
    sharpe_ratio: float = 1.2,
    volatility_reduction: float = 0.35,
    drawdown_reduction: float = 0.25,
    hedge_effectiveness: float = 0.72,
    hedge_cost: float = 0.02,
    cost_benefit_ratio: float = 4.0,
    avg_correlation: float = -0.55,
    correlation_stability: float = 0.8,
) -> HedgePerformance:
    return HedgePerformance(
        pair_name=pair_name,
        period_start=period_start or date(2024, 1, 1),
        period_end=period_end or date(2024, 12, 31),
        total_return=total_return,
        annual_return=annual_return,
        sharpe_ratio=sharpe_ratio,
        volatility_reduction=volatility_reduction,
        drawdown_reduction=drawdown_reduction,
        hedge_effectiveness=hedge_effectiveness,
        hedge_cost=hedge_cost,
        cost_benefit_ratio=cost_benefit_ratio,
        avg_correlation=avg_correlation,
        correlation_stability=correlation_stability,
    )


# ============================================================
# Fund Module Factories
# ============================================================

from apps.fund.domain.entities import (
    FundHolding,
    FundInfo,
    FundManager,
    FundNetValue,
    FundPerformance,
    FundScore,
    FundSectorAllocation,
)


def make_fund_info(
    fund_code: str = "110011",
    fund_name: str = "测试基金A",
    fund_type: str = "混合型",
    **kwargs: Any,
) -> FundInfo:
    return FundInfo(
        fund_code=fund_code,
        fund_name=fund_name,
        fund_type=fund_type,
        **kwargs,
    )


def make_fund_net_value(
    fund_code: str = "110011",
    nav_date: date | None = None,
    unit_nav: Decimal = Decimal("1.5000"),
    accum_nav: Decimal = Decimal("2.3000"),
    daily_return: float | None = None,
) -> FundNetValue:
    return FundNetValue(
        fund_code=fund_code,
        nav_date=nav_date or date(2025, 1, 15),
        unit_nav=unit_nav,
        accum_nav=accum_nav,
        daily_return=daily_return,
    )


def make_fund_performance(
    fund_code: str = "110011",
    start_date: date | None = None,
    end_date: date | None = None,
    total_return: float = 0.15,
    **kwargs: Any,
) -> FundPerformance:
    return FundPerformance(
        fund_code=fund_code,
        start_date=start_date or date(2024, 1, 1),
        end_date=end_date or date(2024, 12, 31),
        total_return=total_return,
        **kwargs,
    )


def make_fund_holding(
    fund_code: str = "110011",
    report_date: date | None = None,
    stock_code: str = "000001",
    stock_name: str = "平安银行",
    **kwargs: Any,
) -> FundHolding:
    return FundHolding(
        fund_code=fund_code,
        report_date=report_date or date(2024, 12, 31),
        stock_code=stock_code,
        stock_name=stock_name,
        **kwargs,
    )


def make_fund_sector_allocation(
    fund_code: str = "110011",
    report_date: date | None = None,
    sector_name: str = "金融",
    allocation_ratio: float = 0.25,
) -> FundSectorAllocation:
    return FundSectorAllocation(
        fund_code=fund_code,
        report_date=report_date or date(2024, 12, 31),
        sector_name=sector_name,
        allocation_ratio=allocation_ratio,
    )


def make_fund_score(
    fund_code: str = "110011",
    fund_name: str = "测试基金A",
    score_date: date | None = None,
    performance_score: float = 80.0,
    regime_fit_score: float = 75.0,
    risk_score: float = 70.0,
    scale_score: float = 60.0,
    total_score: float = 75.0,
    rank: int = 1,
) -> FundScore:
    return FundScore(
        fund_code=fund_code,
        fund_name=fund_name,
        score_date=score_date or date(2025, 1, 15),
        performance_score=performance_score,
        regime_fit_score=regime_fit_score,
        risk_score=risk_score,
        scale_score=scale_score,
        total_score=total_score,
        rank=rank,
    )


# ============================================================
# Factor Module Factories
# ============================================================

from apps.factor.domain.entities import (
    FactorCategory,
    FactorDefinition,
    FactorDirection,
    FactorExposure,
    FactorPortfolioConfig,
    FactorPortfolioHolding,
    FactorScore,
)


def make_factor_definition(
    code: str = "pe_ttm",
    name: str = "市盈率TTM",
    category: FactorCategory = FactorCategory.VALUE,
    description: str = "滚动市盈率",
    data_source: str = "tushare",
    data_field: str = "pe_ttm",
    **kwargs: Any,
) -> FactorDefinition:
    return FactorDefinition(
        code=code,
        name=name,
        category=category,
        description=description,
        data_source=data_source,
        data_field=data_field,
        **kwargs,
    )


def make_factor_exposure(
    stock_code: str = "000001",
    trade_date: date | None = None,
    factor_code: str = "pe_ttm",
    factor_value: float = 0.8,
    percentile_rank: float = 0.75,
    z_score: float = 0.67,
    **kwargs: Any,
) -> FactorExposure:
    return FactorExposure(
        stock_code=stock_code,
        trade_date=trade_date or date(2025, 1, 15),
        factor_code=factor_code,
        factor_value=factor_value,
        percentile_rank=percentile_rank,
        z_score=z_score,
        **kwargs,
    )


def make_factor_score(
    stock_code: str = "000001",
    stock_name: str = "平安银行",
    trade_date: date | None = None,
    factor_scores: dict[str, float] | None = None,
    factor_weights: dict[str, float] | None = None,
    composite_score: float = 0.75,
    percentile_rank: float = 0.80,
    **kwargs: Any,
) -> FactorScore:
    return FactorScore(
        stock_code=stock_code,
        stock_name=stock_name,
        trade_date=trade_date or date(2025, 1, 15),
        factor_scores=factor_scores or {"pe_ttm": 0.8, "roe": 0.7},
        factor_weights=factor_weights or {"pe_ttm": 0.5, "roe": 0.5},
        composite_score=composite_score,
        percentile_rank=percentile_rank,
        **kwargs,
    )


def make_factor_portfolio_config(
    name: str = "价值组合",
    factor_weights: dict[str, float] | None = None,
    **kwargs: Any,
) -> FactorPortfolioConfig:
    return FactorPortfolioConfig(
        name=name,
        factor_weights=factor_weights or {"pe_ttm": 0.4, "pb": 0.3, "roe": 0.3},
        **kwargs,
    )


# ============================================================
# Rotation Module Factories
# ============================================================

from apps.rotation.domain.entities import (
    AssetCategory,
    AssetClass,
    MomentumScore,
    RotationConfig,
    RotationPortfolio,
    RotationSignal,
    RotationStrategyType,
)


def make_asset_class(
    code: str = "510300",
    name: str = "沪深300ETF",
    category: AssetCategory = AssetCategory.EQUITY,
    description: str = "沪深300指数基金",
    **kwargs: Any,
) -> AssetClass:
    return AssetClass(
        code=code,
        name=name,
        category=category,
        description=description,
        **kwargs,
    )


def make_momentum_score(
    asset_code: str = "510300",
    calc_date: date | None = None,
    **kwargs: Any,
) -> MomentumScore:
    return MomentumScore(
        asset_code=asset_code,
        calc_date=calc_date or date(2025, 1, 15),
        **kwargs,
    )


def make_rotation_config(
    name: str = "动量轮动",
    strategy_type: RotationStrategyType = RotationStrategyType.MOMENTUM,
    asset_universe: list[str] | None = None,
    params: dict | None = None,
    regime_allocations: dict | None = None,
    momentum_periods: list[int] | None = None,
    **kwargs: Any,
) -> RotationConfig:
    return RotationConfig(
        name=name,
        strategy_type=strategy_type,
        asset_universe=asset_universe or ["510300", "511260", "159980"],
        params=params or {},
        regime_allocations=regime_allocations or {
            "growth_inflation": {"510300": 0.6, "511260": 0.2, "159980": 0.2},
            "growth_deflation": {"510300": 0.4, "511260": 0.4, "159980": 0.2},
        },
        momentum_periods=momentum_periods or [20, 60, 120],
        **kwargs,
    )


def make_rotation_signal(
    config_name: str = "动量轮动",
    signal_date: date | None = None,
    target_allocation: dict[str, float] | None = None,
    **kwargs: Any,
) -> RotationSignal:
    return RotationSignal(
        config_name=config_name,
        signal_date=signal_date or date(2025, 1, 15),
        target_allocation=target_allocation or {"510300": 0.5, "511260": 0.3, "159980": 0.2},
        **kwargs,
    )


# ============================================================
# Dashboard Module Factories
# ============================================================

from apps.dashboard.domain.entities import (
    AlertConfig,
    AlertSeverity,
    CardType,
    ChartConfig,
    ChartDataType,
    DashboardCard,
    DashboardLayout,
    DashboardPreferences,
    DashboardWidget,
    MetricCard,
    WidgetType,
)


def make_metric_card(
    title: str = "总收益率",
    value: float = 12.5,
    **kwargs: Any,
) -> MetricCard:
    return MetricCard(title=title, value=value, **kwargs)


def make_dashboard_widget(
    widget_id: str = "widget-1",
    widget_type: WidgetType = WidgetType.STAT_CARD,
    **kwargs: Any,
) -> DashboardWidget:
    return DashboardWidget(
        widget_id=widget_id,
        widget_type=widget_type,
        **kwargs,
    )


def make_dashboard_card(
    card_id: str = "card-1",
    card_type: CardType = CardType.METRIC,
    widgets: list[DashboardWidget] | None = None,
    **kwargs: Any,
) -> DashboardCard:
    return DashboardCard(
        card_id=card_id,
        card_type=card_type,
        widgets=widgets or [make_dashboard_widget()],
        **kwargs,
    )


def make_dashboard_layout(
    layout_id: str = "default",
    name: str = "默认布局",
    cards: list[DashboardCard] | None = None,
    **kwargs: Any,
) -> DashboardLayout:
    return DashboardLayout(
        layout_id=layout_id,
        name=name,
        cards=cards or [make_dashboard_card()],
        **kwargs,
    )


def make_alert_config(
    alert_id: str = "alert-1",
    name: str = "收益率告警",
    severity: AlertSeverity = AlertSeverity.WARNING,
    threshold: float = 5.0,
    **kwargs: Any,
) -> AlertConfig:
    return AlertConfig(
        alert_id=alert_id,
        name=name,
        severity=severity,
        threshold=threshold,
        **kwargs,
    )


def make_dashboard_preferences(
    user_id: int = 1,
    layout_id: str = "default",
    **kwargs: Any,
) -> DashboardPreferences:
    return DashboardPreferences(
        user_id=user_id,
        layout_id=layout_id,
        **kwargs,
    )


# ============================================================
# Sector Module Factories
# ============================================================

from apps.sector.domain.entities import (
    SectorIndex,
    SectorInfo,
    SectorRelativeStrength,
    SectorScore,
)


def make_sector_info(
    sector_code: str = "801010",
    sector_name: str = "农林牧渔",
    level: str = "L1",
    **kwargs: Any,
) -> SectorInfo:
    return SectorInfo(
        sector_code=sector_code,
        sector_name=sector_name,
        level=level,
        **kwargs,
    )


def make_sector_index(
    sector_code: str = "801010",
    trade_date: date | None = None,
    open_price: Decimal = Decimal("1000.00"),
    high: Decimal = Decimal("1020.00"),
    low: Decimal = Decimal("990.00"),
    close: Decimal = Decimal("1010.00"),
    volume: int = 100000,
    amount: Decimal = Decimal("10000000.00"),
    change_pct: float = 1.0,
    **kwargs: Any,
) -> SectorIndex:
    return SectorIndex(
        sector_code=sector_code,
        trade_date=trade_date or date(2025, 1, 15),
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
        change_pct=change_pct,
        **kwargs,
    )


def make_sector_relative_strength(
    sector_code: str = "801010",
    trade_date: date | None = None,
    relative_strength: float = 1.05,
    momentum: float = 0.03,
    **kwargs: Any,
) -> SectorRelativeStrength:
    return SectorRelativeStrength(
        sector_code=sector_code,
        trade_date=trade_date or date(2025, 1, 15),
        relative_strength=relative_strength,
        momentum=momentum,
        **kwargs,
    )


# ============================================================
# Equity Module Factories
# ============================================================

from apps.equity.domain.entities import (
    FinancialData,
    ScoringWeightConfig,
    StockInfo,
    TechnicalIndicators,
    ValuationMetrics,
)


def make_stock_info(
    stock_code: str = "000001",
    name: str = "平安银行",
    sector: str = "金融",
    market: str = "主板",
    list_date: date | None = None,
) -> StockInfo:
    return StockInfo(
        stock_code=stock_code,
        name=name,
        sector=sector,
        market=market,
        list_date=list_date or date(1991, 4, 3),
    )


def make_financial_data(
    stock_code: str = "000001",
    report_date: date | None = None,
    revenue: Decimal = Decimal("100000000000"),
    net_profit: Decimal = Decimal("15000000000"),
    revenue_growth: float = 0.08,
    net_profit_growth: float = 0.12,
    total_assets: Decimal = Decimal("5000000000000"),
    total_liabilities: Decimal = Decimal("4500000000000"),
    equity: Decimal = Decimal("500000000000"),
    roe: float = 0.12,
    roa: float = 0.01,
    debt_ratio: float = 0.9,
) -> FinancialData:
    return FinancialData(
        stock_code=stock_code,
        report_date=report_date or date(2024, 12, 31),
        revenue=revenue,
        net_profit=net_profit,
        revenue_growth=revenue_growth,
        net_profit_growth=net_profit_growth,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        equity=equity,
        roe=roe,
        roa=roa,
        debt_ratio=debt_ratio,
    )


def make_valuation_metrics(
    stock_code: str = "000001",
    trade_date: date | None = None,
    pe: float = 8.5,
    pb: float = 0.9,
    ps: float = 1.2,
    total_mv: Decimal = Decimal("300000000000"),
    circ_mv: Decimal = Decimal("280000000000"),
    dividend_yield: float = 4.5,
) -> ValuationMetrics:
    return ValuationMetrics(
        stock_code=stock_code,
        trade_date=trade_date or date(2025, 1, 15),
        pe=pe,
        pb=pb,
        ps=ps,
        total_mv=total_mv,
        circ_mv=circ_mv,
        dividend_yield=dividend_yield,
    )


# ============================================================
# Events Module Factories
# ============================================================

from apps.events.domain.entities import (
    DomainEvent,
    EventBusConfig,
    EventMetrics,
    EventSubscription,
    EventType,
)


def make_domain_event(
    event_id: str | None = None,
    event_type: EventType = EventType.REGIME_CHANGED,
    occurred_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> DomainEvent:
    return DomainEvent(
        event_id=event_id or "evt-test-001",
        event_type=event_type,
        occurred_at=occurred_at or datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
        payload=payload or {"regime": "growth_inflation"},
        metadata=metadata or {},
        **kwargs,
    )


def make_event_bus_config(**kwargs: Any) -> EventBusConfig:
    return EventBusConfig(**kwargs)


# ============================================================
# Utility: Price Series Generator
# ============================================================


def make_price_series(
    base_price: float = 100.0,
    days: int = 120,
    daily_return_mean: float = 0.0005,
    daily_return_std: float = 0.015,
) -> list[float]:
    """Generate a deterministic price series for testing."""
    import math

    prices = [base_price]
    # Use a simple sine-based pattern for deterministic behavior
    for i in range(1, days):
        change = daily_return_mean + daily_return_std * math.sin(i * 0.5)
        prices.append(prices[-1] * (1 + change))
    return prices


def make_get_asset_prices(
    price_data: dict[str, list[float]] | None = None,
) -> Callable[[str, date, int], list[float] | None]:
    """Create a mock get_asset_prices callable for service contexts."""
    data = price_data or {}

    def _get_prices(asset_code: str, calc_date: date, window: int) -> list[float] | None:
        if asset_code in data:
            series = data[asset_code]
            return series[-window:] if len(series) >= window else series
        # Generate default prices
        return make_price_series(base_price=100.0, days=window)

    return _get_prices


def make_get_asset_name() -> Callable[[str], str | None]:
    """Create a mock get_asset_name callable."""
    names = {
        "510300": "沪深300ETF",
        "511260": "10年国债ETF",
        "159980": "黄金ETF",
        "000001": "平安银行",
    }

    def _get_name(code: str) -> str | None:
        return names.get(code, f"资产{code}")

    return _get_name
