"""
Sentiment 模块 - Interface 层视图

本模块包含 API 视图和页面视图。
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest
from django.views.generic import TemplateView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sentiment.application.interface_services import (
    analyze_sentiment_batch,
    analyze_sentiment_text,
    clear_sentiment_cache_payload,
    get_recent_sentiment_indices_payload,
    get_sentiment_analyze_page_context,
    get_sentiment_dashboard_context,
    get_sentiment_health_payload,
    get_sentiment_index_payload,
    get_sentiment_index_range_payload,
)

from .serializers import (
    BatchAnalysisRequestSerializer,
    BatchAnalysisResponseSerializer,
    SentimentAnalysisRequestSerializer,
    SentimentAnalysisResponseSerializer,
    SentimentHealthResponseSerializer,
    SentimentIndexListSerializer,
    SentimentIndexQuerySerializer,
    SentimentIndexRangeRequestSerializer,
    SentimentIndexRecentRequestSerializer,
    SentimentIndexSerializer,
)

logger = logging.getLogger(__name__)

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])


def _schema(**kwargs: Any) -> Callable[[ViewMethod], ViewMethod]:
    """Expose drf-spectacular's runtime decorator with its identity type."""

    return cast(Callable[[ViewMethod], ViewMethod], extend_schema(**kwargs))


def _validation_error(serializer: serializers.BaseSerializer[Any]) -> Response:
    """Return the canonical Sentiment request-validation error envelope."""

    return Response(
        {"error": "验证失败", "details": serializer.errors},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _internal_error(*, error: str, error_code: str) -> Response:
    """Return a stable error envelope without exposing exception details."""

    return Response(
        {"error": error, "error_code": error_code},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ============ API Views ============


class SentimentAnalyzeView(APIView):
    """情感分析 API"""

    @_schema(
        summary="分析文本情感",
        description="使用 AI 分析文本的情感倾向，返回评分、分类和关键词",
        request=SentimentAnalysisRequestSerializer,
        responses={
            200: SentimentAnalysisResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "分析请求示例",
                value={"text": "央行宣布降准，市场情绪高涨，股市大涨。"},
            )
        ],
    )
    def post(self, request: HttpRequest) -> Response:
        """分析单条文本的情感"""
        serializer = SentimentAnalysisRequestSerializer(data=cast(Request, request).data)
        if not serializer.is_valid():
            return _validation_error(serializer)

        text = cast(str, serializer.validated_data["text"])
        use_cache = cast(bool, serializer.validated_data["use_cache"])

        try:
            return Response(
                analyze_sentiment_text(
                    text=text,
                    use_cache=use_cache,
                )
            )
        except RuntimeError as exc:
            logger.warning(
                "Sentiment AI service unavailable; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {
                    "error": "Sentiment AI service is unavailable.",
                    "error_code": "SENTIMENT_AI_UNAVAILABLE",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            logger.error(
                "Sentiment analysis failed; exception_type=%s",
                type(exc).__name__,
            )
            return _internal_error(
                error="Sentiment analysis failed.",
                error_code="SENTIMENT_ANALYSIS_FAILED",
            )


class SentimentBatchAnalyzeView(APIView):
    """批量情感分析 API"""

    @_schema(
        summary="批量分析文本情感",
        description="批量分析多条文本的情感，最多支持50条",
        request=BatchAnalysisRequestSerializer,
        responses={
            200: BatchAnalysisResponseSerializer,
            400: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: HttpRequest) -> Response:
        """批量分析文本情感"""
        serializer = BatchAnalysisRequestSerializer(data=cast(Request, request).data)
        if not serializer.is_valid():
            return _validation_error(serializer)

        texts = cast(list[str], serializer.validated_data["texts"])

        try:
            return Response(analyze_sentiment_batch(texts=texts))

        except Exception as exc:
            logger.error(
                "Batch sentiment analysis failed; exception_type=%s",
                type(exc).__name__,
            )
            return _internal_error(
                error="Batch sentiment analysis failed.",
                error_code="SENTIMENT_BATCH_ANALYSIS_FAILED",
            )


class SentimentIndexView(APIView):
    """情绪指数 API"""

    @_schema(
        summary="获取情绪指数",
        description="获取指定日期或最新的情绪指数",
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                required=False,
                description="指定日期 (YYYY-MM-DD)，不传则返回最新",
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: SentimentIndexSerializer,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: HttpRequest) -> Response:
        """获取情绪指数"""
        serializer = SentimentIndexQuerySerializer(data=cast(Request, request).query_params)
        if not serializer.is_valid():
            return _validation_error(serializer)
        target_date = cast(date | None, serializer.validated_data.get("date"))

        try:
            index = get_sentiment_index_payload(target_date)

            if not index:
                return Response({"error": "未找到情绪指数数据"}, status=status.HTTP_404_NOT_FOUND)

            return Response(index)

        except Exception as exc:
            logger.error(
                "Sentiment index query failed; exception_type=%s",
                type(exc).__name__,
            )
            return _internal_error(
                error="Sentiment index query failed.",
                error_code="SENTIMENT_INDEX_QUERY_FAILED",
            )


class SentimentIndexRangeView(APIView):
    """日期范围情绪指数 API"""

    @_schema(
        summary="获取日期范围内的情绪指数",
        description="获取指定日期范围内的所有情绪指数",
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="开始日期 (YYYY-MM-DD)",
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=True,
                description="结束日期 (YYYY-MM-DD)",
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: SentimentIndexListSerializer,
            400: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: HttpRequest) -> Response:
        """获取日期范围内的情绪指数"""
        serializer = SentimentIndexRangeRequestSerializer(data=cast(Request, request).query_params)
        if not serializer.is_valid():
            return _validation_error(serializer)
        start_date = cast(date, serializer.validated_data["start_date"])
        end_date = cast(date, serializer.validated_data["end_date"])

        try:
            return Response(
                get_sentiment_index_range_payload(
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        except Exception as exc:
            logger.error(
                "Sentiment index range query failed; exception_type=%s",
                type(exc).__name__,
            )
            return _internal_error(
                error="Sentiment index range query failed.",
                error_code="SENTIMENT_INDEX_RANGE_QUERY_FAILED",
            )


class SentimentIndexRecentView(APIView):
    """最近 N 天情绪指数 API"""

    @_schema(
        summary="获取最近的情绪指数",
        description="获取最近 N 天的情绪指数列表",
        parameters=[
            OpenApiParameter(
                name="days",
                type=int,
                required=False,
                description="天数，默认30天",
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: SentimentIndexListSerializer,
        },
    )
    def get(self, request: HttpRequest) -> Response:
        """获取最近 N 天的情绪指数"""
        serializer = SentimentIndexRecentRequestSerializer(data=cast(Request, request).query_params)
        if not serializer.is_valid():
            return _validation_error(serializer)
        days = cast(int, serializer.validated_data["days"])
        return Response(get_recent_sentiment_indices_payload(days=days))


class SentimentHealthView(APIView):
    """健康检查 API"""

    @_schema(
        summary="情感分析服务健康检查",
        description="检查情感分析服务的状态，包括 AI 提供商可用性和缓存状态",
        responses={
            200: SentimentHealthResponseSerializer,
        },
    )
    def get(self, request: HttpRequest) -> Response:
        """健康检查"""
        try:
            return Response(get_sentiment_health_payload())

        except Exception as exc:
            logger.error(
                "Sentiment health check failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {
                    "status": "unhealthy",
                    "error": "Sentiment health check failed.",
                    "error_code": "SENTIMENT_HEALTH_CHECK_FAILED",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SentimentCacheClearView(APIView):
    """清除缓存 API"""

    permission_classes = [IsAdminUser]

    @_schema(
        summary="清除情感分析缓存",
        description="清除情感分析缓存，可以清除全部或指定文本的缓存",
        responses={
            200: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: HttpRequest) -> Response:
        """清除缓存"""
        return Response(clear_sentiment_cache_payload())


# ============ HTML Page Views ============


class SentimentDashboardView(LoginRequiredMixin, TemplateView):
    """情感分析仪表盘 - HTML 视图"""

    template_name = "sentiment/dashboard.html"
    login_url = "/account/login/"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        try:
            context.update(get_sentiment_dashboard_context())
        except Exception as exc:
            logger.error(
                "Sentiment dashboard context failed; exception_type=%s",
                type(exc).__name__,
            )
            context["latest_index"] = None
            context["recent_indices"] = []
            context["ai_available"] = False
            context["error"] = "情感分析数据暂时不可用"

        return context


class SentimentAnalyzePageView(LoginRequiredMixin, TemplateView):
    """情感分析页面 - HTML 视图"""

    template_name = "sentiment/analyze.html"
    login_url = "/account/login/"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        try:
            context.update(get_sentiment_analyze_page_context())
        except Exception:
            context["ai_available"] = False

        return context
