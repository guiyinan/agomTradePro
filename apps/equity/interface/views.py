"""
个股分析模块 Interface 层视图

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
- 包含 API 视图（DRF）和页面视图（Django Views）
"""

from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.equity.application.use_cases import (
    ScreenStocksUseCase,
    AnalyzeValuationUseCase,
    CalculateDCFUseCase,
    AnalyzeRegimeCorrelationUseCase,
    ComprehensiveValuationUseCase,
    ScreenStocksRequest,
    AnalyzeValuationRequest,
    CalculateDCFRequest,
    AnalyzeRegimeCorrelationRequest,
    ComprehensiveValuationRequest,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository
from .serializers import (
    ScreenStocksRequestSerializer,
    ScreenStocksResponseSerializer,
    AnalyzeValuationRequestSerializer,
    AnalyzeValuationResponseSerializer,
    CalculateDCFRequestSerializer,
    CalculateDCFResponseSerializer,
    AnalyzeRegimeCorrelationRequestSerializer,
    AnalyzeRegimeCorrelationResponseSerializer,
    ComprehensiveValuationRequestSerializer,
    ComprehensiveValuationResponseSerializer,
)


# ============================================================================
# 页面视图（前端）
# ============================================================================

@require_http_methods(["GET"])
def screen_page(request):
    """
    个股筛选页面

    GET /equity/screen/
    """
    return render(request, 'equity/screen.html')


@require_http_methods(["GET"])
def detail_page(request, stock_code):
    """
    个股详情页面

    GET /equity/detail/<stock_code>/
    """
    context = {
        'stock_code': stock_code
    }
    return render(request, 'equity/detail.html', context)


@require_http_methods(["GET"])
def pool_page(request):
    """
    股票池管理页面

    GET /equity/pool/
    """
    return render(request, 'equity/pool.html')


class EquityViewSet(viewsets.ViewSet):
    """个股分析 API"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stock_repo = DjangoStockRepository()
        # TODO: 注入 regime_repo
        # self.regime_repo = ...

    @extend_schema(
        summary="筛选个股",
        description="基于 Regime 和财务指标筛选个股",
        request=ScreenStocksRequestSerializer,
        responses={200: ScreenStocksResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='screen')
    def screen_stocks(self, request):
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
            regime=data.get('regime'),
            custom_rule=data.get('custom_rule'),
            max_count=data.get('max_count', 30)
        )

        # 3. 执行用例（需要 regime_repo，暂时使用 mock）
        # TODO: 注入真实的 regime_repo
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository

        use_case = ScreenStocksUseCase(
            stock_repository=self.stock_repo,
            regime_repository=DjangoRegimeRepository()
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = ScreenStocksResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="估值分析",
        description="分析个股的估值水平和历史百分位",
        request=AnalyzeValuationRequestSerializer,
        responses={200: AnalyzeValuationResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation/(?P<stock_code>[^/.]+)')
    def analyze_valuation(self, request, stock_code):
        """
        GET /api/equity/valuation/{stock_code}/

        估值分析

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "current_pe": 12.5,
            "pe_percentile": 0.25,
            "current_pb": 1.3,
            "pb_percentile": 0.30,
            "is_undervalued": true
        }
        """
        # 1. 验证请求
        serializer = AnalyzeValuationRequestSerializer(data={
            'stock_code': stock_code,
            'lookback_days': request.query_params.get('lookback_days', 252)
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = AnalyzeValuationRequest(
            stock_code=data['stock_code'],
            lookback_days=data.get('lookback_days', 252)
        )

        # 3. 执行用例
        use_case = AnalyzeValuationUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = AnalyzeValuationResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="DCF 绝对估值",
        description="计算股票的内在价值",
        request=CalculateDCFRequestSerializer,
        responses={200: CalculateDCFResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='dcf')
    def calculate_dcf(self, request):
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
            stock_code=data['stock_code'],
            growth_rate=data.get('growth_rate', 0.1),
            discount_rate=data.get('discount_rate', 0.1),
            terminal_growth=data.get('terminal_growth', 0.03),
            projection_years=data.get('projection_years', 5)
        )

        # 3. 执行用例
        use_case = CalculateDCFUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = CalculateDCFResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Regime 相关性分析",
        description="分析个股在不同宏观环境下的表现",
        request=AnalyzeRegimeCorrelationRequestSerializer,
        responses={200: AnalyzeRegimeCorrelationResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='regime-correlation/(?P<stock_code>[^/.]+)')
    def analyze_regime_correlation(self, request, stock_code):
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
        serializer = AnalyzeRegimeCorrelationRequestSerializer(data={
            'stock_code': stock_code,
            'lookback_days': request.query_params.get('lookback_days', 1260)
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = AnalyzeRegimeCorrelationRequest(
            stock_code=data['stock_code'],
            lookback_days=data.get('lookback_days', 1260)
        )

        # 3. 执行用例
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository

        use_case = AnalyzeRegimeCorrelationUseCase(
            stock_repository=self.stock_repo,
            regime_repository=DjangoRegimeRepository()
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 转换 regime_performance 为列表格式（用于序列化）
        if use_case_response.success:
            response_data = {
                'success': use_case_response.success,
                'stock_code': use_case_response.stock_code,
                'stock_name': use_case_response.stock_name,
                'regime_performance': [
                    {
                        'regime': rp.regime,
                        'avg_return': rp.avg_return,
                        'beta': rp.beta,
                        'sample_days': rp.sample_days
                    }
                    for rp in use_case_response.regime_performance.values()
                ],
                'best_regime': use_case_response.best_regime,
                'worst_regime': use_case_response.worst_regime
            }
        else:
            response_data = {
                'success': use_case_response.success,
                'stock_code': use_case_response.stock_code,
                'stock_name': '',
                'regime_performance': [],
                'best_regime': '',
                'worst_regime': '',
                'error': use_case_response.error
            }

        # 5. 返回响应
        return Response(response_data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="综合估值分析",
        description="整合多种估值方法，提供综合的低估/高估判断",
        request=ComprehensiveValuationRequestSerializer,
        responses={200: ComprehensiveValuationResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='comprehensive-valuation')
    def comprehensive_valuation(self, request):
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
            stock_code=data['stock_code'],
            lookback_days=data.get('lookback_days', 252),
            industry_avg_pe=data.get('industry_avg_pe', 20.0),
            industry_avg_pb=data.get('industry_avg_pb', 2.0),
            risk_free_rate=data.get('risk_free_rate', 0.03)
        )

        # 3. 执行用例
        use_case = ComprehensiveValuationUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = ComprehensiveValuationResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='pool')
    def get_pool(self, request):
        """
        GET /equity/api/pool/

        获取当前股票池
        """
        # TODO: 实现股票池逻辑
        # 临时返回模拟数据
        from datetime import datetime
        from apps.regime.application.current_regime import resolve_current_regime
        latest_regime = resolve_current_regime()

        # 模拟股票数据
        mock_stocks = [
            {
                'code': '600030.SH',
                'name': '中信证券',
                'sector': '金融',
                'roe': 12.5,
                'pe': 15.2,
                'pb': 1.3,
                'revenue_growth': 8.5,
                'profit_growth': 10.2,
                'score': 75.5
            },
            {
                'code': '000001.SZ',
                'name': '平安银行',
                'sector': '金融',
                'roe': 11.8,
                'pe': 6.5,
                'pb': 0.85,
                'revenue_growth': 5.2,
                'profit_growth': 8.1,
                'score': 70.2
            },
            {
                'code': '600519.SH',
                'name': '贵州茅台',
                'sector': '消费',
                'roe': 25.5,
                'pe': 28.5,
                'pb': 9.2,
                'revenue_growth': 15.8,
                'profit_growth': 18.5,
                'score': 85.0
            }
        ]

        return Response({
            'success': True,
            'regime': latest_regime.dominant_regime if latest_regime else 'Unknown',
            'count': len(mock_stocks),
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'avg_roe': sum(s['roe'] for s in mock_stocks) / len(mock_stocks),
            'avg_pe': sum(s['pe'] for s in mock_stocks) / len(mock_stocks),
            'stocks': mock_stocks
        })

    @action(detail=False, methods=['post'], url_path='pool/refresh')
    def refresh_pool(self, request):
        """
        POST /equity/api/pool/refresh/

        刷新股票池
        """
        # TODO: 实现刷新逻辑
        from datetime import datetime
        from apps.regime.application.current_regime import resolve_current_regime
        latest_regime = resolve_current_regime()

        return Response({
            'success': True,
            'message': '股票池已刷新',
            'regime': latest_regime.dominant_regime if latest_regime else 'Unknown',
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })


# ==================== 多维度筛选 API（通用资产分析框架集成） ====================


class EquityMultiDimScreenAPIView(APIView):
    """个股多维度筛选 API

    POST /api/equity/multidim-screen/

    使用通用资产分析框架进行多维度评分筛选。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository
        from apps.equity.application.services import EquityMultiDimScorer

        self.asset_repo = DjangoEquityAssetRepository()
        self.scorer = EquityMultiDimScorer(self.asset_repo)

    def post(self, request) -> Response:
        """
        多维度筛选个股

        请求体：
        {
            "filters": {
                "sector": "银行",
                "market": "SH",
                "min_market_cap": 50000000000,
                "max_pe": 15.0
            },
            "context": {
                "regime": "Recovery",
                "policy_level": "P0",
                "sentiment_index": 0.5
            },
            "max_count": 30
        }
        """
        # 1. 验证请求
        filters = request.data.get("filters", {})
        context_data = request.data.get("context", {})
        max_count = request.data.get("max_count", 30)

        # 2. 构建评分上下文
        from apps.asset_analysis.domain.value_objects import ScoreContext
        from apps.signal.infrastructure.repositories import DjangoSignalRepository

        # 获取激活的信号
        signal_repo = DjangoSignalRepository()
        active_signals = signal_repo.get_active_signals()

        context = ScoreContext(
            current_regime=context_data.get("regime", "Recovery"),
            policy_level=context_data.get("policy_level", "P0"),
            sentiment_index=context_data.get("sentiment_index", 0.0),
            active_signals=active_signals,
        )

        # 3. 执行筛选
        try:
            result = self.scorer.screen_stocks(
                filters=filters,
                context=context,
                max_count=max_count,
            )

            # 4. 返回响应
            return Response({
                "success": result["success"],
                "count": result["count"],
                "context": {
                    "regime": context.current_regime,
                    "policy_level": context.policy_level,
                    "sentiment_index": context.sentiment_index,
                    "active_signals_count": len(active_signals),
                },
                "stocks": result["stocks"],
            }, status=status.HTTP_200_OK if result["success"] else status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"筛选失败: {str(e)}",
                "stocks": [],
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

