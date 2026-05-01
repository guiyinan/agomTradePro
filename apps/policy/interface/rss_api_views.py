"""Policy RSS API views."""

import logging

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.task_monitor.application.tracking import record_pending_task

from ..application.repository_provider import get_policy_rss_api_interface_service
from .serializers import (
    PolicyLevelKeywordSerializer,
    RSSFetchLogSerializer,
    RSSSourceConfigCreateSerializer,
    RSSSourceConfigSerializer,
    RSSTriggerSerializer,
)

logger = logging.getLogger(__name__)
rss_api_service = get_policy_rss_api_interface_service()


class RSSSourceConfigViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """RSS源配置API"""

    serializer_class = RSSSourceConfigSerializer
    filterset_fields = ["category", "is_active", "parser_type"]
    search_fields = ["name", "url"]

    def get_queryset(self):
        return rss_api_service.list_rss_source_configs(
            category=self.request.query_params.get("category", ""),
            is_active=self.request.query_params.get("is_active", ""),
            parser_type=self.request.query_params.get("parser_type", ""),
            search=self.request.query_params.get("search", ""),
        )

    def get_object(self):
        raw_id = self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        try:
            source_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise NotFound("RSS source not found.") from exc

        source = rss_api_service.get_rss_source_config(source_id)
        if source is None:
            raise NotFound("RSS source not found.")
        self.check_object_permissions(self.request, source)
        return source

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action in {"create", "update", "partial_update"}:
            return RSSSourceConfigCreateSerializer
        return RSSSourceConfigSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = rss_api_service.create_rss_source_config(serializer.validated_data)
        output = RSSSourceConfigSerializer(source, context=self.get_serializer_context())
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        source = self.get_object()
        serializer = self.get_serializer(source, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_source = rss_api_service.update_rss_source_config(
            source.id,
            serializer.validated_data,
        )
        output = RSSSourceConfigSerializer(
            updated_source,
            context=self.get_serializer_context(),
        )
        return Response(output.data)

    def destroy(self, request, *args, **kwargs):
        source = self.get_object()
        rss_api_service.delete_rss_source_config(source.id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def trigger_fetch(self, request, pk=None):
        """手动触发抓取指定源"""
        try:
            from django.conf import settings

            from ..application.tasks import fetch_rss_sources

            source = self.get_object()
            logger.info(f"Triggering RSS fetch for source: {source.name} (ID: {source.id})")

            eager_mode = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
            broker_url = getattr(settings, "CELERY_BROKER_URL", "not set")
            logger.info(f"Celery config - ALWAYS_EAGER={eager_mode}, BROKER_URL={broker_url}")

            if eager_mode:
                logger.info("Running in synchronous mode (CELERY_TASK_ALWAYS_EAGER=True)")
                try:
                    result = fetch_rss_sources(source_id=source.id)
                    return Response(
                        {
                            "status": "completed",
                            "result": result,
                            "source": source.name,
                            "message": "抓取已完成（同步模式）",
                        }
                    )
                except Exception as sync_error:
                    logger.error(f"Synchronous fetch failed: {sync_error}", exc_info=True)
                    return Response(
                        {
                            "status": "error",
                            "error": f"抓取失败: {str(sync_error)}",
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            try:
                task = fetch_rss_sources.delay(source_id=source.id)
                record_pending_task(
                    task_id=task.id,
                    task_name="apps.policy.application.tasks.fetch_rss_sources",
                    kwargs={"source_id": source.id},
                )
                logger.info(f"Task {task.id} queued successfully")
                return Response(
                    {
                        "status": "triggered",
                        "task_id": task.id,
                        "source": source.name,
                    }
                )
            except Exception as celery_error:
                logger.error(f"Celery task failed: {celery_error}", exc_info=True)
                return Response(
                    {
                        "status": "error",
                        "error": (
                            f"Celery任务调度失败: {str(celery_error)}. "
                            "请确保Celery worker正在运行."
                        ),
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        except Exception as exc:
            logger.error(f"Failed to trigger RSS fetch: {exc}", exc_info=True)
            return Response(
                {
                    "status": "error",
                    "error": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def fetch_all(self, request):
        """抓取所有启用的源"""
        from ..application.tasks import fetch_rss_sources

        serializer = RSSTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task = fetch_rss_sources.delay(
            source_id=serializer.validated_data.get("source_id"),
        )
        record_pending_task(
            task_id=task.id,
            task_name="apps.policy.application.tasks.fetch_rss_sources",
            kwargs={"source_id": serializer.validated_data.get("source_id")},
        )

        return Response(
            {
                "status": "triggered",
                "task_id": task.id,
            }
        )


class RSSFetchLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """RSS抓取日志API（只读）"""

    serializer_class = RSSFetchLogSerializer
    ordering = ["-fetched_at"]

    def get_queryset(self):
        """支持通过 source__name 参数过滤"""
        return rss_api_service.list_rss_fetch_logs(
            source_name=self.request.query_params.get("source__name", ""),
            source_id=self.request.query_params.get("source", ""),
            status=self.request.query_params.get("status", ""),
        )

    def get_object(self):
        raw_id = self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        try:
            log_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise NotFound("RSS fetch log not found.") from exc

        fetch_log = rss_api_service.get_rss_fetch_log(log_id)
        if fetch_log is None:
            raise NotFound("RSS fetch log not found.")
        self.check_object_permissions(self.request, fetch_log)
        return fetch_log


class PolicyLevelKeywordViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """政策档位关键词规则API"""

    serializer_class = PolicyLevelKeywordSerializer
    filterset_fields = ["level", "is_active", "category"]
    ordering = ["-weight", "level"]

    def get_queryset(self):
        return rss_api_service.list_policy_level_keywords(
            level=self.request.query_params.get("level", ""),
            is_active=self.request.query_params.get("is_active", ""),
            category=self.request.query_params.get("category", ""),
        )

    def get_object(self):
        raw_id = self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        try:
            keyword_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise NotFound("Policy keyword not found.") from exc

        keyword = rss_api_service.get_policy_level_keyword(keyword_id)
        if keyword is None:
            raise NotFound("Policy keyword not found.")
        self.check_object_permissions(self.request, keyword)
        return keyword

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        keyword = rss_api_service.create_policy_level_keyword(serializer.validated_data)
        output = PolicyLevelKeywordSerializer(keyword, context=self.get_serializer_context())
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        keyword = self.get_object()
        serializer = self.get_serializer(keyword, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_keyword = rss_api_service.update_policy_level_keyword(
            keyword.id,
            serializer.validated_data,
        )
        output = PolicyLevelKeywordSerializer(
            updated_keyword,
            context=self.get_serializer_context(),
        )
        return Response(output.data)

    def destroy(self, request, *args, **kwargs):
        keyword = self.get_object()
        rss_api_service.delete_policy_level_keyword(keyword.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
