"""Equity valuation analysis use cases, including published snapshot reads."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, TypeAlias

from apps.equity.application.use_case_protocols import (
    EquityPublicationGate,
    EquityStockReadRepositoryProtocol,
)
from apps.equity.application.use_case_runtime import (
    RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS,
)

logger = logging.getLogger("apps.equity.application.use_cases")
EquityPayload: TypeAlias = dict[str, object]
_PUBLISHED_EQUITY_DATASET_KEYS = (
    "equity.financial.fact",
    "equity.price.bar",
    "equity.valuation.fact",
)


@dataclass
class AnalyzeValuationRequest:
    """估值分析请求"""

    stock_code: str
    lookback_days: int = 252  # 回看天数（默认 1 年）
    mode: str = "published"
    publication_key: str = "current"


@dataclass
class AnalyzeValuationResponse:
    """估值分析响应（个股详情页完整数据）"""

    success: bool
    stock_code: str
    stock_name: str
    # 基本信息
    sector: str
    market: str
    list_date: str | None
    # 估值数据
    current_pe: float | None
    pe_percentile: float | None
    current_pb: float | None
    pb_percentile: float | None
    is_undervalued: bool | None
    # 最新估值详情
    latest_valuation: EquityPayload | None = None
    # 财务数据
    financial_data: EquityPayload | None = None
    error: str | None = None
    status: Literal["success", "blocked", "failed"] = "success"
    mode: Literal["historical", "published"] | None = None
    publication_key: str | None = None
    publication_id: str | None = None
    publication: dict[str, object] | None = None
    publication_gates: dict[str, EquityPublicationGate | None] | None = None
    must_not_use_for_decision: bool | None = None


class AnalyzeValuationUseCase:
    """估值分析用例"""

    def __init__(self, stock_repository: EquityStockReadRepositoryProtocol) -> None:
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
        """
        self.stock_repo = stock_repository

    def execute(self, request: AnalyzeValuationRequest) -> AnalyzeValuationResponse:
        """
        执行估值分析

        流程：
        1. 获取股票基本信息
        2. 获取历史估值数据
        3. 计算 PE/PB 百分位
        4. 判断是否低估
        5. 获取财务数据
        6. 返回完整结果
        """
        publication_gates: dict[str, EquityPublicationGate | None] | None = None
        try:
            from datetime import timedelta

            from apps.equity.domain.services import ValuationAnalyzer

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 读取同一已发布快照或历史数据
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)
            if request.mode == "published":
                published_inputs = self.stock_repo.get_published_valuation_inputs(
                    stock_info.stock_code,
                    start_date,
                    end_date,
                    publication_key=request.publication_key,
                    valuation_limit=5000,
                )
                available_gates = dict(published_inputs.publication_gates)
                publication_gates = {
                    dataset_key: available_gates.get(dataset_key)
                    for dataset_key in _PUBLISHED_EQUITY_DATASET_KEYS
                }
                blocking_gates: list[EquityPublicationGate | None] = []
                for dataset_key in _PUBLISHED_EQUITY_DATASET_KEYS:
                    gate = publication_gates[dataset_key]
                    if gate is None or gate.must_not_use_for_decision:
                        blocking_gates.append(gate)
                if blocking_gates:
                    blocking_gate = blocking_gates[0]
                    blocked_reason = (
                        "canonical_publication_missing"
                        if blocking_gate is None
                        else blocking_gate.blocked_reason or "publication_member_snapshot_invalid"
                    )
                    return AnalyzeValuationResponse(
                        success=False,
                        stock_code=request.stock_code,
                        stock_name=stock_info.name,
                        sector=stock_info.sector or "",
                        market=stock_info.market or "",
                        list_date=(
                            stock_info.list_date.isoformat() if stock_info.list_date else None
                        ),
                        current_pe=None,
                        pe_percentile=None,
                        current_pb=None,
                        pb_percentile=None,
                        is_undervalued=None,
                        latest_valuation=None,
                        financial_data=None,
                        error=blocked_reason,
                        status="blocked",
                        publication_gates=publication_gates,
                    )

                valuation_history = list(published_inputs.valuation_history)
                financial = published_inputs.latest_financial
                daily_prices = list(published_inputs.daily_prices)
                if not valuation_history:
                    return AnalyzeValuationResponse(
                        success=False,
                        stock_code=request.stock_code,
                        stock_name=stock_info.name,
                        sector=stock_info.sector or "",
                        market=stock_info.market or "",
                        list_date=(
                            stock_info.list_date.isoformat() if stock_info.list_date else None
                        ),
                        current_pe=None,
                        pe_percentile=None,
                        current_pb=None,
                        pb_percentile=None,
                        is_undervalued=None,
                        latest_valuation=None,
                        financial_data=None,
                        error="published_valuation_history_unavailable",
                        status="blocked",
                        publication_gates=publication_gates,
                    )
            else:
                valuation_history = self.stock_repo.get_valuation_history(
                    request.stock_code,
                    start_date,
                    end_date,
                    hydrate=False,
                    published_only=False,
                    publication_key=request.publication_key,
                )

                # 5. 获取财务数据
                financial = self.stock_repo.get_latest_financial_data(
                    request.stock_code,
                    hydrate=False,
                    published_only=False,
                    publication_key=request.publication_key,
                )

                # 6. 获取日线数据（用于获取当前价格、换手率等）
                daily_prices = self.stock_repo.get_daily_prices(
                    request.stock_code,
                    start_date=end_date - timedelta(days=7),
                    end_date=end_date,
                    hydrate=False,
                    published_only=False,
                    publication_key=request.publication_key,
                )
            latest_daily = daily_prices[-1] if daily_prices else None

            latest = None
            pe_percentile = 0.0
            pb_percentile = 0.0
            is_undervalued = False
            latest_valuation: EquityPayload | None = None
            response_error = None

            if valuation_history:
                latest = valuation_history[-1]

                # 3. 计算百分位
                analyzer = ValuationAnalyzer()
                pe_history = [v.pe for v in valuation_history if v.pe is not None and v.pe > 0]
                pb_history = [v.pb for v in valuation_history if v.pb is not None and v.pb > 0]

                if latest.pe is None or latest.pb is None:
                    response_error = f"股票 {request.stock_code} 的 PE/PB 数据不完整"
                    latest_valuation = {
                        "pe": latest.pe,
                        "pb": latest.pb,
                        "ps": latest.ps,
                        "pe_percentile": 0.0,
                        "pb_percentile": 0.0,
                        "total_mv": float(latest.total_mv) if latest.total_mv is not None else None,
                        "circ_mv": float(latest.circ_mv) if latest.circ_mv is not None else None,
                        "dividend_yield": latest.dividend_yield,
                        "price": float(latest_daily[1]) if latest_daily else None,
                        "trade_date": latest.trade_date.isoformat(),
                        "updated_at": latest.fetched_at.isoformat() if latest.fetched_at else None,
                        "source_updated_at": (
                            latest.source_updated_at.isoformat()
                            if latest.source_updated_at
                            else None
                        ),
                    }
                    latest = None
                else:
                    pe_percentile = analyzer.calculate_pe_percentile(latest.pe, pe_history)
                    pb_percentile = analyzer.calculate_pb_percentile(latest.pb, pb_history)

                    # 4. 判断是否低估
                    is_undervalued = analyzer.is_undervalued(pe_percentile, pb_percentile)

                    # 7. 构建最新估值详情字典
                    latest_valuation = {
                        "pe": latest.pe if latest.pe > 0 else None,
                        "pb": latest.pb if latest.pb > 0 else None,
                        "ps": latest.ps if latest.ps is not None and latest.ps > 0 else None,
                        "pe_percentile": pe_percentile,
                        "pb_percentile": pb_percentile,
                        "total_mv": float(latest.total_mv) if latest.total_mv is not None else None,
                        "circ_mv": float(latest.circ_mv) if latest.circ_mv is not None else None,
                        "dividend_yield": (
                            latest.dividend_yield
                            if latest.dividend_yield is not None and latest.dividend_yield > 0
                            else None
                        ),
                        "price": float(latest_daily[1]) if latest_daily else None,
                        "trade_date": latest.trade_date.isoformat(),
                        "updated_at": latest.fetched_at.isoformat() if latest.fetched_at else None,
                        "source_updated_at": (
                            latest.source_updated_at.isoformat()
                            if latest.source_updated_at
                            else None
                        ),
                    }
            else:
                response_error = f"未找到股票 {request.stock_code} 的估值数据"
                latest_valuation = {
                    "pe": None,
                    "pb": None,
                    "ps": None,
                    "pe_percentile": 0.0,
                    "pb_percentile": 0.0,
                    "total_mv": None,
                    "circ_mv": None,
                    "dividend_yield": None,
                    "price": float(latest_daily[1]) if latest_daily else None,
                    "trade_date": latest_daily[0].isoformat() if latest_daily else None,
                    "updated_at": None,
                    "source_updated_at": None,
                }

            # 8. 构建财务数据字典
            financial_data: EquityPayload | None = None
            if financial:
                financial_data = {
                    "roe": financial.roe,
                    "roa": financial.roa,
                    "revenue": float(financial.revenue) if financial.revenue else None,
                    "net_profit": float(financial.net_profit) if financial.net_profit else None,
                    "revenue_growth": financial.revenue_growth,
                    "net_profit_growth": financial.net_profit_growth,
                    "debt_ratio": financial.debt_ratio,
                    "gross_margin": None,  # 需要从其他地方获取
                    "period_end": (
                        financial.period_end.isoformat() if financial.period_end else None
                    ),
                    "period_type": financial.period_type or None,
                    "report_date": (
                        financial.report_date.isoformat() if financial.report_date else None
                    ),
                    "source": financial.source or None,
                    "fetched_at": (
                        financial.fetched_at.isoformat() if financial.fetched_at else None
                    ),
                }

            # 9. 返回结果
            return AnalyzeValuationResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                sector=stock_info.sector or "",
                market=stock_info.market or "",
                list_date=stock_info.list_date.isoformat() if stock_info.list_date else None,
                current_pe=latest.pe if latest is not None else None,
                pe_percentile=pe_percentile,
                current_pb=latest.pb if latest is not None else None,
                pb_percentile=pb_percentile,
                is_undervalued=is_undervalued,
                latest_valuation=latest_valuation,
                financial_data=financial_data,
                error=response_error,
                status="success",
                publication_gates=publication_gates,
            )

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as e:
            logger.warning("AnalyzeValuationUseCase.execute failed: %s", e)
            return AnalyzeValuationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                sector="",
                market="",
                list_date=None,
                current_pe=None,
                pe_percentile=None if request.mode == "published" else 0.0,
                current_pb=None,
                pb_percentile=None if request.mode == "published" else 0.0,
                is_undervalued=None if request.mode == "published" else False,
                latest_valuation=None,
                financial_data=None,
                error=str(e),
                status="failed",
                publication_gates=publication_gates,
            )


# ============================================================================
# DCF 绝对估值
# ============================================================================


@dataclass
class CalculateDCFRequest:
    """DCF 估值请求"""

    stock_code: str
    growth_rate: float = 0.1  # 未来增长率（默认 10%）
    discount_rate: float = 0.1  # 折现率（默认 10%）
    terminal_growth: float = 0.03  # 永续增长率（默认 3%）
    projection_years: int = 5  # 预测年数（默认 5 年）
    mode: str = "published"
    publication_key: str = "current"


@dataclass
class CalculateDCFResponse:
    """DCF 估值响应"""

    success: bool
    stock_code: str
    stock_name: str
    intrinsic_value: Decimal  # 内在价值（企业总价值）
    intrinsic_value_per_share: Decimal | None  # 每股内在价值
    current_price: Decimal | None  # 当前股价
    upside: float | None  # 上涨空间（百分比）
    error: str | None = None


class CalculateDCFUseCase:
    """DCF 绝对估值用例"""

    def __init__(self, stock_repository: EquityStockReadRepositoryProtocol) -> None:
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
        """
        self.stock_repo = stock_repository

    def execute(self, request: CalculateDCFRequest) -> CalculateDCFResponse:
        """
        执行 DCF 估值

        流程：
        1. 获取股票基本信息
        2. 获取最新财务数据（计算自由现金流）
        3. 调用 Domain 层的 DCF 计算逻辑
        4. 计算每股内在价值
        5. 对比当前价格，计算上涨空间
        6. 返回结果
        """
        try:
            from apps.equity.domain.services import ValuationAnalyzer

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取最新财务数据
            financial = self.stock_repo.get_latest_financial_data(
                request.stock_code,
                hydrate=request.mode != "published",
                published_only=request.mode == "published",
                publication_key=request.publication_key,
            )
            if not financial:
                raise ValueError(f"未找到股票 {request.stock_code} 的财务数据")

            # 3. 计算自由现金流（简化版：FCF = 净利润 + 折旧 - 资本支出 - 营运资本变化）
            # 简化：使用净利润的 80% 作为自由现金流近似值
            latest_fcf = financial.net_profit * Decimal("0.8")
            if not latest_fcf.is_finite() or latest_fcf <= 0:
                raise ValueError("自由现金流必须为有限正数，当前财务数据不适合 DCF")

            # 4. 调用 Domain 层的 DCF 计算
            analyzer = ValuationAnalyzer()
            intrinsic_value = analyzer.calculate_dcf_value(
                latest_fcf=latest_fcf,
                growth_rate=request.growth_rate,
                discount_rate=request.discount_rate,
                terminal_growth=request.terminal_growth,
                projection_years=request.projection_years,
            )

            # 5. 获取当前市值和股价
            valuation = self.stock_repo.get_valuation_history(
                request.stock_code,
                date.today() - timedelta(days=7),
                date.today(),
                hydrate=request.mode != "published",
                published_only=request.mode == "published",
                publication_key=request.publication_key,
            )
            if not valuation:
                raise ValueError(f"未找到股票 {request.stock_code} 的估值数据")
            current_mv = valuation[-1].total_mv
            if current_mv is None or not current_mv.is_finite() or current_mv <= 0:
                raise ValueError("总市值必须为有限正数，无法推导总股本")

            daily_prices = self.stock_repo.get_daily_prices(
                request.stock_code,
                start_date=date.today() - timedelta(days=30),
                end_date=date.today(),
                hydrate=request.mode != "published",
                published_only=request.mode == "published",
                publication_key=request.publication_key,
            )
            if not daily_prices:
                raise ValueError(f"未找到股票 {request.stock_code} 的当前价格")
            current_price = daily_prices[-1][1]
            if not current_price.is_finite() or current_price <= 0:
                raise ValueError("当前价格必须为有限正数")

            total_shares = current_mv / current_price
            intrinsic_value_per_share = intrinsic_value / total_shares
            upside = float((intrinsic_value_per_share - current_price) / current_price)

            # 6. 返回结果
            return CalculateDCFResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                intrinsic_value=intrinsic_value,
                intrinsic_value_per_share=intrinsic_value_per_share,
                current_price=current_price,
                upside=upside,
            )

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as e:
            logger.warning("CalculateDCFUseCase.execute failed: %s", e)
            return CalculateDCFResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                intrinsic_value=Decimal(0),
                intrinsic_value_per_share=None,
                current_price=None,
                upside=None,
                error=str(e),
            )


# ============================================================================
# 综合估值分析
# ============================================================================


@dataclass
class ComprehensiveValuationRequest:
    """综合估值分析请求"""

    stock_code: str
    lookback_days: int = 252  # 回看天数
    industry_avg_pe: float = 20.0  # 行业平均 PE
    industry_avg_pb: float = 2.0  # 行业平均 PB
    risk_free_rate: float = 0.03  # 无风险利率
    mode: str = "published"
    publication_key: str = "current"


@dataclass
class ValuationScoreDTO:
    """估值评分 DTO"""

    method: str
    score: float
    signal: str  # 'undervalued', 'fair', 'overvalued'
    details: EquityPayload

    def to_dict(self) -> EquityPayload:
        return {
            "method": self.method,
            "score": self.score,
            "signal": self.signal,
            "details": self.details,
        }


@dataclass
class ComprehensiveValuationResponse:
    """综合估值分析响应"""

    success: bool
    stock_code: str
    stock_name: str
    overall_score: float
    overall_signal: str
    recommendation: str
    confidence: float
    scores: list[EquityPayload]  # 序列化后的评分列表
    error: str | None = None


class ComprehensiveValuationUseCase:
    """综合估值分析用例"""

    def __init__(self, stock_repository: EquityStockReadRepositoryProtocol) -> None:
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
        """
        self.stock_repo = stock_repository

    def execute(self, request: ComprehensiveValuationRequest) -> ComprehensiveValuationResponse:
        """
        执行综合估值分析

        流程：
        1. 获取股票基本信息
        2. 获取最新财务数据
        3. 获取最新估值数据
        4. 获取历史估值数据
        5. 调用综合估值分析器
        6. 返回结果
        """
        try:
            from datetime import timedelta

            from apps.equity.domain.services_comprehensive_valuation import (
                ComprehensiveValuationAnalyzer,
            )

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取最新财务数据
            financial = self.stock_repo.get_latest_financial_data(
                request.stock_code,
                hydrate=request.mode != "published",
                published_only=request.mode == "published",
                publication_key=request.publication_key,
            )
            if not financial:
                raise ValueError(f"未找到股票 {request.stock_code} 的财务数据")

            # 3. 获取最新估值数据
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)

            valuation_history = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date,
                end_date,
                hydrate=request.mode != "published",
                published_only=request.mode == "published",
                publication_key=request.publication_key,
            )

            if not valuation_history:
                raise ValueError(f"未找到股票 {request.stock_code} 的估值数据")

            latest_valuation = valuation_history[-1]

            # 4. 提取历史 PE/PB 数据
            historical_pe = [v.pe for v in valuation_history if v.pe is not None and v.pe > 0]
            historical_pb = [v.pb for v in valuation_history if v.pb is not None and v.pb > 0]

            # 5. 调用综合估值分析器
            analyzer = ComprehensiveValuationAnalyzer()
            result = analyzer.analyze(
                stock_code=request.stock_code,
                financial=financial,
                valuation=latest_valuation,
                historical_pe=historical_pe,
                historical_pb=historical_pb,
                industry_avg_pe=request.industry_avg_pe,
                industry_avg_pb=request.industry_avg_pb,
                risk_free_rate=request.risk_free_rate,
            )

            # 6. 转换为响应格式
            scores_dto = [
                ValuationScoreDTO(
                    method=s.method, score=s.score, signal=s.signal, details=s.details
                )
                for s in result.scores
            ]

            return ComprehensiveValuationResponse(
                success=True,
                stock_code=result.stock_code,
                stock_name=stock_info.name,
                overall_score=result.overall_score,
                overall_signal=result.overall_signal,
                recommendation=result.recommendation,
                confidence=result.confidence,
                scores=[s.to_dict() for s in scores_dto],
            )

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as e:
            logger.warning("ComprehensiveValuationUseCase.execute failed: %s", e)
            return ComprehensiveValuationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                overall_score=0.0,
                overall_signal="",
                recommendation="",
                confidence=0.0,
                scores=[],
                error=str(e),
            )
