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
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.equity.application.use_cases import (
    ScreenStocksUseCase,
    AnalyzeValuationUseCase,
    ScreenStocksRequest,
    AnalyzeValuationRequest,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository
from .serializers import (
    ScreenStocksRequestSerializer,
    ScreenStocksResponseSerializer,
    AnalyzeValuationRequestSerializer,
    AnalyzeValuationResponseSerializer,
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
