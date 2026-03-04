"""
Exception Handling Utilities

提供统一的异常处理工具函数和装饰器，用于规范异常处理模式。
"""

import logging
import functools
from typing import Callable, TypeVar, Optional, Any, Type
from contextlib import contextmanager

from core.exceptions import (
    AgomSAAFException,
    ExternalServiceError,
    DataFetchError,
    TimeoutError as AppTimeoutError,
)
from core.metrics import record_exception

logger = logging.getLogger(__name__)

T = TypeVar('T')


def handle_external_service_errors(
    service_name: str,
    default_value: Any = None,
    raise_on_error: bool = False,
) -> Callable:
    """
    外部服务调用错误处理装饰器

    自动捕获外部服务调用的常见异常，并转换为标准的业务异常。

    Args:
        service_name: 外部服务名称（用于日志和指标）
        default_value: 发生错误时的默认返回值
        raise_on_error: 是否在错误时抛出异常（False 则返回 default_value）

    Usage:
        @handle_external_service_errors("Tushare", default_value=None)
        def fetch_stock_data(code: str):
            return ts.pro_api(...)

        @handle_external_service_errors("OpenAI", raise_on_error=True)
        def generate_prompt(prompt: str):
            return openai.ChatCompletion.create(...)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except AppTimeoutError as e:
                # 已知的应用层超时
                logger.warning(
                    f"{service_name} timeout: {e}",
                    extra={"service": service_name, "error_type": "timeout"}
                )
                record_exception(e, module=func.__module__, is_handled=True, service_name=service_name)
                if raise_on_error:
                    raise
                return default_value
            except Exception as e:
                # 检查是否是超时相关异常
                error_str = str(e).lower()
                is_timeout = any(keyword in error_str for keyword in ['timeout', 'timed out'])

                if is_timeout:
                    logger.warning(
                        f"{service_name} operation timed out: {e}",
                        extra={"service": service_name, "error_type": "timeout"}
                    )
                    exc = AppTimeoutError(f"{service_name} operation timed out")
                else:
                    logger.exception(
                        f"{service_name} error: {e}",
                        extra={"service": service_name, "error_type": "unknown"}
                    )
                    exc = ExternalServiceError(f"{service_name} error: {e}")

                record_exception(exc, module=func.__module__, is_handled=True, service_name=service_name)

                if raise_on_error:
                    raise exc from e
                return default_value

        return wrapper
    return decorator


def handle_repository_errors(
    repository_name: str,
    default_value: Any = None,
) -> Callable:
    """
    数据仓储错误处理装饰器

    自动捕获数据库操作的常见异常。

    Args:
        repository_name: 仓储名称（用于日志）
        default_value: 发生错误时的默认返回值

    Usage:
        @handle_repository_errors("RegimeRepository", default_value=None)
        def get_latest_regime(self):
            return Regime.objects.latest('observed_at')
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e).lower()

                # 检查是否是"不存在"类错误
                is_not_found = any(keyword in error_str for keyword in ['doesnotexist', 'not found'])

                if is_not_found:
                    logger.debug(
                        f"{repository_name}: resource not found",
                        extra={"repository": repository_name}
                    )
                    return default_value

                # 其他错误
                logger.exception(
                    f"{repository_name} error: {e}",
                    extra={"repository": repository_name}
                )
                record_exception(e, module=func.__module__, is_handled=True)

                if default_value is not None:
                    return default_value
                raise DataFetchError(f"Failed to fetch from {repository_name}") from e

        return wrapper
    return decorator


@contextmanager
def exception_context(
    operation_name: str,
    module: str,
    reraise: Type[Exception] = None,
):
    """
    异常处理上下文管理器

    自动记录异常指标，并可选择重新抛出特定类型的异常。

    Args:
        operation_name: 操作名称（用于日志）
        module: 模块名称
        reraise: 重新抛出的异常类型（None 表示不重新抛出）

    Usage:
        with exception_context("calculate_regime", "apps.regime"):
            result = complex_calculation()

        with exception_context("fetch_data", "apps.macro", reraise=DataFetchError):
            data = external_api_call()
    """
    try:
        yield
    except Exception as e:
        logger.exception(
            f"{operation_name} failed: {e}",
            extra={"operation": operation_name, "module": module}
        )
        record_exception(e, module=module, is_handled=True)

        if reraise and isinstance(e, reraise):
            raise
        elif reraise:
            # 转换为指定异常类型
            raise reraise(str(e)) from e


def safe_execute(
    func: Callable[..., T],
    default_value: T,
    log_error: bool = True,
    exception_types: tuple = (Exception,),
) -> T:
    """
    安全执行函数，捕获所有异常并返回默认值

    Args:
        func: 要执行的函数
        default_value: 发生异常时的默认返回值
        log_error: 是否记录错误日志
        exception_types: 要捕获的异常类型

    Returns:
        函数执行结果或默认值

    Usage:
        result = safe_execute(
            lambda: risky_operation(),
            default_value=[],
            log_error=True
        )
    """
    try:
        return func()
    except exception_types as e:
        if log_error:
            logger.error(
                f"Safe execution failed for {func.__name__}: {e}",
                extra={"function": func.__name__}
            )
            record_exception(e, module=func.__module__, is_handled=True)
        return default_value


def validate_and_execute(
    validator: Callable,
    error_message: str,
    exception_type: Type[AgomSAAFException] = None,
):
    """
    验证并执行装饰器

    先执行验证函数，验证失败时抛出指定异常。

    Args:
        validator: 验证函数，返回 (is_valid, error_msg)
        error_message: 基础错误消息
        exception_type: 验证失败时抛出的异常类型

    Usage:
        @validate_and_execute(
            validator=lambda x: isinstance(x, str) and len(x) > 0,
            error_message="Asset code must be non-empty string",
            exception_type=InvalidInputError
        )
        def process_asset(asset_code: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # 执行验证
            if validator(*args, **kwargs):
                return func(*args, **kwargs)

            # 验证失败
            if exception_type:
                raise exception_type(error_message)
            raise ValueError(error_message)

        return wrapper
    return decorator


class ExceptionRecorder:
    """
    异常记录器类

    用于自动记录异常指标和日志的上下文管理器。

    Usage:
        with ExceptionRecorder("my_operation", "apps.myapp"):
            risky_operation()
    """

    def __init__(self, operation_name: str, module: str, service_name: str = None):
        self.operation_name = operation_name
        self.module = module
        self.service_name = service_name
        self.exception_occurred = False
        self.exception_type = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.exception_occurred = True
            self.exception_type = exc_type.__name__

            logger.exception(
                f"{self.operation_name} raised {self.exception_type}: {exc_val}",
                extra={
                    "operation": self.operation_name,
                    "module": self.module,
                    "service": self.service_name,
                }
            )

            record_exception(
                exc_val,
                module=self.module,
                is_handled=True,
                service_name=self.service_name,
            )

        # 不抑制异常
        return False


def retry_on_exception(
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    exception_types: tuple = (ExternalServiceError,),
    on_retry: Callable = None,
):
    """
    异常重试装饰器

    Args:
        max_retries: 最大重试次数
        backoff_factor: 退避因子（每次重试等待时间 = backoff_factor * (2 ** retry_count)）
        exception_types: 触发重试的异常类型
        on_retry: 重试时的回调函数

    Usage:
        @retry_on_exception(max_retries=3, exception_types=(ExternalServiceError,))
        def fetch_external_data():
            return api.call()
    """
    import time

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exception_types as e:
                    last_exception = e

                    if attempt < max_retries:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {wait_time}s..."
                        )

                        if on_retry:
                            on_retry(attempt + 1, e)

                        time.sleep(wait_time)
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {e}"
                        )
                        record_exception(e, module=func.__module__, is_handled=True)

            # 重试次数用尽
            raise last_exception

        return wrapper
    return decorator
