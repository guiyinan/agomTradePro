"""
Sentiment 模块 - Interface 层视图

本模块包含 API 视图和页面视图。
"""

import logging
from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import status
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
    SentimentIndexSerializer,
)

logger = logging.getLogger(__name__)


# ============ API Views ============

class SentimentAnalyzeView(APIView):
    """情感分析 API"""

    @extend_schema(
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
        ]
    )
    def post(self, request):
        """分析单条文本的情感"""
        serializer = SentimentAnalysisRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': '验证失败', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        text = serializer.validated_data['text']
        use_cache = serializer.validated_data.get('use_cache', True)

        try:
            return Response(
                analyze_sentiment_text(
                    text=text,
                    use_cache=use_cache,
                )
            )
        except RuntimeError as e:
            logger.error(f"AI 服务不可用: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except Exception as e:
            logger.error(f"情感分析失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentimentBatchAnalyzeView(APIView):
    """批量情感分析 API"""

    @extend_schema(
        summary="批量分析文本情感",
        description="批量分析多条文本的情感，最多支持50条",
        request=BatchAnalysisRequestSerializer,
        responses={
            200: BatchAnalysisResponseSerializer,
            400: OpenApiTypes.OBJECT,
        }
    )
    def post(self, request):
        """批量分析文本情感"""
        serializer = BatchAnalysisRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': '验证失败', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        texts = serializer.validated_data['texts']

        try:
            return Response(analyze_sentiment_batch(texts=texts))

        except Exception as e:
            logger.error(f"批量分析失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentimentIndexView(APIView):
    """情绪指数 API"""

    @extend_schema(
        summary="获取情绪指数",
        description="获取指定日期或最新的情绪指数",
        parameters=[
            OpenApiParameter(
                name='date',
                type=str,
                required=False,
                description='指定日期 (YYYY-MM-DD)，不传则返回最新',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: SentimentIndexSerializer,
            404: OpenApiTypes.OBJECT,
        }
    )
    def get(self, request):
        """获取情绪指数"""
        target_date = request.query_params.get('date')

        try:
            if target_date:
                target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
            index = get_sentiment_index_payload(target_date)

            if not index:
                return Response(
                    {'error': '未找到情绪指数数据'},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response(index)

        except ValueError:
            return Response(
                {'error': '日期格式错误，应为 YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"获取情绪指数失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentimentIndexRangeView(APIView):
    """日期范围情绪指数 API"""

    @extend_schema(
        summary="获取日期范围内的情绪指数",
        description="获取指定日期范围内的所有情绪指数",
        parameters=[
            OpenApiParameter(
                name='start_date',
                type=str,
                required=True,
                description='开始日期 (YYYY-MM-DD)',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='end_date',
                type=str,
                required=True,
                description='结束日期 (YYYY-MM-DD)',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: SentimentIndexListSerializer,
            400: OpenApiTypes.OBJECT,
        }
    )
    def get(self, request):
        """获取日期范围内的情绪指数"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not start_date or not end_date:
            return Response(
                {'error': '必须提供 start_date 和 end_date'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            return Response(
                get_sentiment_index_range_payload(
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        except ValueError:
            return Response(
                {'error': '日期格式错误，应为 YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"获取范围情绪指数失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentimentIndexRecentView(APIView):
    """最近 N 天情绪指数 API"""

    @extend_schema(
        summary="获取最近的情绪指数",
        description="获取最近 N 天的情绪指数列表",
        parameters=[
            OpenApiParameter(
                name='days',
                type=int,
                required=False,
                description='天数，默认30天',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: SentimentIndexListSerializer,
        }
    )
    def get(self, request):
        """获取最近 N 天的情绪指数"""
        days = request.query_params.get('days', 30)
        try:
            days = int(days)
            if days < 1 or days > 365:
                days = 30
        except ValueError:
            days = 30

        return Response(get_recent_sentiment_indices_payload(days=days))


class SentimentHealthView(APIView):
    """健康检查 API"""

    @extend_schema(
        summary="情感分析服务健康检查",
        description="检查情感分析服务的状态，包括 AI 提供商可用性和缓存状态",
        responses={
            200: SentimentHealthResponseSerializer,
        }
    )
    def get(self, request):
        """健康检查"""
        try:
            return Response(get_sentiment_health_payload())

        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return Response({
                'status': 'unhealthy',
                'error': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SentimentCacheClearView(APIView):
    """清除缓存 API"""

    @extend_schema(
        summary="清除情感分析缓存",
        description="清除情感分析缓存，可以清除全部或指定文本的缓存",
        responses={
            200: OpenApiTypes.OBJECT,
        }
    )
    def post(self, request):
        """清除缓存"""
        return Response(clear_sentiment_cache_payload())


# ============ HTML Page Views ============

class SentimentDashboardView(LoginRequiredMixin, TemplateView):
    """情感分析仪表盘 - HTML 视图"""
    template_name = 'sentiment/dashboard.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            context.update(get_sentiment_dashboard_context())
        except Exception as e:
            logger.error(f"获取情感分析数据失败: {e}")
            context['latest_index'] = None
            context['recent_indices'] = []
            context['ai_available'] = False
            context['error'] = str(e)

        return context


class SentimentAnalyzePageView(LoginRequiredMixin, TemplateView):
    """情感分析页面 - HTML 视图"""
    template_name = 'sentiment/analyze.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            context.update(get_sentiment_analyze_page_context())
        except Exception:
            context['ai_available'] = False

        return context
