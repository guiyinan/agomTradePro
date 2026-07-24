"""Policy RSS API views."""

import logging
from typing import Any, cast

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
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


def _queue_rss_fetch(*, source_id: int | None) -> str:
    """Queue one RSS fetch and record monitoring metadata without leaking internals."""
    from ..application.tasks import fetch_rss_sources

    task = fetch_rss_sources.delay(source_id=source_id)
    task_id = getattr(task, "id", None)
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError("RSS fetch task did not return a valid task ID")
    try:
        record_pending_task(
            task_id=task_id,
            task_name="apps.policy.application.tasks.fetch_rss_sources",
            kwargs={"source_id": source_id},
        )
    except Exception:
        logger.exception("RSS fetch queued but task monitoring registration failed")
    return task_id


class RSSSourceConfigViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Any],
):
    """RSS源配置API"""

    serializer_class = RSSSourceConfigSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["category", "is_active", "parser_type"]
    search_fields = ["name", "url"]

    def get_queryset(self) -> Any:
        return rss_api_service.list_rss_source_configs(
            category=self.request.query_params.get("category", ""),
            is_active=self.request.query_params.get("is_active", ""),
            parser_type=self.request.query_params.get("parser_type", ""),
            search=self.request.query_params.get("search", ""),
        )

    def get_object(self) -> Any:
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

    def get_serializer_class(self) -> type[Any]:
        """根据操作选择序列化器"""
        if self.action in {"create", "update", "partial_update"}:
            return cast(type[Any], RSSSourceConfigCreateSerializer)
        return cast(type[Any], RSSSourceConfigSerializer)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = rss_api_service.create_rss_source_config(serializer.validated_data)
        output = RSSSourceConfigSerializer(source, context=self.get_serializer_context())
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
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

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = self.get_object()
        rss_api_service.delete_rss_source_config(source.id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def trigger_fetch(self, request: Request, pk: str | None = None) -> Response:
        """手动触发抓取指定源"""
        from django.conf import settings

        from ..application.tasks import fetch_rss_sources

        source = self.get_object()
        logger.info("Triggering RSS fetch for source ID %s", source.id)

        eager_mode = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
        logger.info("Celery RSS fetch mode - ALWAYS_EAGER=%s", eager_mode)

        if eager_mode:
            logger.info("Running RSS fetch in synchronous eager mode")
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
            except Exception:
                logger.exception("Synchronous RSS fetch failed")
                return Response(
                    {
                        "status": "error",
                        "error": "抓取失败，请查看服务端日志",
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        try:
            task_id = _queue_rss_fetch(source_id=source.id)
            logger.info("RSS fetch task %s queued successfully", task_id)
            return Response(
                {
                    "status": "triggered",
                    "task_id": task_id,
                    "source": source.name,
                }
            )
        except Exception:
            logger.exception("RSS fetch task scheduling failed")
            return Response(
                {
                    "status": "error",
                    "error": "RSS 抓取任务调度失败，请检查任务服务状态",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    @action(detail=False, methods=["post"])
    def fetch_all(self, request: Request) -> Response:
        """抓取所有启用的源"""
        serializer = RSSTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source_id = cast(int | None, serializer.validated_data.get("source_id"))
        try:
            task_id = _queue_rss_fetch(source_id=source_id)
        except Exception:
            logger.exception("RSS fetch-all task scheduling failed")
            return Response(
                {
                    "status": "error",
                    "error": "RSS 抓取任务调度失败，请检查任务服务状态",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "status": "triggered",
                "task_id": task_id,
            }
        )


class RSSFetchLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Any],
):
    """RSS抓取日志API（只读）"""

    serializer_class = RSSFetchLogSerializer
    permission_classes = [IsAdminUser]
    ordering = ["-fetched_at"]

    def get_queryset(self) -> Any:
        """支持通过 source__name 参数过滤"""
        return rss_api_service.list_rss_fetch_logs(
            source_name=self.request.query_params.get("source__name", ""),
            source_id=self.request.query_params.get("source", ""),
            status=self.request.query_params.get("status", ""),
        )

    def get_object(self) -> Any:
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
    viewsets.GenericViewSet[Any],
):
    """政策档位关键词规则API"""

    serializer_class = PolicyLevelKeywordSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["level", "is_active", "category"]
    ordering = ["-weight", "level"]

    def get_queryset(self) -> Any:
        return rss_api_service.list_policy_level_keywords(
            level=self.request.query_params.get("level", ""),
            is_active=self.request.query_params.get("is_active", ""),
            category=self.request.query_params.get("category", ""),
        )

    def get_object(self) -> Any:
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

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        keyword = rss_api_service.create_policy_level_keyword(serializer.validated_data)
        output = PolicyLevelKeywordSerializer(keyword, context=self.get_serializer_context())
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
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

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        keyword = self.get_object()
        rss_api_service.delete_policy_level_keyword(keyword.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
