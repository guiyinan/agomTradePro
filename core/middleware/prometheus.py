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

from django.http import HttpRequest, HttpResponse

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
    - 只记录 /api/ 路径的请求
    - 跳过 /metrics/ 端点本身
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # 跳过非 API 路径和 metrics 端点
        if not request.path.startswith('/api/') or request.path == '/metrics/':
            return self.get_response(request)

        # 记录开始时间
        start_time = time.perf_counter()

        # 执行请求
        response = self.get_response(request)

        # 计算延迟
        duration = time.perf_counter() - start_time

        # 记录指标
        self._record_metrics(request, response, duration)

        return response

    def _record_metrics(
        self,
        request: HttpRequest,
        response: HttpResponse,
        duration: float
    ) -> None:
        """记录 Prometheus 指标"""
        try:
            from core.metrics import (
                api_error_total,
                api_request_latency_seconds,
                api_request_total,
            )

            # 获取视图名称（从 response 或 request）
            view_name = getattr(response, 'view_name', None)
            if not view_name:
                # 尝试从 resolver 获取
                try:
                    resolver_match = request.resolver_match
                    if resolver_match:
                        view_name = resolver_match.view_name or 'unknown'
                        # 简化视图名称（去掉 app 前缀）
                        if '.' in view_name:
                            view_name = view_name.split('.')[-1]
                except Exception:
                    view_name = 'unknown'

            # 标准化端点路径（移除参数）
            endpoint = self._normalize_path(request.path)

            # 记录请求总数
            api_request_total.labels(
                method=request.method,
                endpoint=endpoint,
                status_code=str(response.status_code),
                view_name=view_name,
            ).inc()

            # 记录延迟
            api_request_latency_seconds.labels(
                method=request.method,
                endpoint=endpoint,
                view_name=view_name,
            ).observe(duration)

            # 记录错误（4xx/5xx）
            if response.status_code >= 400:
                error_class = getattr(response, 'error_class', 'http_error')
                api_error_total.labels(
                    method=request.method,
                    endpoint=endpoint,
                    error_class=error_class,
                    status_code=str(response.status_code),
                ).inc()

        except Exception as e:
            # 指标记录失败不应影响业务
            logger.warning(f"Failed to record Prometheus metrics: {e}")

    def _normalize_path(self, path: str) -> str:
        """
        标准化路径（移除 ID 参数）

        示例:
            /api/regime/123/ -> /api/regime/:id/
            /api/signal/?page=2 -> /api/signal/
        """
        import re

        # 移除查询字符串
        path = path.split('?')[0]

        # 替换数字 ID 为 :id 占位符
        path = re.sub(r'/\d+(?=/|$)', '/:id', path)

        # 替换 UUID 为 :uuid 占位符
        path = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)',
            '/:uuid',
            path,
            flags=re.IGNORECASE
        )

        return path


class ResponseViewNameMixin:
    """
    DRF 视图 Mixin，用于添加视图名称到 response

    配合 PrometheusMetricsMiddleware 使用，自动记录视图名称。
    """

    def finalize_response(self, request, response, *args, **kwargs):
        # 添加视图名称到 response
        response.view_name = self.__class__.__name__
        return super().finalize_response(request, response, *args, **kwargs)
