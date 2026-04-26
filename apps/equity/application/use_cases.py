"""
个股分析模块 Application 层用例

遵循四层架构规范：
- Application 层负责用例编排
- 通过依赖注入使用 Infrastructure 层
- 调用 Domain 层的业务逻辑
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from apps.equity.domain.rules import StockScreeningRule
from apps.equity.domain.services import StockScreener
from apps.equity.domain.services_technical import TechnicalChartService


@dataclass
class ScreenStocksRequest:
    """筛选个股请求"""
    regime: str | None = None  # 如果为 None，自动获取最新 Regime
    custom_rule: dict | None = None  # 自定义规则
    max_count: int = 30


@dataclass
class ScreenStocksResponse:
    """筛选个股响应"""
    success: bool
    regime: str
    stock_codes: list[str]
    items: list[dict]
    screening_criteria: dict
    error: str | None = None


class ScreenStocksUseCase:
    """筛选个股用例"""

    def __init__(self, stock_repository, regime_repository):
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
            # 1. 获取 Regime
            if request.regime:
                regime = request.regime
            else:
                from apps.regime.application.current_regime import resolve_current_regime
                regime = resolve_current_regime(as_of_date=date.today()).dominant_regime

            # 2. 获取筛选规则（从数据库配置加载）
            from apps.equity.infrastructure.config_loader import get_stock_screening_rule
            rule = get_stock_screening_rule(regime)

            if not rule:
                raise ValueError(
                    f"未找到 Regime '{regime}' 的筛选规则，"
                    f"请在 Django Admin 中配置或运行 scripts/init_equity_config.py"
                )

            if request.custom_rule:
                # 用户自定义规则覆盖
                rule = self._parse_custom_rule(request.custom_rule, regime)

            # 调整 max_count
            if request.max_count != rule.max_count:
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
                    max_count=request.max_count
                )

            # 3. 获取全市场数据（最新财务数据 + 最新估值）
            all_stocks = self.stock_repo.get_all_stocks_with_fundamentals()

            if not all_stocks:
                raise ValueError("没有找到股票数据，请先运行数据采集任务")

            # 4. 获取评分权重配置
            from apps.equity.infrastructure.providers import ScoringWeightConfigRepository
            config_repo = ScoringWeightConfigRepository()
            scoring_config = config_repo.get_active_config()

            # 5. 筛选（调用 Domain 服务，传入评分配置）
            screener = StockScreener(scoring_config=scoring_config)
            stock_codes = screener.screen(all_stocks, rule)

            stock_lookup = {
                stock_info.stock_code: (stock_info, financial, valuation)
                for stock_info, financial, valuation in all_stocks
            }
            items: list[dict] = []
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
                    'rule_name': rule.name,
                    'min_roe': rule.min_roe,
                    'max_pe': rule.max_pe,
                    'max_pb': rule.max_pb,
                    'sectors': rule.sector_preference
                }
            )

        except Exception as e:
            return ScreenStocksResponse(
                success=False,
                regime='',
                stock_codes=[],
                items=[],
                screening_criteria={},
                error=str(e)
            )

    def _parse_custom_rule(
        self,
        custom_rule: dict,
        regime: str
    ) -> StockScreeningRule:
        """
        解析自定义规则

        Args:
            custom_rule: 自定义规则字典
            regime: Regime 名称

        Returns:
            StockScreeningRule 对象
        """
        return StockScreeningRule(
            regime=regime,
            name=custom_rule.get('name', '自定义规则'),
            min_roe=custom_rule.get('min_roe', 0.0),
            min_revenue_growth=custom_rule.get('min_revenue_growth', 0.0),
            min_profit_growth=custom_rule.get('min_profit_growth', 0.0),
            max_debt_ratio=custom_rule.get('max_debt_ratio', 100.0),
            max_pe=custom_rule.get('max_pe', 999.0),
            max_pb=custom_rule.get('max_pb', 999.0),
            min_market_cap=Decimal(str(custom_rule.get('min_market_cap', 0))),
            sector_preference=custom_rule.get('sector_preference'),
            max_count=custom_rule.get('max_count', 50)
            )


@dataclass
class GetTechnicalChartRequest:
    """技术图表请求。"""

    stock_code: str
    timeframe: str = "day"
    lookback_days: int = 365


@dataclass
class GetTechnicalChartResponse:
    """技术图表响应。"""

    success: bool
    stock_code: str
    stock_name: str
    timeframe: str
    candles: list[dict]
    signals: list[dict]
    latest_signal: dict | None
    error: str | None = None


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
    points: list[dict]
    latest_point: dict | None
    session_date: str | None
    source: str | None
    error: str | None = None


class GetTechnicalChartUseCase:
    """个股技术图表用例。"""

    def __init__(self, stock_repository):
        self.stock_repo = stock_repository
        self.chart_service = TechnicalChartService()

    def execute(self, request: GetTechnicalChartRequest) -> GetTechnicalChartResponse:
        """获取技术图表数据。"""
        try:
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)
            bars = self.stock_repo.get_technical_bars(
                request.stock_code,
                start_date=start_date,
                end_date=end_date,
            )
            if not bars:
                raise ValueError(f"未找到股票 {request.stock_code} 的日线技术数据")

            aggregated_bars = self.chart_service.aggregate_bars(bars, request.timeframe)
            signals = self.chart_service.detect_crossovers(aggregated_bars)

            candle_payload = [
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
            signal_payload = [
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
            )
        except Exception as exc:
            return GetTechnicalChartResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                timeframe=request.timeframe,
                candles=[],
                signals=[],
                latest_signal=None,
                error=str(exc),
            )


class GetIntradayChartUseCase:
    """个股分时图用例。"""

    def __init__(self, stock_repository):
        self.stock_repo = stock_repository

    def execute(self, request: GetIntradayChartRequest) -> GetIntradayChartResponse:
        """获取分时图数据。"""
        try:
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            points = self.stock_repo.get_intraday_points(request.stock_code)
            if not points:
                raise ValueError(f"未找到股票 {request.stock_code} 的分时数据")

            payload = [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "price": float(point.price),
                    "avg_price": float(point.avg_price) if point.avg_price is not None else None,
                    "volume": point.volume,
                }
                for point in points
            ]

            return GetIntradayChartResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                points=payload,
                latest_point=payload[-1] if payload else None,
                session_date=points[-1].timestamp.date().isoformat() if points else None,
                source=(
                    self.stock_repo.get_last_intraday_source()
                    if hasattr(self.stock_repo, "get_last_intraday_source")
                    else "akshare"
                ),
            )
        except Exception as exc:
            return GetIntradayChartResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                points=[],
                latest_point=None,
                session_date=None,
                source=None,
                error=str(exc),
            )


@dataclass
class AnalyzeValuationRequest:
    """估值分析请求"""
    stock_code: str
    lookback_days: int = 252  # 回看天数（默认 1 年）


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
    current_pe: float
    pe_percentile: float
    current_pb: float
    pb_percentile: float
    is_undervalued: bool
    # 最新估值详情
    latest_valuation: dict | None = None
    # 财务数据
    financial_data: dict | None = None
    error: str | None = None


class AnalyzeValuationUseCase:
    """估值分析用例"""

    def __init__(self, stock_repository):
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
        try:
            from datetime import timedelta

            from apps.equity.domain.services import ValuationAnalyzer

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取历史估值数据
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)

            valuation_history = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date,
                end_date
            )

            # 5. 获取财务数据
            financial = self.stock_repo.get_latest_financial_data(request.stock_code)

            # 6. 获取日线数据（用于获取当前价格、换手率等）
            daily_prices = self.stock_repo.get_daily_prices(
                request.stock_code,
                start_date=end_date - timedelta(days=7),
                end_date=end_date
            )
            latest_daily = daily_prices[-1] if daily_prices else None

            latest = None
            pe_percentile = 0.0
            pb_percentile = 0.0
            is_undervalued = False
            latest_valuation = None
            response_error = None

            if valuation_history:
                latest = valuation_history[-1]

                # 3. 计算百分位
                analyzer = ValuationAnalyzer()
                pe_history = [v.pe for v in valuation_history if v.pe > 0]
                pb_history = [v.pb for v in valuation_history if v.pb > 0]

                pe_percentile = analyzer.calculate_pe_percentile(latest.pe, pe_history)
                pb_percentile = analyzer.calculate_pb_percentile(latest.pb, pb_history)

                # 4. 判断是否低估
                is_undervalued = analyzer.is_undervalued(pe_percentile, pb_percentile)

                # 7. 构建最新估值详情字典
                latest_valuation = {
                    'pe': latest.pe if latest.pe > 0 else None,
                    'pb': latest.pb if latest.pb > 0 else None,
                    'ps': latest.ps if latest.ps > 0 else None,
                    'pe_percentile': pe_percentile,
                    'pb_percentile': pb_percentile,
                    'total_mv': float(latest.total_mv) if latest.total_mv else None,
                    'circ_mv': float(latest.circ_mv) if latest.circ_mv else None,
                    'dividend_yield': latest.dividend_yield if latest.dividend_yield > 0 else None,
                    'price': float(latest_daily[1]) if latest_daily else None,
                    'trade_date': latest.trade_date.isoformat() if latest.trade_date else None,
                    'updated_at': latest.fetched_at.isoformat() if hasattr(latest, 'fetched_at') and latest.fetched_at else None,
                }
            else:
                response_error = f"未找到股票 {request.stock_code} 的估值数据"
                latest_valuation = {
                    'pe': None,
                    'pb': None,
                    'ps': None,
                    'pe_percentile': 0.0,
                    'pb_percentile': 0.0,
                    'total_mv': None,
                    'circ_mv': None,
                    'dividend_yield': None,
                    'price': float(latest_daily[1]) if latest_daily else None,
                    'trade_date': latest_daily[0].isoformat() if latest_daily else None,
                    'updated_at': None,
                }

            # 8. 构建财务数据字典
            financial_data = None
            if financial:
                financial_data = {
                    'roe': financial.roe,
                    'roa': financial.roa,
                    'revenue': float(financial.revenue) if financial.revenue else None,
                    'net_profit': float(financial.net_profit) if financial.net_profit else None,
                    'revenue_growth': financial.revenue_growth,
                    'net_profit_growth': financial.net_profit_growth,
                    'debt_ratio': financial.debt_ratio,
                    'gross_margin': None,  # 需要从其他地方获取
                    'report_date': financial.report_date.isoformat() if financial.report_date else None,
                }

            # 9. 返回结果
            return AnalyzeValuationResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                sector=stock_info.sector or '',
                market=stock_info.market or '',
                list_date=stock_info.list_date.isoformat() if stock_info.list_date else None,
                current_pe=latest.pe if latest is not None else 0.0,
                pe_percentile=pe_percentile,
                current_pb=latest.pb if latest is not None else 0.0,
                pb_percentile=pb_percentile,
                is_undervalued=is_undervalued,
                latest_valuation=latest_valuation,
                financial_data=financial_data,
                error=response_error,
            )

        except Exception as e:
            return AnalyzeValuationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name='',
                sector='',
                market='',
                list_date=None,
                current_pe=0.0,
                pe_percentile=0.0,
                current_pb=0.0,
                pb_percentile=0.0,
                is_undervalued=False,
                latest_valuation=None,
                financial_data=None,
                error=str(e)
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

    def __init__(self, stock_repository):
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
            financial = self.stock_repo.get_latest_financial_data(request.stock_code)
            if not financial:
                raise ValueError(f"未找到股票 {request.stock_code} 的财务数据")

            # 3. 计算自由现金流（简化版：FCF = 净利润 + 折旧 - 资本支出 - 营运资本变化）
            # 简化：使用净利润的 80% 作为自由现金流近似值
            latest_fcf = financial.net_profit * Decimal(0.8)

            # 4. 调用 Domain 层的 DCF 计算
            analyzer = ValuationAnalyzer()
            intrinsic_value = analyzer.calculate_dcf_value(
                latest_fcf=latest_fcf,
                growth_rate=request.growth_rate,
                discount_rate=request.discount_rate,
                terminal_growth=request.terminal_growth,
                projection_years=request.projection_years
            )

            # 5. 获取当前市值和股价
            valuation = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date=date.today() - timedelta(days=7),
                end_date=date.today()
            )

            current_price = None
            intrinsic_value_per_share = None
            upside = None

            if valuation:
                current_mv = valuation[-1].total_mv
                current_price = valuation[-1].total_mv / valuation[-1].ps if valuation[-1].ps > 0 else None

                # 计算每股内在价值（简化：使用总股本）
                # intrinsic_value_per_share = intrinsic_value / total_shares
                # 这里简化处理：假设内在价值/市值比例
                if current_mv and current_mv > 0:
                    intrinsic_value_per_share = intrinsic_value / current_mv * (current_price or Decimal(1))

                # 计算上涨空间
                if current_price and current_price > 0:
                    upside = float((intrinsic_value_per_share - current_price) / current_price)

            # 6. 返回结果
            return CalculateDCFResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                intrinsic_value=intrinsic_value,
                intrinsic_value_per_share=intrinsic_value_per_share,
                current_price=current_price,
                upside=upside
            )

        except Exception as e:
            return CalculateDCFResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name='',
                intrinsic_value=Decimal(0),
                intrinsic_value_per_share=None,
                current_price=None,
                upside=None,
                error=str(e)
            )


# ============================================================================
# Regime 相关性分析
# ============================================================================

@dataclass
class AnalyzeRegimeCorrelationRequest:
    """Regime 相关性分析请求"""
    stock_code: str
    lookback_days: int = 1260  # 回看天数（默认 5 年，约 1260 个交易日）


@dataclass
class RegimePerformance:
    """单个 Regime 的表现"""
    regime: str
    avg_return: float
    beta: float
    sample_days: int


@dataclass
class AnalyzeRegimeCorrelationResponse:
    """Regime 相关性分析响应"""
    success: bool
    stock_code: str
    stock_name: str
    regime_performance: dict[str, RegimePerformance]
    best_regime: str
    worst_regime: str
    error: str | None = None


class AnalyzeRegimeCorrelationUseCase:
    """Regime 相关性分析用例"""

    def __init__(self, stock_repository, regime_repository):
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
            regime_repository: Regime 数据仓储
        """
        self.stock_repo = stock_repository
        self.regime_repo = regime_repository

    def execute(self, request: AnalyzeRegimeCorrelationRequest) -> AnalyzeRegimeCorrelationResponse:
        """
        执行 Regime 相关性分析

        流程：
        1. 获取股票基本信息
        2. 获取历史收益率数据
        3. 获取 Regime 历史数据
        4. 获取市场指数收益率（用于计算 Beta）
        5. 调用 Domain 层的分析逻辑
        6. 返回结果
        """
        try:
            from datetime import timedelta

            from apps.equity.domain.services import RegimeCorrelationAnalyzer

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取历史收益率
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)

            stock_returns = self.stock_repo.calculate_daily_returns(
                request.stock_code,
                start_date,
                end_date
            )

            if not stock_returns:
                raise ValueError(
                    f"未找到股票 {request.stock_code} 的价格数据，请先同步日线数据或检查 Tushare/AKShare 数据源"
                )

            # 3. 获取 Regime 历史（从 Regime 模块）
            regime_history = self._get_regime_history(start_date, end_date)

            # 4. 获取市场收益率（使用沪深 300）
            market_returns = self._get_market_returns(start_date, end_date)

            # 5. 调用 Domain 层分析
            analyzer = RegimeCorrelationAnalyzer()

            # 计算各 Regime 下的平均收益
            avg_returns = analyzer.calculate_regime_correlation(
                stock_returns,
                regime_history
            )

            # 计算各 Regime 下的 Beta
            regime_betas = analyzer.calculate_regime_beta(
                stock_returns,
                market_returns,
                regime_history
            )

            # 6. 构造响应
            regime_performance = {}
            for regime in ['Recovery', 'Overheat', 'Stagflation', 'Deflation']:
                # 计算样本天数
                sample_days = sum(
                    1 for r in regime_history.values()
                    if r == regime
                )

                regime_performance[regime] = RegimePerformance(
                    regime=regime,
                    avg_return=avg_returns.get(regime, 0.0),
                    beta=regime_betas.get(regime, 1.0),
                    sample_days=sample_days
                )

            # 找出最佳和最差 Regime
            sorted_by_return = sorted(
                regime_performance.items(),
                key=lambda x: x[1].avg_return,
                reverse=True
            )
            best_regime = sorted_by_return[0][0] if sorted_by_return else 'Recovery'
            worst_regime = sorted_by_return[-1][0] if sorted_by_return else 'Deflation'

            return AnalyzeRegimeCorrelationResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                regime_performance=regime_performance,
                best_regime=best_regime,
                worst_regime=worst_regime
            )

        except Exception as e:
            return AnalyzeRegimeCorrelationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name='',
                regime_performance={},
                best_regime='',
                worst_regime='',
                error=str(e)
            )

    def _get_regime_history(self, start_date: date, end_date: date) -> dict[date, str]:
        """
        获取 Regime 历史数据

        从 regime 模块获取指定日期范围内的 Regime 快照，
        将其转换为按日期索引的字典。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: Regime 名称}
        """
        from apps.equity.infrastructure.adapters import RegimeRepositoryAdapter

        try:
            regime_adapter = RegimeRepositoryAdapter()
            snapshots = regime_adapter.get_snapshots_in_range(start_date, end_date)

            # 将快照列表转换为日期字典
            regime_history = {}
            for snapshot in snapshots:
                regime_history[snapshot.observed_at] = snapshot.dominant_regime

            # 对于缺失的日期，使用前一个有效日期的 Regime
            return self._fill_missing_dates(regime_history, start_date, end_date)

        except Exception:
            # 如果获取失败，返回空字典
            # Domain 层的 RegimeCorrelationAnalyzer 会处理空数据情况
            return {}

    def _get_market_returns(self, start_date: date, end_date: date) -> dict[date, float]:
        """
        获取市场指数收益率

        使用数据库配置的市场基准。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}
        """
        from apps.equity.infrastructure.adapters import MarketDataRepositoryAdapter
        from core.integration.runtime_benchmarks import get_runtime_benchmark_code

        try:
            market_adapter = MarketDataRepositoryAdapter()
            benchmark_code = get_runtime_benchmark_code("equity_market_benchmark")
            if not benchmark_code:
                return {}
            return market_adapter.get_index_daily_returns(
                index_code=benchmark_code,
                start_date=start_date,
                end_date=end_date
            )

        except Exception:
            # 如果获取失败，返回空字典
            return {}

    def _fill_missing_dates(
        self,
        regime_history: dict[date, str],
        start_date: date,
        end_date: date
    ) -> dict[date, str]:
        """
        填充缺失的日期

        Regime 数据通常不会每天都有，使用前一个有效日期的值填充。

        Args:
            regime_history: 原始 Regime 历史（可能有日期缺失）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            填充后的完整日期字典
        """
        from datetime import timedelta

        result = {}
        current = start_date
        last_regime = 'Recovery'  # 默认 Regime

        # 按日期排序
        sorted_dates = sorted(regime_history.keys())

        while current <= end_date:
            # 如果当前日期有数据，使用当前日期的数据
            if current in regime_history:
                result[current] = regime_history[current]
                last_regime = regime_history[current]
            else:
                # 找到最近的前一个日期
                prev_date = None
                for d in sorted_dates:
                    if d <= current:
                        prev_date = d
                    else:
                        break

                if prev_date:
                    result[current] = regime_history[prev_date]
                    last_regime = regime_history[prev_date]
                else:
                    # 没有找到前一个日期，使用已知的最后一个 Regime
                    result[current] = last_regime

            current += timedelta(days=1)

        return result


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


@dataclass
class ValuationScoreDTO:
    """估值评分 DTO"""
    method: str
    score: float
    signal: str  # 'undervalued', 'fair', 'overvalued'
    details: dict

    def to_dict(self):
        return {
            'method': self.method,
            'score': self.score,
            'signal': self.signal,
            'details': self.details
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
    scores: list[dict]  # 序列化后的评分列表
    error: str | None = None


class ComprehensiveValuationUseCase:
    """综合估值分析用例"""

    def __init__(self, stock_repository):
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
            financial = self.stock_repo.get_latest_financial_data(request.stock_code)
            if not financial:
                raise ValueError(f"未找到股票 {request.stock_code} 的财务数据")

            # 3. 获取最新估值数据
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)

            valuation_history = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date,
                end_date
            )

            if not valuation_history:
                raise ValueError(f"未找到股票 {request.stock_code} 的估值数据")

            latest_valuation = valuation_history[-1]

            # 4. 提取历史 PE/PB 数据
            historical_pe = [v.pe for v in valuation_history if v.pe > 0]
            historical_pb = [v.pb for v in valuation_history if v.pb > 0]

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
                risk_free_rate=request.risk_free_rate
            )

            # 6. 转换为响应格式
            scores_dto = [
                ValuationScoreDTO(
                    method=s.method,
                    score=s.score,
                    signal=s.signal,
                    details=s.details
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
                scores=[s.to_dict() for s in scores_dto]
            )

        except Exception as e:
            return ComprehensiveValuationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name='',
                overall_score=0.0,
                overall_signal='',
                recommendation='',
                confidence=0.0,
                scores=[],
                error=str(e)
            )
