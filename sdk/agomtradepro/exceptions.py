"""
AgomTradePro SDK 异常定义

所有与 API 交互相关的异常类型。
"""

from __future__ import annotations

import re
from typing import Any

_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_UNSAFE_MESSAGE_PATTERN = re.compile(
    r"(?:password|passwd|secret|token|authorization|traceback|select\s+.+\s+from|sqlalchemy)",
    re.IGNORECASE,
)


def _safe_error_code(response: dict[str, Any] | None, default: str) -> str:
    """Return a bounded public error code from an upstream JSON payload."""

    if response is None:
        return default
    raw_code = (
        response.get("code")
        or response.get("error_code")
        or response.get("block_reason_code")
        or response.get("blocked_reason")
    )
    if not isinstance(raw_code, str):
        return default
    normalized = raw_code.strip()
    return normalized.lower() if _ERROR_CODE_PATTERN.fullmatch(normalized) else default


def _safe_error_message(response: dict[str, Any] | None, default: str) -> str:
    """Return a bounded non-sensitive public error message."""

    if response is None:
        return default
    for key in ("message", "error", "detail", "block_reason"):
        value = response.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and len(normalized) <= 240 and not _UNSAFE_MESSAGE_PATTERN.search(normalized):
            return normalized
    return default


class AgomTradeProAPIError(Exception):
    """
    AgomTradePro API 基础异常类

    所有 API 相关异常的基类，包含状态码和响应详情。
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.response = response
        self.code = "api_error"
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message


class AuthenticationError(AgomTradeProAPIError):
    """
    认证失败异常 (401/403)

    当 API Token 无效或过期时抛出。
    """

    def __init__(
        self,
        message: str = "Authentication failed. Please check your API token.",
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=401, response=response)


class RateLimitError(AgomTradeProAPIError):
    """
    请求频率限制异常 (429)

    当请求超过频率限制时抛出。
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please retry later.",
        retry_after: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=429, response=response)
        self.retry_after = retry_after


class ValidationError(AgomTradeProAPIError):
    """
    数据验证失败异常 (400)

    当请求数据不符合验证规则时抛出。
    """

    def __init__(
        self,
        message: str = "Validation failed.",
        errors: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=400, response=response)
        self.errors = errors or {}


class NotFoundError(AgomTradeProAPIError):
    """
    资源未找到异常 (404)

    当请求的资源不存在时抛出。
    """

    def __init__(
        self,
        message: str = "Resource not found.",
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=404, response=response)


class ConflictError(AgomTradeProAPIError):
    """
    资源冲突异常 (409)

    当请求操作与现有资源冲突时抛出（如重复创建）。
    """

    def __init__(
        self,
        message: str = "Resource conflict.",
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=409, response=response)


class ServerError(AgomTradeProAPIError):
    """
    服务器错误异常 (5xx)

    当服务器内部错误时抛出。
    """

    def __init__(
        self,
        message: str = "Internal server error.",
        status_code: int = 500,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response=response)


class ConnectionError(AgomTradeProAPIError):
    """
    网络连接异常

    当无法连接到 API 服务器时抛出。
    """

    def __init__(
        self,
        message: str = "Failed to connect to AgomTradePro server.",
    ) -> None:
        super().__init__(message)
        self.code = "transport_connection_failed"


class TimeoutError(AgomTradeProAPIError):
    """
    请求超时异常

    当 API 请求超时时抛出。
    """

    def __init__(
        self,
        message: str = "Request timed out.",
    ) -> None:
        super().__init__(message)
        self.code = "transport_timeout"


class ConfigurationError(AgomTradeProAPIError):
    """
    配置错误异常

    当客户端配置不正确时抛出。
    """

    def __init__(
        self,
        message: str = "Invalid configuration.",
    ) -> None:
        super().__init__(message)


class UnsupportedFeatureError(AgomTradeProAPIError):
    """
    当前服务端构建不支持的功能异常。

    用于历史兼容入口仍存在，但当前 canonical API / 后端能力并不存在的场景。
    """

    def __init__(
        self,
        message: str = "This feature is not available in the current server build.",
    ) -> None:
        super().__init__(message, status_code=501)


def raise_for_status(status_code: int, response: dict[str, Any] | None = None) -> None:
    """
    根据状态码抛出对应的异常

    Args:
        status_code: HTTP 状态码
        response: 响应数据

    Raises:
        AuthenticationError: 401/403
        ValidationError: 400
        NotFoundError: 404
        ConflictError: 409
        RateLimitError: 429
        ServerError: 5xx
        AgomTradeProAPIError: 其他错误
    """
    if status_code >= 200 and status_code < 300:
        return

    payload = response if isinstance(response, dict) else None
    error_code = _safe_error_code(payload, f"http_{status_code}")
    error_detail = _safe_error_message(payload, f"HTTP {status_code} error")

    if status_code in (401, 403):
        error: AgomTradeProAPIError = AuthenticationError(
            message=error_detail,
            response=response,
        )
    elif status_code == 400:
        error = ValidationError(
            message=error_detail,
            errors=response.get("errors") if response else None,
            response=response,
        )
    elif status_code == 404:
        error = NotFoundError(message=error_detail, response=response)
    elif status_code == 409:
        error = ConflictError(message=error_detail, response=response)
    elif status_code == 429:
        retry_after = response.get("retry_after") if response else None
        error = RateLimitError(message=error_detail, retry_after=retry_after, response=response)
    elif status_code >= 500:
        error = ServerError(message=error_detail, status_code=status_code, response=response)
    else:
        error = AgomTradeProAPIError(
            message=error_detail,
            status_code=status_code,
            response=response,
        )
    error.code = error_code
    raise error
