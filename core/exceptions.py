"""
AgomSAAF Custom Exceptions

Provides standardized exception classes for consistent error handling across the application.
"""

from typing import Optional, Dict, Any


class AgomSAAFException(Exception):
    """
    Base exception for all AgomSAAF exceptions.

    All custom exceptions should inherit from this class.
    """

    default_message = "An error occurred"
    default_code = "INTERNAL_ERROR"
    default_status_code = 500

    def __init__(
        self,
        message: Optional[str] = None,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.status_code = status_code or self.default_status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result = {
            "error": self.message,
            "code": self.code,
        }
        if self.details:
            result["details"] = self.details
        return result


# ========== Validation Errors ==========

class ValidationError(AgomSAAFException):
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

class AuthenticationError(AgomSAAFException):
    """Raised when authentication fails."""

    default_message = "认证失败"
    default_code = "AUTHENTICATION_ERROR"
    default_status_code = 401


class AuthorizationError(AgomSAAFException):
    """Raised when user lacks permission."""

    default_message = "权限不足"
    default_code = "AUTHORIZATION_ERROR"
    default_status_code = 403


# ========== Resource Errors ==========

class ResourceNotFoundError(AgomSAAFException):
    """Raised when a requested resource is not found."""

    default_message = "资源不存在"
    default_code = "NOT_FOUND"
    default_status_code = 404


class DuplicateResourceError(AgomSAAFException):
    """Raised when attempting to create a duplicate resource."""

    default_message = "资源已存在"
    default_code = "DUPLICATE_RESOURCE"
    default_status_code = 409


# ========== Business Logic Errors ==========

class BusinessLogicError(AgomSAAFException):
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

class ExternalServiceError(AgomSAAFException):
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

class TimeoutError(AgomSAAFException):
    """Raised when an operation times out."""

    default_message = "操作超时"
    default_code = "TIMEOUT"
    default_status_code = 504


# ========== Configuration Errors ==========

class ConfigurationError(AgomSAAFException):
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
