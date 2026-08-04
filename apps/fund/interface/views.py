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

from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import MissingConfigError

from ..application import interface_services, use_cases
from ..application.use_cases import (
    AnalyzeFundStyleRequest,
    CalculateFundPerformanceRequest,
    ScreenFundsRequest,
)
from .serializers import (
    AnalyzeFundStyleRequestSerializer,
    AnalyzeFundStyleResponseSerializer,
    CalculateFundPerformanceRequestSerializer,
    CalculateFundPerformanceResponseSerializer,
    FundHoldingQuerySerializer,
    FundMultiDimScreenRequestSerializer,
    FundNavQuerySerializer,
    FundScoreSerializer,
    RankFundsQuerySerializer,
    ScreenFundsRequestSerializer,
    ScreenFundsResponseSerializer,
)

AnalyzeFundStyleUseCase = use_cases.AnalyzeFundStyleUseCase

# ============================================================================
# 页面视图（前端）
# ============================================================================


@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    基金分析仪表盘页面

    GET /fund/dashboard/
    """
    context = interface_services.build_dashboard_context()
    return render(request, "fund/dashboard.html", context)


class ScreenFundsView(APIView):
    """筛选基金 API

    POST /api/fund/screen/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """筛选基金"""
        # 1. 验证请求
        serializer = ScreenFundsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # 2. 构造请求对象
        screen_request = ScreenFundsRequest(
            regime=data.get("regime"),
            custom_types=data.get("custom_types"),
            custom_styles=data.get("custom_styles"),
            min_scale=data.get("min_scale"),
            max_count=data.get("max_count", 30),
        )

        # 3. 执行用例
        response = interface_services.screen_funds(screen_request)

        # 4. 序列化响应
        response_serializer = ScreenFundsResponseSerializer(instance=cast(Any, response))
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AnalyzeFundStyleView(APIView):
    """分析基金风格 API

    GET /api/fund/style/{fund_code}/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, fund_code: str) -> Response:
        """分析基金风格"""
        # 1. 验证请求
        query_params = {**request.query_params, "fund_code": fund_code}
        serializer = AnalyzeFundStyleRequestSerializer(data=query_params)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": "请求参数无效", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # 2. 构造请求对象
        analyze_request = AnalyzeFundStyleRequest(
            fund_code=data["fund_code"], report_date=data.get("report_date")
        )

        # 3. 执行用例
        response = interface_services.analyze_fund_style(analyze_request)

        # 4. 序列化响应
        response_serializer = AnalyzeFundStyleResponseSerializer(instance=cast(Any, response))
        status_code = status.HTTP_200_OK if response.success else status.HTTP_404_NOT_FOUND
        return Response(response_serializer.data, status=status_code)


class CalculateFundPerformanceView(APIView):
    """计算基金业绩 API

    POST /api/fund/performance/calculate/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """计算基金业绩"""
        # 1. 验证请求
        serializer = CalculateFundPerformanceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": "请求参数无效", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # 2. 构造请求对象
        perf_request = CalculateFundPerformanceRequest(
            fund_code=data["fund_code"], start_date=data["start_date"], end_date=data["end_date"]
        )

        # 3. 执行用例
        response = interface_services.calculate_fund_performance(perf_request)

        # 4. 序列化响应
        response_serializer = CalculateFundPerformanceResponseSerializer(
            instance=cast(Any, response)
        )
        status_code = status.HTTP_200_OK if response.success else status.HTTP_404_NOT_FOUND
        return Response(response_serializer.data, status=status_code)


class RankFundsView(APIView):
    """基金排名 API

    GET /api/fund/rank/?regime=Recovery&max_count=50
    """

    permission_classes = [IsAuthenticated]
    serializer_class = RankFundsQuerySerializer

    def get(self, request: Request) -> Response:
        """获取基金排名"""
        query = RankFundsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        regime = query.validated_data["regime"]
        max_count = query.validated_data["max_count"]

        # 执行用例
        try:
            fund_scores = interface_services.rank_funds(regime, max_count)
        except MissingConfigError:
            return Response(
                {
                    "success": False,
                    "error": "fund_ranking_preferences_unavailable",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # 序列化响应
        serializer = FundScoreSerializer(instance=cast(Any, fund_scores), many=True)
        return Response(
            {
                "success": True,
                "regime": regime,
                "count": len(fund_scores),
                "funds": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class FundScoreView(APIView):
    """Return one computed fund score."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, fund_code: str) -> Response:
        from .serializers import FundScoreQuerySerializer, FundScoreSerializer

        query = FundScoreQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        score = interface_services.get_fund_score(
            fund_code=fund_code,
            regime=query.validated_data["regime"],
            as_of_date=query.validated_data.get("as_of_date"),
        )
        if score is None:
            return Response(
                {"success": False, "error": f"基金 {fund_code} 暂无评分"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "success": True,
                "score": FundScoreSerializer(instance=cast(Any, score)).data,
            }
        )


class FundInfoView(APIView):
    """基金信息 API

    GET /api/fund/info/{fund_code}/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, fund_code: str) -> Response:
        """获取基金信息"""
        fund_info = interface_services.get_fund_info(fund_code)

        if not fund_info:
            return Response(
                {"success": False, "error": f"基金 {fund_code} 不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        from .serializers import FundInfoSerializer

        serializer = FundInfoSerializer(instance=cast(Any, fund_info))

        return Response({"success": True, "fund": serializer.data}, status=status.HTTP_200_OK)


class FundNavView(APIView):
    """基金净值 API

    GET /api/fund/nav/{fund_code}/?start_date=&end_date=
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, fund_code: str) -> Response:
        """获取基金净值"""
        query = FundNavQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start_date = query.validated_data.get("start_date")
        end_date = query.validated_data.get("end_date")

        current_contract: dict[str, object] | None = None
        if start_date is None and end_date is None:
            published_payload = interface_services.get_published_fund_nav_payload(fund_code)
            nav_list = list(published_payload.get("rows") or [])
            current_contract = {
                "publication_id": published_payload.get("publication_id"),
                "published_at": published_payload.get("published_at"),
                "as_of": published_payload.get("as_of"),
                "observed_at": published_payload.get("observed_at"),
                "freshness_status": published_payload.get("freshness_status", "missing"),
                "must_not_use_for_decision": bool(
                    published_payload.get("must_not_use_for_decision", True)
                ),
                "blocked_reason": str(
                    published_payload.get("blocked_reason") or "canonical_publication_missing"
                ),
                "mode": "published",
            }
        else:
            nav_list = interface_services.get_fund_nav(fund_code, start_date, end_date)

        if not nav_list:
            if current_contract is not None and current_contract["must_not_use_for_decision"]:
                return Response(
                    {
                        "success": False,
                        "error": "当前基金净值发布不可用",
                        "fund_code": fund_code,
                        "contract": current_contract,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"success": False, "error": f"基金 {fund_code} 暂无净值数据"},
                status=status.HTTP_404_NOT_FOUND,
            )

        from .serializers import FundNetValueSerializer

        serializer = FundNetValueSerializer(instance=cast(Any, nav_list), many=True)

        response_payload: dict[str, object] = {
            "success": True,
            "fund_code": fund_code,
            "count": len(nav_list),
            "nav_data": serializer.data,
        }
        if current_contract is not None:
            response_payload["contract"] = current_contract
        return Response(
            response_payload,
            status=status.HTTP_200_OK,
        )


class FundHoldingView(APIView):
    """基金持仓 API

    GET /api/fund/holding/{fund_code}/?report_date=
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, fund_code: str) -> Response:
        """获取基金持仓"""
        query = FundHoldingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        report_date = query.validated_data.get("report_date")

        holdings = interface_services.get_fund_holdings(fund_code, report_date)

        if not holdings:
            return Response(
                {"success": False, "error": f"基金 {fund_code} 暂无持仓数据"},
                status=status.HTTP_404_NOT_FOUND,
            )

        from .serializers import FundHoldingSerializer

        serializer = FundHoldingSerializer(instance=cast(Any, holdings), many=True)

        return Response(
            {
                "success": True,
                "fund_code": fund_code,
                "report_date": report_date.isoformat() if report_date else "最新",
                "count": len(holdings),
                "holdings": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# ==================== 多维度筛选 API（通用资产分析框架集成） ====================


class FundMultiDimScreenAPIView(APIView):
    """基金多维度筛选 API

    POST /api/fund/multidim-screen/

    使用通用资产分析框架进行多维度评分筛选。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
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
        request_serializer = FundMultiDimScreenRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        filters = request_serializer.validated_data.get("filters", {})
        context_data = request_serializer.validated_data["context"]
        max_count = request_serializer.validated_data["max_count"]

        try:
            payload = interface_services.screen_funds_multidim(
                filters=filters,
                context_data=context_data,
                max_count=max_count,
            )
            result = payload["result"]
            context = payload["context"]

            return Response(
                {
                    "success": result["success"],
                    "count": result["count"],
                    "context": {
                        "regime": context.current_regime,
                        "policy_level": context.policy_level,
                        "sentiment_index": context.sentiment_index,
                        "active_signals_count": payload["active_signals_count"],
                    },
                    "funds": result["funds"],
                },
                status=status.HTTP_200_OK if result["success"] else status.HTTP_404_NOT_FOUND,
            )

        except Exception:
            return Response(
                {
                    "success": False,
                    "message": "筛选失败，请检查基金筛选条件与宏观上下文",
                    "funds": [],
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
