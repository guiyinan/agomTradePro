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

from typing import Any, Dict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application import interface_services
from ..application.use_cases import (
    AnalyzeFundStyleRequest,
    AnalyzeFundStyleUseCase,
    CalculateFundPerformanceRequest,
    CalculateFundPerformanceUseCase,
    RankFundsUseCase,
    ScreenFundsRequest,
    ScreenFundsUseCase,
)
from .serializers import (
    AnalyzeFundStyleRequestSerializer,
    AnalyzeFundStyleResponseSerializer,
    CalculateFundPerformanceRequestSerializer,
    CalculateFundPerformanceResponseSerializer,
    FundScoreSerializer,
    ScreenFundsRequestSerializer,
    ScreenFundsResponseSerializer,
)

# ============================================================================
# 页面视图（前端）
# ============================================================================

@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def dashboard_view(request):
    """
    基金分析仪表盘页面

    GET /fund/dashboard/
    """
    context = interface_services.build_dashboard_context()
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
        response = interface_services.screen_funds(screen_request)

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
        response = interface_services.analyze_fund_style(analyze_request)

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
        response = interface_services.calculate_fund_performance(perf_request)

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
        fund_scores = interface_services.rank_funds(regime, max_count)

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
        fund_info = interface_services.get_fund_info(fund_code)

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

        nav_list = interface_services.get_fund_nav(fund_code, start_date, end_date)

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

        holdings = interface_services.get_fund_holdings(fund_code, report_date)

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


# ==================== 多维度筛选 API（通用资产分析框架集成） ====================


class FundMultiDimScreenAPIView(APIView):
    """基金多维度筛选 API

    POST /api/fund/multidim-screen/

    使用通用资产分析框架进行多维度评分筛选。
    """

    def post(self, request) -> Response:
        """
        多维度筛选基金

        请求体：
        {
            "filters": {
                "fund_type": "股票型",
                "investment_style": "成长",
                "min_scale": 1000000000
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

        try:
            payload = interface_services.screen_funds_multidim(
                filters=filters,
                context_data=context_data,
                max_count=max_count,
            )
            result = payload["result"]
            context = payload["context"]

            return Response({
                "success": result["success"],
                "count": result["count"],
                "context": {
                    "regime": context.current_regime,
                    "policy_level": context.policy_level,
                    "sentiment_index": context.sentiment_index,
                    "active_signals_count": payload["active_signals_count"],
                },
                "funds": result["funds"],
            }, status=status.HTTP_200_OK if result["success"] else status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"筛选失败: {str(e)}",
                "funds": [],
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
