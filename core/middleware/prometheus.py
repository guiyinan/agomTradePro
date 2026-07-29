"""
Prometheus Metrics Middleware for API Requests

自动记录 API 请求的 Prometheus 指标：
- 请求总数（按方法、端点、状态码分组）
- 请求延迟（按方法、端点分组）
- 错误请求计数（4xx/5xx）

与 django-prometheus 中间件配合使用，提供额外的业务指标记录。
"""

import logging
import time
from collections.abc import Callable
from typing import Any, cast

from django.http import HttpRequest, HttpResponse
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class PrometheusMetricsMiddleware:
    """
    Prometheus 指标中间件

    自动记录所有 API 请求的指标到 Prometheus。

    功能：
    1. 记录请求总数和延迟
    2. 记录错误请求（4xx/5xx）
    3. 提取视图名称作为标签

    注意：
    - 与 django_prometheus.middleware 配合使用
    - API 通用指标只记录 /api/ 路径
    - Web-to-TUI 兼容指标覆盖受审 Classic 路由与 TUI 入口/action
    - 跳过 metrics 端点本身
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path in {"/metrics/", "/api/metrics/"}:
            return self.get_response(request)

        is_api_request = request.path.startswith("/api/")
        start_time = time.perf_counter() if is_api_request else None
        response = self.get_response(request)
        self._record_ui_migration_metrics(request, response)

        if is_api_request and start_time is not None:
            duration = time.perf_counter() - start_time
            self._record_metrics(request, response, duration)

        return response

    @staticmethod
    def _record_ui_migration_metrics(
        request: HttpRequest,
        response: HttpResponse,
    ) -> None:
        """Record one bounded compatibility event when the route is in scope."""

        try:
            from core.metrics import record_web_to_tui_migration_event
            from core.ui_migration_telemetry import classify_ui_migration_request

            event = classify_ui_migration_request(request, response)
            if event is None:
                return
            record_web_to_tui_migration_event(
                surface=event.surface,
                event_type=event.event_type,
                task_key=event.task_key,
                outcome=event.outcome,
            )
        except Exception as exc:
            logger.warning(
                "Failed to record Web-to-TUI migration metrics (error_type=%s)",
                type(exc).__name__,
            )

    def _record_metrics(
        self, request: HttpRequest, response: HttpResponse, duration: float
    ) -> None:
        """记录 Prometheus 指标"""
        try:
            from core.metrics import (
                api_error_total,
                api_request_latency_seconds,
                api_request_total,
            )

            # 获取视图名称（从 response 或 request）
            view_name = getattr(response, "view_name", None)
            if not view_name:
                # 尝试从 resolver 获取
                try:
                    resolver_match = request.resolver_match
                    if resolver_match:
                        view_name = resolver_match.view_name or "unknown"
                        # 简化视图名称（去掉 app 前缀）
                        if "." in view_name:
                            view_name = view_name.split(".")[-1]
                except Exception:
                    view_name = "unknown"

            # 标准化端点路径（移除参数）
            endpoint = self._normalize_path(request.path)

            # 记录请求总数
            normalized_view_name = str(view_name or "unknown")[:128]
            api_request_total.labels(
                method=request.method,
                endpoint=endpoint,
                status_code=str(response.status_code),
                view_name=normalized_view_name,
            ).inc()

            # 记录延迟
            api_request_latency_seconds.labels(
                method=request.method,
                endpoint=endpoint,
                view_name=normalized_view_name,
            ).observe(duration)

            # 记录错误（4xx/5xx）
            if response.status_code >= 400:
                error_class = str(getattr(response, "error_class", "http_error"))[:64]
                api_error_total.labels(
                    method=request.method,
                    endpoint=endpoint,
                    error_class=error_class,
                    status_code=str(response.status_code),
                ).inc()

        except Exception as exc:
            # 指标记录失败不应影响业务
            logger.warning(
                "Failed to record Prometheus metrics (error_type=%s)",
                type(exc).__name__,
            )

    def _normalize_path(self, path: str) -> str:
        """
        标准化路径（移除 ID 参数）

        示例:
            /api/regime/123/ -> /api/regime/:id/
            /api/signal/?page=2 -> /api/signal/
        """
        import re

        # 移除查询字符串
        path = path.split("?")[0]

        # 替换数字 ID 为 :id 占位符
        path = re.sub(r"/\d+(?=/|$)", "/:id", path)

        # 替换 UUID 为 :uuid 占位符
        path = re.sub(
            r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)",
            "/:uuid",
            path,
            flags=re.IGNORECASE,
        )

        return path


class ResponseViewNameMixin:
    """
    DRF 视图 Mixin，用于添加视图名称到 response

    配合 PrometheusMetricsMiddleware 使用，自动记录视图名称。
    """

    def finalize_response(
        self,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        # 添加视图名称到 response
        response.__dict__["view_name"] = self.__class__.__name__
        parent = cast(Any, super())
        return cast(Response, parent.finalize_response(request, response, *args, **kwargs))
