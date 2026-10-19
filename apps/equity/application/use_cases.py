"""
个股分析模块 Application 层用例

遵循四层架构规范：
- Application 层负责用例编排
- 通过依赖注入使用 Infrastructure 层
- 调用 Domain 层的业务逻辑
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from math import isfinite
from typing import TypeAlias, cast

from apps.account.application.config_summary_service import (
    get_account_config_summary_service as get_account_config_summary_service,
)
from apps.equity.application.regime_correlation_use_cases import (
    AnalyzeRegimeCorrelationRequest as AnalyzeRegimeCorrelationRequest,
)
from apps.equity.application.regime_correlation_use_cases import (
    AnalyzeRegimeCorrelationResponse as AnalyzeRegimeCorrelationResponse,
)
from apps.equity.application.regime_correlation_use_cases import (
    AnalyzeRegimeCorrelationUseCase as AnalyzeRegimeCorrelationUseCase,
)
from apps.equity.application.regime_correlation_use_cases import (
    RegimePerformance as RegimePerformance,
)
from apps.equity.application.repository_provider import (
    get_equity_market_data_repository as get_equity_market_data_repository,
)
from apps.equity.application.repository_provider import (
    get_equity_scoring_weight_config_repository,
    get_stock_screening_rule,
)
from apps.equity.application.use_case_protocols import (
    EquityPublicationGate as EquityPublicationGate,
)
from apps.equity.application.use_case_protocols import (
    EquityStockReadRepositoryProtocol as EquityStockReadRepositoryProtocol,
)
from apps.equity.application.use_case_protocols import (
    RegimeHistoryRepositoryProtocol as RegimeHistoryRepositoryProtocol,
)
from apps.equity.application.use_case_protocols import (
    ScoringWeightConfigRepositoryProtocol as ScoringWeightConfigRepositoryProtocol,
)
from apps.equity.application.use_case_runtime import (
    RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS,
)
from apps.equity.application.use_case_runtime import (
    get_runtime_benchmark_code as get_runtime_benchmark_code,
)
from apps.equity.application.use_cases_valuation import (
    AnalyzeValuationRequest as AnalyzeValuationRequest,
)
from apps.equity.application.use_cases_valuation import (
    AnalyzeValuationResponse as AnalyzeValuationResponse,
)
from apps.equity.application.use_cases_valuation import (
    AnalyzeValuationUseCase as AnalyzeValuationUseCase,
)
from apps.equity.application.use_cases_valuation import CalculateDCFRequest as CalculateDCFRequest
from apps.equity.application.use_cases_valuation import CalculateDCFResponse as CalculateDCFResponse
from apps.equity.application.use_cases_valuation import CalculateDCFUseCase as CalculateDCFUseCase
from apps.equity.application.use_cases_valuation import (
    ComprehensiveValuationRequest as ComprehensiveValuationRequest,
)
from apps.equity.application.use_cases_valuation import (
    ComprehensiveValuationResponse as ComprehensiveValuationResponse,
)
from apps.equity.application.use_cases_valuation import (
    ComprehensiveValuationUseCase as ComprehensiveValuationUseCase,
)
from apps.equity.application.use_cases_valuation import ValuationScoreDTO as ValuationScoreDTO
from apps.equity.domain.rules import StockScreeningRule
from apps.equity.domain.services import StockScreener
from apps.equity.domain.services_technical import TechnicalChartService

logger = logging.getLogger(__name__)

EquityPayload: TypeAlias = dict[str, object]


def _custom_float(payload: EquityPayload, key: str, default: float) -> float:
    """Read one finite numeric custom screening value."""

    raw = payload.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if not isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _custom_decimal(payload: EquityPayload, key: str, default: Decimal) -> Decimal:
    """Read one finite non-negative Decimal custom screening value."""

    raw = payload.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{key} must be a finite non-negative value")
    return value


def _custom_count(payload: EquityPayload, key: str, default: int) -> int:
    """Read one bounded custom screening count."""

    raw = payload.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        value = int(str(raw))
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not 1 <= value <= 100:
        raise ValueError(f"{key} must be between 1 and 100")
    return value


def _custom_sectors(payload: EquityPayload) -> list[str] | None:
    """Read an optional string-only sector preference list."""

    raw = payload.get("sector_preference")
    if raw is None:
        return None
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("sector_preference must be an array of strings")
    return [item.strip() for item in raw if item.strip()]


@dataclass
class ScreenStocksRequest:
    """筛选个股请求"""

    regime: str | None = None  # 如果为 None，自动获取最新 Regime
    custom_rule: EquityPayload | None = None  # 自定义规则
    max_count: int | None = None


@dataclass
class ScreenStocksResponse:
    """筛选个股响应"""

    success: bool
    regime: str
    stock_codes: list[str]
    items: list[EquityPayload]
    screening_criteria: EquityPayload
    error: str | None = None


class ScreenStocksUseCase:
    """筛选个股用例"""

    def __init__(
        self,
        stock_repository: EquityStockReadRepositoryProtocol,
        regime_repository: object,
    ) -> None:
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
            regime_repository: Regime 数据仓储
        """
        self.stock_repo = stock_repository
        self.regime_repo = regime_repository

    def execute(self, request: ScreenStocksRequest) -> ScreenStocksResponse:
        """
        执行个股筛选

        流程：
        1. 获取当前 Regime（如果未指定）
        2. 加载对应的筛选规则
        3. 获取全市场股票数据
        4. 应用规则筛选
        5. 返回结果
        """
        try:
            if request.max_count is not None and not 1 <= request.max_count <= 100:
                raise ValueError("max_count must be between 1 and 100")

            # 1. 获取 Regime
            if request.regime:
                regime = request.regime
            else:
                from apps.regime.application.current_regime import resolve_current_regime

                regime = resolve_current_regime(as_of_date=date.today()).dominant_regime

            # 2. 获取筛选规则（从数据库配置加载）
            rule = get_stock_screening_rule(regime)

            if not rule:
                raise ValueError(
                    f"未找到 Regime '{regime}' 的筛选规则，"
                    "请在 Django Admin 中配置或运行 python manage.py init_equity_config"
                )

            if request.custom_rule:
                # 用户自定义规则覆盖
                rule = self._parse_custom_rule(request.custom_rule, regime)

            # 调整 max_count
            if request.max_count is not None and request.max_count != rule.max_count:
                rule = StockScreeningRule(
                    regime=rule.regime,
                    name=rule.name,
                    min_roe=rule.min_roe,
                    min_revenue_growth=rule.min_revenue_growth,
                    min_profit_growth=rule.min_profit_growth,
                    max_debt_ratio=rule.max_debt_ratio,
                    max_pe=rule.max_pe,
                    max_pb=rule.max_pb,
                    min_market_cap=rule.min_market_cap,
                    sector_preference=rule.sector_preference,
                    max_count=request.max_count,
                )

            # 3. 获取全市场数据（最新财务数据 + 最新估值）
            all_stocks = self.stock_repo.get_all_stocks_with_fundamentals()

            if not all_stocks:
                raise ValueError("没有找到股票数据，请先运行数据采集任务")

            # 4. 获取评分权重配置
            config_repo = cast(
                ScoringWeightConfigRepositoryProtocol,
                get_equity_scoring_weight_config_repository(),
            )
            scoring_config = config_repo.get_active_config()

            # 5. 筛选（调用 Domain 服务，传入评分配置）
            screener = StockScreener(scoring_config=scoring_config)
            stock_codes = screener.screen(all_stocks, rule)

            stock_lookup = {
                stock_info.stock_code: (stock_info, financial, valuation)
                for stock_info, financial, valuation in all_stocks
            }
            items: list[EquityPayload] = []
            for rank, stock_code in enumerate(stock_codes, start=1):
                stock_row = stock_lookup.get(stock_code)
                if not stock_row:
                    continue

                stock_info, financial, valuation = stock_row
                items.append(
                    {
                        "rank": rank,
                        "code": stock_info.stock_code,
                        "name": stock_info.name,
                        "sector": stock_info.sector,
                        "market": stock_info.market,
                        "roe": financial.roe,
                        "debt_ratio": financial.debt_ratio,
                        "revenue_growth": financial.revenue_growth,
                        "profit_growth": financial.net_profit_growth,
                        "pe": valuation.pe,
                        "pb": valuation.pb,
                        "ps": valuation.ps,
                        "dividend_yield": valuation.dividend_yield,
                        "score": None,
                        "source": "screen",
                    }
                )

            # 6. 返回结果
            return ScreenStocksResponse(
                success=True,
                regime=regime,
                stock_codes=stock_codes,
                items=items,
                screening_criteria={
                    "rule_name": rule.name,
                    "min_roe": rule.min_roe,
                    "max_pe": rule.max_pe,
                    "max_pb": rule.max_pb,
                    "sectors": rule.sector_preference,
                },
            )

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as e:
            logger.warning("ScreenStocksUseCase.execute failed: %s", e)
            return ScreenStocksResponse(
                success=False,
                regime="",
                stock_codes=[],
                items=[],
                screening_criteria={},
                error=str(e),
            )

    def _parse_custom_rule(
        self,
        custom_rule: EquityPayload,
        regime: str,
    ) -> StockScreeningRule:
        """
        解析自定义规则

        Args:
            custom_rule: 自定义规则字典
            regime: Regime 名称

        Returns:
            StockScreeningRule 对象
        """
        raw_name = custom_rule.get("name")
        if raw_name is not None and not isinstance(raw_name, str):
            raise ValueError("name must be a string")
        return StockScreeningRule(
            regime=regime,
            name=raw_name or "自定义规则",
            min_roe=_custom_float(custom_rule, "min_roe", 0.0),
            min_revenue_growth=_custom_float(custom_rule, "min_revenue_growth", 0.0),
            min_profit_growth=_custom_float(custom_rule, "min_profit_growth", 0.0),
            max_debt_ratio=_custom_float(custom_rule, "max_debt_ratio", 100.0),
            max_pe=_custom_float(custom_rule, "max_pe", 999.0),
            max_pb=_custom_float(custom_rule, "max_pb", 999.0),
            min_market_cap=_custom_decimal(custom_rule, "min_market_cap", Decimal("0")),
            sector_preference=_custom_sectors(custom_rule),
            max_count=_custom_count(custom_rule, "max_count", 50),
        )


@dataclass
class GetTechnicalChartRequest:
    """技术图表请求。"""

    stock_code: str
    timeframe: str = "day"
    lookback_days: int = 365
    mode: str = "published"
    publication_key: str = "current"


@dataclass
class GetTechnicalChartResponse:
    """技术图表响应。"""

    success: bool
    stock_code: str
    stock_name: str
    timeframe: str
    candles: list[EquityPayload]
    signals: list[EquityPayload]
    latest_signal: EquityPayload | None
    error: str | None = None
    observed_at: str | None = None
    freshness_status: str = "unverified"
    must_not_use_for_decision: bool = True
    blocked_reason: str | None = None
    mode: str = "published"
    publication_key: str = "current"


@dataclass
class GetIntradayChartRequest:
    """分时图请求。"""

    stock_code: str


@dataclass
class GetIntradayChartResponse:
    """分时图响应。"""

    success: bool
    stock_code: str
    stock_name: str
    points: list[EquityPayload]
    latest_point: EquityPayload | None
    session_date: str | None
    source: str | None
    error: str | None = None
    observed_at: str | None = None
    freshness_status: str = "unverified"
    must_not_use_for_decision: bool = True
    blocked_reason: str | None = None


class GetTechnicalChartUseCase:
    """个股技术图表用例。"""

    def __init__(self, stock_repository: EquityStockReadRepositoryProtocol) -> None:
        self.stock_repo = stock_repository
        self.chart_service = TechnicalChartService()

    def execute(self, request: GetTechnicalChartRequest) -> GetTechnicalChartResponse:
        """获取技术图表数据。"""
        try:
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            end_date = date.today()
            lookback_days = self._resolve_technical_lookback_days(
                request.timeframe, request.lookback_days
            )
            start_date = end_date - timedelta(days=lookback_days)
            bars = self.stock_repo.get_technical_bars(
                request.stock_code,
                start_date=start_date,
                end_date=end_date,
                hydrate=request.mode != "published",
                published_only=request.mode == "published",
                publication_key=request.publication_key,
            )
            if not bars:
                if request.mode == "published":
                    raise ValueError(f"未找到股票 {request.stock_code} 的已发布日线技术数据")
                raise ValueError(f"未找到股票 {request.stock_code} 的日线技术数据")

            aggregated_bars = self.chart_service.aggregate_bars(bars, request.timeframe)
            signals = self.chart_service.detect_crossovers(aggregated_bars)
            latest_trade_date = max(bar.trade_date for bar in aggregated_bars)
            age_days = max((date.today() - latest_trade_date).days, 0)
            freshness_status = "fresh" if age_days <= 5 else "stale"
            must_not_use_for_decision = freshness_status != "fresh"
            blocked_reason = "technical_observation_stale" if must_not_use_for_decision else None

            candle_payload: list[EquityPayload] = [
                {
                    "trade_date": bar.trade_date.isoformat(),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": bar.volume,
                    "amount": float(bar.amount),
                    "ma5": float(bar.ma5) if bar.ma5 is not None else None,
                    "ma20": float(bar.ma20) if bar.ma20 is not None else None,
                    "ma60": float(bar.ma60) if bar.ma60 is not None else None,
                    "macd": bar.macd,
                    "macd_signal": bar.macd_signal,
                    "macd_hist": bar.macd_hist,
                    "rsi": bar.rsi,
                }
                for bar in aggregated_bars
            ]
            signal_payload: list[EquityPayload] = [
                {
                    "signal_type": signal.signal_type,
                    "trade_date": signal.trade_date.isoformat(),
                    "price": float(signal.price),
                    "short_value": float(signal.short_value),
                    "long_value": float(signal.long_value),
                    "label": signal.label,
                }
                for signal in signals[-8:]
            ]

            return GetTechnicalChartResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                timeframe=request.timeframe,
                candles=candle_payload,
                signals=signal_payload,
                latest_signal=signal_payload[-1] if signal_payload else None,
                observed_at=latest_trade_date.isoformat(),
                freshness_status=freshness_status,
                must_not_use_for_decision=must_not_use_for_decision,
                blocked_reason=blocked_reason,
                mode=request.mode,
                publication_key=request.publication_key,
            )
        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as exc:
            logger.warning("GetTechnicalChartUseCase.execute failed: %s", exc)
            return GetTechnicalChartResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                timeframe=request.timeframe,
                candles=[],
                signals=[],
                latest_signal=None,
                error=str(exc),
                freshness_status="unverified",
                must_not_use_for_decision=True,
                blocked_reason=(
                    "technical_publication_unavailable"
                    if request.mode == "published"
                    else "technical_observation_unavailable"
                ),
                mode=request.mode,
                publication_key=request.publication_key,
            )

    @staticmethod
    def _resolve_technical_lookback_days(timeframe: str, requested_days: int) -> int:
        """Use a period-aware minimum window so weekly/monthly charts are meaningful."""
        minimum_by_timeframe = {
            "week": 1260,
            "month": 2000,
        }
        return max(requested_days, minimum_by_timeframe.get(timeframe, requested_days))


class GetIntradayChartUseCase:
    """个股分时图用例。"""

    def __init__(self, stock_repository: EquityStockReadRepositoryProtocol) -> None:
        self.stock_repo = stock_repository

    def execute(self, request: GetIntradayChartRequest) -> GetIntradayChartResponse:
        """获取分时图数据。"""
        stock_name = ""
        try:
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")
            stock_name = stock_info.name

            points = self.stock_repo.get_intraday_points(request.stock_code)
            if not points:
                raise ValueError(f"未找到股票 {request.stock_code} 的分时数据")

            payload: list[EquityPayload] = [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "price": float(point.price),
                    "avg_price": float(point.avg_price) if point.avg_price is not None else None,
                    "volume": point.volume,
                }
                for point in points
            ]
            observed_at = points[-1].timestamp
            blocked_reason: str | None
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                freshness_status = "unverified"
                must_not_use_for_decision = True
                blocked_reason = "intraday_observation_naive"
            else:
                age_days = max(
                    (datetime.now(UTC) - observed_at.astimezone(UTC)).total_seconds() / 86400,
                    0.0,
                )
                freshness_status = "fresh" if age_days <= 5 else "stale"
                must_not_use_for_decision = freshness_status != "fresh"
                blocked_reason = "intraday_observation_stale" if must_not_use_for_decision else None

            return GetIntradayChartResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_name,
                points=payload,
                latest_point=payload[-1] if payload else None,
                session_date=points[-1].timestamp.date().isoformat() if points else None,
                source=self.stock_repo.get_last_intraday_source() or "akshare",
                observed_at=observed_at.isoformat(),
                freshness_status=freshness_status,
                must_not_use_for_decision=must_not_use_for_decision,
                blocked_reason=blocked_reason,
            )
        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as exc:
            logger.warning("GetIntradayChartUseCase.execute failed: %s", exc)
            return GetIntradayChartResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name=stock_name,
                points=[],
                latest_point=None,
                session_date=None,
                source=None,
                error=str(exc),
            )
