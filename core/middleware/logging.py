"""
日志中间件

为每个请求添加 trace_id 追踪，并在响应头中返回。
支持从请求头传入 trace_id 以实现分布式追踪。
"""

import logging
from typing import Callable

from django.http import HttpRequest, HttpResponse

from core.logging_utils import set_trace_id, clear_trace_id, get_trace_id

logger = logging.getLogger(__name__)


class TraceIDMiddleware:
    """
    为每个 HTTP 请求添加 trace_id 追踪。

    功能：
    1. 从请求头读取 X-Trace-ID 或 X-Request-ID
    2. 如果不存在则自动生成新的 trace_id
    3. 在响应头中返回 X-Trace-ID
    4. 所有日志自动包含 trace_id

    Example:
        客户端请求：
        GET /api/regime/states/
        X-Trace-ID: abc123def

        服务端响应：
        X-Trace-ID: abc123def
    """

    # 支持的请求头名称（优先级从高到低）
    TRACE_ID_HEADERS = [
        'X-Trace-ID',      # 主要追踪 ID
        'X-Request-ID',    # 兼容常见的 request_id header
        'X-Correlation-ID', # 兼容 correlation_id
    ]

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """
        初始化中间件。

        Args:
            get_response: 下一个中间件或视图
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        处理请求并添加 trace_id。

        Args:
            request: HTTP 请求

        Returns:
            带有 X-Trace-ID 响应头的 HTTP 响应
        """
        # 尝试从请求头获取 trace_id
        trace_id = self._get_incoming_trace_id(request)

        # 设置或生成 trace_id
        if trace_id:
            set_trace_id(trace_id)
            logger.debug(f"Using incoming trace_id: {trace_id}")
        else:
            trace_id = set_trace_id()
            logger.debug(f"Generated new trace_id: {trace_id}")

        # 将 trace_id 附加到 request 对象，方便视图访问
        request.trace_id = trace_id

        try:
            # 处理请求
            response = self.get_response(request)

            # 添加 trace_id 到响应头（容错：测试桩可能返回非 HttpResponse 对象）
            if hasattr(response, '__setitem__'):
                response['X-Trace-ID'] = trace_id

            return response
        finally:
            # 清除 thread-local trace_id
            clear_trace_id()

    def _get_incoming_trace_id(self, request: HttpRequest) -> str | None:
        """
        从请求头获取传入的 trace_id。

        Args:
            request: HTTP 请求

        Returns:
            trace_id 或 None
        """
        for header_name in self.TRACE_ID_HEADERS:
            # Django 会将 header 名转换为 HTTP_X_TRACE_ID 格式
            # 但使用 request.headers.get() 可以直接使用原始格式
            trace_id = request.headers.get(header_name)
            if trace_id:
                # 验证 trace_id 格式（可选）
                if self._is_valid_trace_id(trace_id):
                    return trace_id
                else:
                    logger.warning(
                        f"Invalid trace_id format: {trace_id}. "
                        f"Generating new trace_id."
                    )

        return None

    def _is_valid_trace_id(self, trace_id: str) -> bool:
        """
        验证 trace_id 格式。

        允许的格式：
        - UUID (8-4-4-4-12)
        - 短 ID (8-32 字符的字母数字)
        - 已知前缀 + ID

        Args:
            trace_id: 要验证的 trace_id

        Returns:
            是否有效
        """
        if not trace_id or not isinstance(trace_id, str):
            return False

        # 移除可能的前缀
        cleaned = trace_id.strip().strip('"').strip("'")

        # 检查长度（1-128 字符）
        if not 1 <= len(cleaned) <= 128:
            return False

        # 检查是否包含有效的字符（字母、数字、横线、下划线）
        valid_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
        return all(c in valid_chars for c in cleaned)


class RequestLoggingMiddleware:
    """
    请求日志中间件

    记录每个请求的基本信息：
    - 请求方法、路径
    - 响应状态码
    - 处理时间
    - trace_id

    配合 StructuredFormatter 使用时，所有日志都会包含 trace_id。
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """
        初始化中间件。

        Args:
            get_response: 下一个中间件或视图
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        处理请求并记录日志。

        Args:
            request: HTTP 请求

        Returns:
            HTTP 响应
        """
        import time

        # 记录请求开始时间
        start_time = time.time()

        # 获取 trace_id（应该已经被 TraceIDMiddleware 设置）
        trace_id = get_trace_id() or '-'

        # 记录请求开始
        logger.info(
            f"Request started: {request.method} {request.path}",
            extra={
                'request_method': request.method,
                'request_path': request.path,
                'remote_addr': self._get_client_ip(request),
                'user_agent': request.headers.get('User-Agent', '-')[:256],  # 限制长度
            }
        )

        try:
            # 处理请求
            response = self.get_response(request)

            # 计算处理时间
            duration_ms = (time.time() - start_time) * 1000

            # 记录请求完成
            log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
            logger.log(
                log_level,
                f"Request completed: {request.method} {request.path} - "
                f"{response.status_code} ({duration_ms:.0f}ms)",
                extra={
                    'request_method': request.method,
                    'request_path': request.path,
                    'status_code': response.status_code,
                    'duration_ms': round(duration_ms, 2),
                }
            )

            return response

        except Exception as e:
            # 记录请求异常
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(
                f"Request failed: {request.method} {request.path} - "
                f"{type(e).__name__} ({duration_ms:.0f}ms)",
                extra={
                    'request_method': request.method,
                    'request_path': request.path,
                    'error_type': type(e).__name__,
                    'duration_ms': round(duration_ms, 2),
                }
            )
            raise

    def _get_client_ip(self, request: HttpRequest) -> str:
        """
        获取客户端 IP 地址（支持代理）。

        Args:
            request: HTTP 请求

        Returns:
            客户端 IP 地址
        """
        x_forwarded_for = request.headers.get('X-Forwarded-For')
        if x_forwarded_for:
            # X-Forwarded-For 可能包含多个 IP，取第一个
            return x_forwarded_for.split(',')[0].strip()

        x_real_ip = request.headers.get('X-Real-IP')
        if x_real_ip:
            return x_real_ip

        return request.META.get('REMOTE_ADDR', '-')
