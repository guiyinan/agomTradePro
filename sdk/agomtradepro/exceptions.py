"""
AgomTradePro SDK 异常定义

所有与 API 交互相关的异常类型。
"""

from typing import Optional


class AgomTradeProAPIError(Exception):
    """
    AgomTradePro API 基础异常类

    所有 API 相关异常的基类，包含状态码和响应详情。
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[dict] = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.response = response
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
        response: Optional[dict] = None,
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
        retry_after: Optional[int] = None,
        response: Optional[dict] = None,
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
        errors: Optional[dict] = None,
        response: Optional[dict] = None,
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
        response: Optional[dict] = None,
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
        response: Optional[dict] = None,
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
        response: Optional[dict] = None,
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


def raise_for_status(status_code: int, response: Optional[dict] = None) -> None:
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

    error_detail = None
    if response and isinstance(response, dict):
        error_detail = response.get("detail") or response.get("error")

    if status_code in (401, 403):
        raise AuthenticationError(response=response)
    elif status_code == 400:
        raise ValidationError(errors=response.get("errors") if response else None, response=response)
    elif status_code == 404:
        raise NotFoundError(response=response)
    elif status_code == 409:
        raise ConflictError(response=response)
    elif status_code == 429:
        retry_after = response.get("retry_after") if response else None
        raise RateLimitError(retry_after=retry_after, response=response)
    elif status_code >= 500:
        raise ServerError(status_code=status_code, response=response)
    else:
        raise AgomTradeProAPIError(
            message=error_detail or f"HTTP {status_code} error",
            status_code=status_code,
            response=response,
        )
