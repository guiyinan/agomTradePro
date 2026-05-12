"""
AgomTradePro Custom Exceptions

Provides standardized exception classes for consistent error handling across the application.
"""

import logging
from typing import Any, Optional, Union

from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class AgomTradeProException(Exception):
    """
    Base exception for all AgomTradePro exceptions.

    All custom exceptions should inherit from this class.
    """

    default_message = "An error occurred"
    default_code = "INTERNAL_ERROR"
    default_status_code = 500

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None
    ):
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.status_code = status_code or self.default_status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result = {
            "error": self.message,
            "code": self.code,
        }
        if self.details:
            result["details"] = self.details
        return result


# ========== Validation Errors ==========

class ValidationError(AgomTradeProException):
    """Raised when input validation fails."""

    default_message = "输入验证失败"
    default_code = "VALIDATION_ERROR"
    default_status_code = 400


class InvalidInputError(ValidationError):
    """Raised when input is invalid."""

    default_message = "输入无效"
    default_code = "INVALID_INPUT"


class MissingRequiredFieldError(ValidationError):
    """Raised when a required field is missing."""

    default_message = "缺少必填字段"
    default_code = "MISSING_REQUIRED_FIELD"


# ========== Authentication & Authorization Errors ==========

class AuthenticationError(AgomTradeProException):
    """Raised when authentication fails."""

    default_message = "认证失败"
    default_code = "AUTHENTICATION_ERROR"
    default_status_code = 401


class AuthorizationError(AgomTradeProException):
    """Raised when user lacks permission."""

    default_message = "权限不足"
    default_code = "AUTHORIZATION_ERROR"
    default_status_code = 403


# ========== Resource Errors ==========

class ResourceNotFoundError(AgomTradeProException):
    """Raised when a requested resource is not found."""

    default_message = "资源不存在"
    default_code = "NOT_FOUND"
    default_status_code = 404


class DuplicateResourceError(AgomTradeProException):
    """Raised when attempting to create a duplicate resource."""

    default_message = "资源已存在"
    default_code = "DUPLICATE_RESOURCE"
    default_status_code = 409


# ========== Business Logic Errors ==========

class BusinessLogicError(AgomTradeProException):
    """Raised when business rules are violated."""

    default_message = "业务逻辑错误"
    default_code = "BUSINESS_LOGIC_ERROR"
    default_status_code = 422


class RegimeNotDeterminedError(BusinessLogicError):
    """Raised when regime cannot be determined."""

    default_message = "无法判定当前 Regime"
    default_code = "REGIME_NOT_DETERMINED"


class SignalValidationError(BusinessLogicError):
    """Raised when signal validation fails."""

    default_message = "信号验证失败"
    default_code = "SIGNAL_VALIDATION_ERROR"


class IneligibleAssetError(BusinessLogicError):
    """Raised when asset is not eligible for investment."""

    default_message = "资产不符合准入条件"
    default_code = "INELIGIBLE_ASSET"


# ========== External Service Errors ==========

class ExternalServiceError(AgomTradeProException):
    """Base exception for external service errors."""

    default_message = "外部服务错误"
    default_code = "EXTERNAL_SERVICE_ERROR"
    default_status_code = 503


class DataFetchError(ExternalServiceError):
    """Raised when data fetch from external source fails."""

    default_message = "数据获取失败"
    default_code = "DATA_FETCH_ERROR"


class AIServiceError(ExternalServiceError):
    """Raised when AI service call fails."""

    default_message = "AI 服务调用失败"
    default_code = "AI_SERVICE_ERROR"


class TushareError(DataFetchError):
    """Raised when Tushare API call fails."""

    default_message = "Tushare API 调用失败"
    default_code = "TUSHARE_ERROR"


class AKShareError(DataFetchError):
    """Raised when AKShare API call fails."""

    default_message = "AKShare API 调用失败"
    default_code = "AKSHARE_ERROR"


# ========== Timeout Errors ==========

class TimeoutError(AgomTradeProException):
    """Raised when an operation times out."""

    default_message = "操作超时"
    default_code = "TIMEOUT"
    default_status_code = 504


# ========== Configuration Errors ==========

class ConfigurationError(AgomTradeProException):
    """Raised when configuration is invalid."""

    default_message = "配置错误"
    default_code = "CONFIGURATION_ERROR"
    default_status_code = 500


class MissingConfigError(ConfigurationError):
    """Raised when required configuration is missing."""

    default_message = "缺少必要配置"
    default_code = "MISSING_CONFIG"


# ========== Data Errors ==========

class InsufficientDataError(BusinessLogicError):
    """Raised when there is insufficient data to perform an operation."""

    default_message = "数据不足，无法执行操作"
    default_code = "INSUFFICIENT_DATA"


class DataValidationError(BusinessLogicError):
    """Raised when data validation fails."""

    default_message = "数据验证失败"
    default_code = "DATA_VALIDATION_ERROR"


# ========== DRF Exception Handler ==========

def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Custom exception handler for Django REST Framework.

    Provides unified error response format for all API exceptions:
    - AgomTradeProException subclasses: use their structured format
    - DRF validation errors: wrap in standard format
    - Other exceptions: pass through to DRF default handler

    Response format:
    {
        "error": "Error message",
        "code": "ERROR_CODE",
        "details": {...}  # Optional
    }

    Args:
        exc: The exception that was raised
        context: DRF context dict containing view, request, etc.

    Returns:
        Response object or None (falls through to default handler)
    """
    # First, let DRF handle the exception to get the standard response
    response = exception_handler(exc, context)

    # Handle AgomTradeProException subclasses
    if isinstance(exc, AgomTradeProException):
        logger.warning(
            f"AgomTradeProException raised: {exc.code} - {exc.message}",
            extra={
                "code": exc.code,
                "status_code": exc.status_code,
                "details": exc.details,
                "view": context.get("view").__class__.__name__ if context.get("view") else None,
            }
        )
        return Response(
            exc.to_dict(),
            status=exc.status_code
        )

    # If DRF already handled it, format the response
    if response is not None:
        # Standardize the error format for DRF exceptions
        error_data = response.data

        # Handle different DRF error formats
        if isinstance(error_data, dict):
            # Check if it's already in our format
            if "error" in error_data and "code" in error_data:
                return response

            # Wrap validation errors
            if "detail" in error_data:
                # Single error message
                return Response(
                    {
                        "error": str(error_data["detail"]),
                        "code": "API_ERROR",
                    },
                    status=response.status_code
                )
            else:
                # Multiple field errors (e.g., serializer validation)
                return Response(
                    {
                        "error": "请求参数验证失败",
                        "code": "VALIDATION_ERROR",
                        "details": error_data,
                    },
                    status=response.status_code
                )
        elif isinstance(error_data, list):
            # List of errors
            return Response(
                {
                    "error": "; ".join(str(e) for e in error_data),
                    "code": "API_ERROR",
                },
                status=response.status_code
            )
        elif isinstance(error_data, str):
            return Response(
                {
                    "error": error_data,
                    "code": "API_ERROR",
                },
                status=response.status_code
            )

        return response

    # Handle Django Http404 (not caught by DRF)
    if isinstance(exc, Http404):
        return Response(
            {
                "error": "资源不存在",
                "code": "NOT_FOUND",
            },
            status=status.HTTP_404_NOT_FOUND
        )

    # For unhandled exceptions, return None to let DRF use default behavior
    # In production, this will result in a 500 error
    logger.exception(
        f"Unhandled exception in API: {type(exc).__name__}: {exc}",
        extra={
            "view": context.get("view").__class__.__name__ if context.get("view") else None,
        }
    )
    return None
