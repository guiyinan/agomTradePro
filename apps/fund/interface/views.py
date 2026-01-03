"""
基金分析模块 - 视图

包含：
- 页面视图（HTML）
- API 视图（REST）

遵循项目架构约束：
- 只负责请求/响应处理
- 调用 Application 层用例
- 不包含业务逻辑
"""

from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from typing import Dict, Any

from ..infrastructure.repositories import DjangoFundRepository
from ..application.use_cases import (
    ScreenFundsUseCase, ScreenFundsRequest,
    AnalyzeFundStyleUseCase, AnalyzeFundStyleRequest,
    CalculateFundPerformanceUseCase, CalculateFundPerformanceRequest,
    RankFundsUseCase
)
from .serializers import (
    ScreenFundsRequestSerializer, ScreenFundsResponseSerializer,
    AnalyzeFundStyleRequestSerializer, AnalyzeFundStyleResponseSerializer,
    CalculateFundPerformanceRequestSerializer, CalculateFundPerformanceResponseSerializer,
    FundScoreSerializer
)


# ============================================================================
# 页面视图（前端）
# ============================================================================

@require_http_methods(["GET"])
def dashboard_view(request):
    """
    基金分析仪表盘页面

    GET /fund/dashboard/
    """
    # 获取当前 Regime 信息
    from apps.regime.infrastructure.repositories import DjangoRegimeRepository
    regime_repo = DjangoRegimeRepository()
    latest_regime = regime_repo.get_latest_snapshot()

    regime_display = {
        'Recovery': '复苏',
        'Overheat': '过热',
        'Stagflation': '滞胀',
        'Deflation': '通缩',
    }

    context = {
        'current_regime': latest_regime.dominant_regime if latest_regime else 'Unknown',
        'regime_display': regime_display.get(latest_regime.dominant_regime) if latest_regime else '未知',
        'regime_confidence': f"{latest_regime.confidence:.1%}" if latest_regime else "N/A",
    }

    return render(request, 'fund/dashboard.html', context)


class ScreenFundsView(APIView):
    """筛选基金 API

    POST /api/fund/screen/
    """

    def post(self, request) -> Response:
        """筛选基金"""
        # 1. 验证请求
        serializer = ScreenFundsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': '请求参数无效', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data

        # 2. 构造请求对象
        screen_request = ScreenFundsRequest(
            regime=data.get('regime'),
            custom_types=data.get('custom_types'),
            custom_styles=data.get('custom_styles'),
            min_scale=data.get('min_scale'),
            max_count=data.get('max_count', 30)
        )

        # 3. 执行用例
        fund_repo = DjangoFundRepository()
        use_case = ScreenFundsUseCase(fund_repo)
        response = use_case.execute(screen_request)

        # 4. 序列化响应
        response_serializer = ScreenFundsResponseSerializer(response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AnalyzeFundStyleView(APIView):
    """分析基金风格 API

    GET /api/fund/style/{fund_code}/
    """

    def get(self, request, fund_code: str) -> Response:
        """分析基金风格"""
        # 1. 验证请求
        query_params = {**request.query_params, 'fund_code': fund_code}
        serializer = AnalyzeFundStyleRequestSerializer(data=query_params)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': '请求参数无效', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data

        # 2. 构造请求对象
        analyze_request = AnalyzeFundStyleRequest(
            fund_code=data['fund_code'],
            report_date=data.get('report_date')
        )

        # 3. 执行用例
        fund_repo = DjangoFundRepository()
        use_case = AnalyzeFundStyleUseCase(fund_repo)
        response = use_case.execute(analyze_request)

        # 4. 序列化响应
        response_serializer = AnalyzeFundStyleResponseSerializer(response)
        status_code = status.HTTP_200_OK if response.success else status.HTTP_404_NOT_FOUND
        return Response(response_serializer.data, status=status_code)


class CalculateFundPerformanceView(APIView):
    """计算基金业绩 API

    POST /api/fund/performance/calculate/
    """

    def post(self, request) -> Response:
        """计算基金业绩"""
        # 1. 验证请求
        serializer = CalculateFundPerformanceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': '请求参数无效', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data

        # 2. 构造请求对象
        perf_request = CalculateFundPerformanceRequest(
            fund_code=data['fund_code'],
            start_date=data['start_date'],
            end_date=data['end_date']
        )

        # 3. 执行用例
        fund_repo = DjangoFundRepository()
        use_case = CalculateFundPerformanceUseCase(fund_repo)
        response = use_case.execute(perf_request)

        # 4. 序列化响应
        response_serializer = CalculateFundPerformanceResponseSerializer(response)
        status_code = status.HTTP_200_OK if response.success else status.HTTP_404_NOT_FOUND
        return Response(response_serializer.data, status=status_code)


class RankFundsView(APIView):
    """基金排名 API

    GET /api/fund/rank/?regime=Recovery&max_count=50
    """

    def get(self, request) -> Response:
        """获取基金排名"""
        regime = request.query_params.get('regime', 'Recovery')
        max_count = int(request.query_params.get('max_count', 50))

        # 执行用例
        fund_repo = DjangoFundRepository()
        use_case = RankFundsUseCase(fund_repo)
        fund_scores = use_case.execute(regime, max_count)

        # 序列化响应
        serializer = FundScoreSerializer(fund_scores, many=True)
        return Response({
            'success': True,
            'regime': regime,
            'count': len(fund_scores),
            'funds': serializer.data
        }, status=status.HTTP_200_OK)


class FundInfoView(APIView):
    """基金信息 API

    GET /api/fund/info/{fund_code}/
    """

    def get(self, request, fund_code: str) -> Response:
        """获取基金信息"""
        fund_repo = DjangoFundRepository()
        fund_info = fund_repo.get_fund_info(fund_code)

        if not fund_info:
            return Response(
                {'success': False, 'error': f'基金 {fund_code} 不存在'},
                status=status.HTTP_404_NOT_FOUND
            )

        from .serializers import FundInfoSerializer
        serializer = FundInfoSerializer(fund_info)

        return Response({
            'success': True,
            'fund': serializer.data
        }, status=status.HTTP_200_OK)


class FundNavView(APIView):
    """基金净值 API

    GET /api/fund/nav/{fund_code}/?start_date=&end_date=
    """

    def get(self, request, fund_code: str) -> Response:
        """获取基金净值"""
        from datetime import datetime

        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')

        start_date = None
        end_date = None

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        fund_repo = DjangoFundRepository()
        nav_list = fund_repo.get_fund_nav(fund_code, start_date, end_date)

        if not nav_list:
            return Response(
                {'success': False, 'error': f'基金 {fund_code} 暂无净值数据'},
                status=status.HTTP_404_NOT_FOUND
            )

        from .serializers import FundNetValueSerializer
        serializer = FundNetValueSerializer(nav_list, many=True)

        return Response({
            'success': True,
            'fund_code': fund_code,
            'count': len(nav_list),
            'nav_data': serializer.data
        }, status=status.HTTP_200_OK)


class FundHoldingView(APIView):
    """基金持仓 API

    GET /api/fund/holding/{fund_code}/?report_date=
    """

    def get(self, request, fund_code: str) -> Response:
        """获取基金持仓"""
        from datetime import datetime

        report_date_str = request.query_params.get('report_date')
        report_date = None

        if report_date_str:
            report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()

        fund_repo = DjangoFundRepository()
        holdings = fund_repo.get_fund_holdings(fund_code, report_date)

        if not holdings:
            return Response(
                {'success': False, 'error': f'基金 {fund_code} 暂无持仓数据'},
                status=status.HTTP_404_NOT_FOUND
            )

        from .serializers import FundHoldingSerializer
        serializer = FundHoldingSerializer(holdings, many=True)

        return Response({
            'success': True,
            'fund_code': fund_code,
            'report_date': report_date_str or '最新',
            'count': len(holdings),
            'holdings': serializer.data
        }, status=status.HTTP_200_OK)
