"""Analysis and screening actions for the equity API viewset.

Owns `EquityAnalysisActionsMixin`. The compatibility facade in `views.py`
composes the final `EquityViewSet` and keeps the legacy monkeypatch surface;
do not import it here.
"""

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.repository_provider import (
    get_equity_regime_history_repository,
)
from apps.equity.application.use_cases import (
    AnalyzeRegimeCorrelationRequest,
    AnalyzeRegimeCorrelationUseCase,
    AnalyzeValuationRequest,
    AnalyzeValuationUseCase,
    CalculateDCFRequest,
    CalculateDCFUseCase,
    ComprehensiveValuationRequest,
    ComprehensiveValuationUseCase,
    GetIntradayChartRequest,
    GetIntradayChartUseCase,
    GetTechnicalChartRequest,
    GetTechnicalChartUseCase,
    ScreenStocksRequest,
    ScreenStocksUseCase,
)

from .serializers import (
    AnalyzeRegimeCorrelationRequestSerializer,
    AnalyzeRegimeCorrelationResponseSerializer,
    AnalyzeValuationRequestSerializer,
    AnalyzeValuationResponseSerializer,
    CalculateDCFRequestSerializer,
    CalculateDCFResponseSerializer,
    ComprehensiveValuationRequestSerializer,
    ComprehensiveValuationResponseSerializer,
    IntradayChartRequestSerializer,
    IntradayChartResponseSerializer,
    ScreenStocksRequestSerializer,
    ScreenStocksResponseSerializer,
    TechnicalChartRequestSerializer,
    TechnicalChartResponseSerializer,
)
from .valuation_actions import typed_action, typed_schema


class EquityAnalysisActionsMixin:
    """Screening, valuation analysis, chart, DCF, and regime-correlation actions."""

    stock_repo: Any
    regime_repo: Any

    @typed_schema(
        summary="筛选个股",
        description="基于 Regime 和财务指标筛选个股",
        request=ScreenStocksRequestSerializer,
        responses={200: ScreenStocksResponseSerializer},
    )
    @typed_action(detail=False, methods=["post"], url_path="screen")
    def screen_stocks(self, request: Request) -> Response:
        """
        POST /api/equity/screen/

        筛选个股

        Request Body:
        {
            "regime": "Recovery",  // 可选，不填则自动获取最新
            "custom_rule": {  // 可选，自定义规则
                "min_roe": 20.0,
                "max_pe": 25.0
            },
            "max_count": 20
        }

        Response:
        {
            "success": true,
            "regime": "Recovery",
            "stock_codes": ["600030.SH", "000001.SZ"],
            "screening_criteria": {
                "min_roe": 15.0,
                "max_pe": 30.0
            }
        }
        """
        # 1. 验证请求
        serializer = ScreenStocksRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = ScreenStocksRequest(
            regime=data.get("regime"),
            custom_rule=data.get("custom_rule"),
            max_count=data.get("max_count"),
        )

        # 3. 执行用例
        use_case = ScreenStocksUseCase(
            stock_repository=self.stock_repo, regime_repository=self.regime_repo
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = ScreenStocksResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @typed_schema(
        summary="估值分析（个股详情）",
        description="获取个股的完整估值分析数据，包括基本信息、估值指标、财务数据等",
        request=AnalyzeValuationRequestSerializer,
        responses={200: AnalyzeValuationResponseSerializer},
    )
    @typed_action(
        detail=False,
        methods=["get"],
        url_path="valuation/(?P<stock_code>[^/]+)",
        permission_classes=[IsAuthenticated],
    )
    def analyze_valuation(self, request: Request, stock_code: str) -> Response:
        """
        GET /api/equity/valuation/{stock_code}/

        估值分析（个股详情页完整数据）

        Response:
        {
            "success": true,
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "sector": "银行",
            "market": "SZ",
            "list_date": "1991-04-03",
            "current_pe": 5.2,
            "pe_percentile": 0.15,
            "current_pb": 0.55,
            "pb_percentile": 0.20,
            "is_undervalued": true,
            "latest_valuation": {
                "pe": 5.2,
                "pb": 0.55,
                "ps": 1.2,
                "pe_percentile": 0.15,
                "pb_percentile": 0.20,
                "total_mv": 250000000000,
                "circ_mv": 250000000000,
                "dividend_yield": 5.5,
                "price": 12.5,
                "trade_date": "2026-03-22"
            },
            "financial_data": {
                "roe": 10.5,
                "roa": 0.8,
                "revenue": 100000000000,
                "net_profit": 25000000000,
                "revenue_growth": 8.5,
                "net_profit_growth": 12.3,
                "debt_ratio": 95.0,
                "gross_margin": null,
                "report_date": "2025-12-31"
            }
        }
        """
        # 1. 验证请求
        query = request.query_params.copy()
        query["stock_code"] = stock_code
        serializer = AnalyzeValuationRequestSerializer(data=query)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = AnalyzeValuationRequest(
            stock_code=data["stock_code"], lookback_days=data.get("lookback_days", 252)
        )

        # 3. 执行用例
        use_case = AnalyzeValuationUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = AnalyzeValuationResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @typed_schema(
        summary="技术图表数据",
        description="返回个股 K 线、均线、MACD 与最近金叉死叉信号",
        request=TechnicalChartRequestSerializer,
        responses={200: TechnicalChartResponseSerializer},
    )
    @typed_action(detail=False, methods=["get"], url_path="technical/(?P<stock_code>[^/]+)")
    def technical_chart(self, request: Request, stock_code: str) -> Response:
        """GET /api/equity/technical/{stock_code}/"""
        query = request.query_params.copy()
        query["stock_code"] = stock_code
        serializer = TechnicalChartRequestSerializer(data=query)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        use_case = GetTechnicalChartUseCase(stock_repository=self.stock_repo)
        response = use_case.execute(
            GetTechnicalChartRequest(
                stock_code=data["stock_code"],
                timeframe=data["timeframe"],
                lookback_days=data["lookback_days"],
            )
        )
        response_serializer = TechnicalChartResponseSerializer(response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @typed_schema(
        summary="分时图数据",
        description="返回个股最新交易日的 1 分钟分时价格、均价与成交量",
        request=IntradayChartRequestSerializer,
        responses={200: IntradayChartResponseSerializer},
    )
    @typed_action(detail=False, methods=["get"], url_path="intraday/(?P<stock_code>[^/]+)")
    def intraday_chart(self, request: Request, stock_code: str) -> Response:
        """GET /api/equity/intraday/{stock_code}/"""
        query = request.query_params.copy()
        query["stock_code"] = stock_code
        serializer = IntradayChartRequestSerializer(data=query)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        use_case = GetIntradayChartUseCase(stock_repository=self.stock_repo)
        response = use_case.execute(GetIntradayChartRequest(stock_code=data["stock_code"]))
        response_serializer = IntradayChartResponseSerializer(response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @typed_schema(
        summary="DCF 绝对估值",
        description="计算股票的内在价值",
        request=CalculateDCFRequestSerializer,
        responses={200: CalculateDCFResponseSerializer},
    )
    @typed_action(detail=False, methods=["post"], url_path="dcf")
    def calculate_dcf(self, request: Request) -> Response:
        """
        POST /api/equity/dcf/

        DCF 绝对估值

        Request Body:
        {
            "stock_code": "600030.SH",
            "growth_rate": 0.1,  // 可选，默认 0.1
            "discount_rate": 0.1,  // 可选，默认 0.1
            "terminal_growth": 0.03,  // 可选，默认 0.03
            "projection_years": 5  // 可选，默认 5
        }

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "intrinsic_value": 280000000000,
            "intrinsic_value_per_share": 28.5,
            "current_price": 23.5,
            "upside": 0.21  // 21% 上涨空间
        }
        """
        # 1. 验证请求
        serializer = CalculateDCFRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = CalculateDCFRequest(
            stock_code=data["stock_code"],
            growth_rate=data.get("growth_rate", 0.1),
            discount_rate=data.get("discount_rate", 0.1),
            terminal_growth=data.get("terminal_growth", 0.03),
            projection_years=data.get("projection_years", 5),
        )

        # 3. 执行用例
        use_case = CalculateDCFUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = CalculateDCFResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @typed_schema(
        summary="Regime 相关性分析",
        description="分析个股在不同宏观环境下的表现",
        request=AnalyzeRegimeCorrelationRequestSerializer,
        responses={200: AnalyzeRegimeCorrelationResponseSerializer},
    )
    @typed_action(
        detail=False,
        methods=["get"],
        url_path="regime-correlation/(?P<stock_code>[^/]+)",
    )
    def analyze_regime_correlation(self, request: Request, stock_code: str) -> Response:
        """
        GET /api/equity/regime-correlation/{stock_code}/

        Regime 相关性分析

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "regime_performance": [
                {
                    "regime": "Recovery",
                    "avg_return": 0.0025,
                    "beta": 1.3,
                    "sample_days": 320
                },
                {
                    "regime": "Overheat",
                    "avg_return": 0.0018,
                    "beta": 1.1,
                    "sample_days": 280
                },
                {
                    "regime": "Stagflation",
                    "avg_return": -0.0012,
                    "beta": 0.9,
                    "sample_days": 310
                },
                {
                    "regime": "Deflation",
                    "avg_return": -0.0008,
                    "beta": 0.8,
                    "sample_days": 350
                }
            ],
            "best_regime": "Recovery",
            "worst_regime": "Stagflation"
        }
        """
        # 1. 验证请求
        query = request.query_params.copy()
        query["stock_code"] = stock_code
        serializer = AnalyzeRegimeCorrelationRequestSerializer(data=query)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = AnalyzeRegimeCorrelationRequest(
            stock_code=data["stock_code"], lookback_days=data.get("lookback_days", 1260)
        )

        # 3. 执行用例
        use_case = AnalyzeRegimeCorrelationUseCase(
            stock_repository=self.stock_repo,
            regime_repository=get_equity_regime_history_repository(),
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 转换 regime_performance 为列表格式（用于序列化）
        if use_case_response.success:
            response_data = {
                "success": use_case_response.success,
                "stock_code": use_case_response.stock_code,
                "stock_name": use_case_response.stock_name,
                "regime_performance": [
                    {
                        "regime": rp.regime,
                        "avg_return": rp.avg_return,
                        "beta": rp.beta,
                        "sample_days": rp.sample_days,
                    }
                    for rp in use_case_response.regime_performance.values()
                ],
                "best_regime": use_case_response.best_regime,
                "worst_regime": use_case_response.worst_regime,
            }
        else:
            response_data = {
                "success": use_case_response.success,
                "stock_code": use_case_response.stock_code,
                "stock_name": "",
                "regime_performance": [],
                "best_regime": "",
                "worst_regime": "",
                "error": use_case_response.error,
            }

        # 5. 返回响应
        return Response(response_data, status=status.HTTP_200_OK)

    @typed_schema(
        summary="综合估值分析",
        description="整合多种估值方法，提供综合的低估/高估判断",
        request=ComprehensiveValuationRequestSerializer,
        responses={200: ComprehensiveValuationResponseSerializer},
    )
    @typed_action(detail=False, methods=["post"], url_path="comprehensive-valuation")
    def comprehensive_valuation(self, request: Request) -> Response:
        """
        POST /api/equity/comprehensive-valuation/

        综合估值分析

        整合多种估值方法：
        1. PE/PB 百分位分析（权重 30%）
        2. 相对行业估值（权重 20%）
        3. PEG 估值（权重 20%）
        4. 质量评分（权重 15%）
        5. DCF 绝对估值（权重 15%）

        Request Body:
        {
            "stock_code": "600030.SH",
            "lookback_days": 252,  // 可选，默认 252
            "industry_avg_pe": 20.0,  // 可选，默认 20.0
            "industry_avg_pb": 2.0,  // 可选，默认 2.0
            "risk_free_rate": 0.03  // 可选，默认 0.03
        }

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "overall_score": 76.5,
            "overall_signal": "buy",
            "recommendation": "推荐买入。股票估值偏低，具有投资价值。",
            "confidence": 0.82,
            "scores": [
                {
                    "method": "PE/PB 百分位",
                    "score": 80,
                    "signal": "undervalued",
                    "details": {"pe_percentile": 0.25, "pb_percentile": 0.30}
                },
                {
                    "method": "相对行业",
                    "score": 70,
                    "signal": "undervalued",
                    "details": {"pe_ratio": 0.75, "pb_ratio": 0.80}
                },
                {
                    "method": "PEG",
                    "score": 85,
                    "signal": "undervalued",
                    "details": {"peg": 0.67}
                },
                {
                    "method": "质量评分",
                    "score": 65,
                    "signal": "fair",
                    "details": {"roe": 16.5, "revenue_growth": 18.0}
                }
            ]
        }
        """
        # 1. 验证请求
        serializer = ComprehensiveValuationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = ComprehensiveValuationRequest(
            stock_code=data["stock_code"],
            lookback_days=data.get("lookback_days", 252),
            industry_avg_pe=data.get("industry_avg_pe", 20.0),
            industry_avg_pb=data.get("industry_avg_pb", 2.0),
            risk_free_rate=data.get("risk_free_rate", 0.03),
        )

        # 3. 执行用例
        use_case = ComprehensiveValuationUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = ComprehensiveValuationResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


__all__ = ["EquityAnalysisActionsMixin"]
