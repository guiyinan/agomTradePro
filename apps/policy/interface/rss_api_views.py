"""Policy RSS API views."""

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..infrastructure.models import (
    PolicyLevelKeywordModel,
    RSSFetchLog,
    RSSSourceConfigModel,
)
from .serializers import (
    PolicyLevelKeywordSerializer,
    RSSFetchLogSerializer,
    RSSSourceConfigCreateSerializer,
    RSSSourceConfigSerializer,
    RSSTriggerSerializer,
)

logger = logging.getLogger(__name__)

class RSSSourceConfigViewSet(viewsets.ModelViewSet):
    """RSS源配置API"""

    queryset = RSSSourceConfigModel._default_manager.all()
    serializer_class = RSSSourceConfigSerializer
    filterset_fields = ['category', 'is_active', 'parser_type']
    search_fields = ['name', 'url']

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'create':
            return RSSSourceConfigCreateSerializer
        return RSSSourceConfigSerializer

    @action(detail=True, methods=['post'])
    def trigger_fetch(self, request, pk=None):
        """手动触发抓取指定源"""
        try:
            from django.conf import settings

            from ..application.tasks import fetch_rss_sources

            source = self.get_object()
            logger.info(f"Triggering RSS fetch for source: {source.name} (ID: {source.id})")

            # 调试：检查 Celery 配置
            eager_mode = getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False)
            broker_url = getattr(settings, 'CELERY_BROKER_URL', 'not set')
            logger.info(f"Celery config - ALWAYS_EAGER={eager_mode}, BROKER_URL={broker_url}")

            # 检查是否为同步模式（开发环境无 Redis）
            if eager_mode:
                # 同步执行模式
                logger.info("Running in synchronous mode (CELERY_TASK_ALWAYS_EAGER=True)")
                try:
                    result = fetch_rss_sources(source_id=source.id)
                    return Response({
                        'status': 'completed',
                        'result': result,
                        'source': source.name,
                        'message': '抓取已完成（同步模式）'
                    })
                except Exception as sync_error:
                    logger.error(f"Synchronous fetch failed: {sync_error}", exc_info=True)
                    return Response({
                        'status': 'error',
                        'error': f'抓取失败: {str(sync_error)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                # 异步执行模式（需要 Celery worker）
                try:
                    task = fetch_rss_sources.delay(source_id=source.id)
                    logger.info(f"Task {task.id} queued successfully")
                    return Response({
                        'status': 'triggered',
                        'task_id': task.id,
                        'source': source.name
                    })
                except Exception as celery_error:
                    logger.error(f"Celery task failed: {celery_error}", exc_info=True)
                    return Response({
                        'status': 'error',
                        'error': f'Celery任务调度失败: {str(celery_error)}. 请确保Celery worker正在运行.'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        except Exception as e:
            logger.error(f"Failed to trigger RSS fetch: {e}", exc_info=True)
            return Response({
                'status': 'error',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def fetch_all(self, request):
        """抓取所有启用的源"""
        from ..application.tasks import fetch_rss_sources

        serializer = RSSTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task = fetch_rss_sources.delay(
            source_id=serializer.validated_data.get('source_id'),
        )

        return Response({
            'status': 'triggered',
            'task_id': task.id
        })

class RSSFetchLogViewSet(viewsets.ReadOnlyModelViewSet):
    """RSS抓取日志API（只读）"""

    queryset = RSSFetchLog._default_manager.all()
    serializer_class = RSSFetchLogSerializer
    filterset_fields = ['source', 'status']
    ordering = ['-fetched_at']

    def get_queryset(self):
        """支持通过 source__name 参数过滤"""
        queryset = super().get_queryset()
        source_name = self.request.query_params.get('source__name')
        source_id = self.request.query_params.get('source')

        if source_name:
            queryset = queryset.filter(source__name=source_name)
        elif source_id:
            queryset = queryset.filter(source_id=source_id)

        return queryset.select_related('source')

class PolicyLevelKeywordViewSet(viewsets.ModelViewSet):
    """政策档位关键词规则API"""

    queryset = PolicyLevelKeywordModel._default_manager.all()
    serializer_class = PolicyLevelKeywordSerializer
    filterset_fields = ['level', 'is_active', 'category']
    ordering = ['-weight', 'level']

