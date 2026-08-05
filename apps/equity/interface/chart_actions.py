"""Technical and intraday chart actions for the equity API viewset.

The chart endpoints are kept in their own focused mixin so the analysis
compatibility owner remains bounded.  ``views.py`` composes this mixin
through :class:`EquityAnalysisActionsMixin`; no compatibility-facade import
is allowed here.
"""

from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.use_cases import (
    GetIntradayChartRequest,
    GetIntradayChartUseCase,
    GetTechnicalChartRequest,
    GetTechnicalChartUseCase,
)

from .serializers import (
    IntradayChartRequestSerializer,
    IntradayChartResponseSerializer,
    TechnicalChartRequestSerializer,
    TechnicalChartResponseSerializer,
)
from .valuation_actions import typed_action, typed_schema


class EquityChartActionsMixin:
    """Technical and intraday chart actions."""

    stock_repo: Any

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
                mode=data["mode"],
                publication_key=data["publication_key"],
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


__all__ = ["EquityChartActionsMixin"]
