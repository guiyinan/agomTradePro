"""
结构化日志工具

提供结构化日志格式化器和 trace_id/request_id 追踪功能。
确保关键问题可用 trace_id 在 10 分钟内定位。
"""

import json
import logging
import re
import sys
import threading
import uuid
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from typing import Any

_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_VALID_LOG_LEVELS = frozenset(
    {
        "CRITICAL",
        "DEBUG",
        "ERROR",
        "INFO",
        "NOTSET",
        "WARNING",
    }
)
_SENSITIVE_KEY_SUFFIXES = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "encryption_key",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
    }
)
_REDACTED = "***"


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in _SENSITIVE_KEY_SUFFIXES
    )


def _redact_log_value(
    value: object,
    *,
    depth: int = 0,
    seen: frozenset[int] = frozenset(),
) -> object:
    if depth >= 6:
        return "<max-depth>"
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in seen:
            return "<recursive>"
        next_seen = seen | {object_id}
        return {
            str(key): (
                _REDACTED
                if _is_sensitive_key(key)
                else _redact_log_value(
                    nested_value,
                    depth=depth + 1,
                    seen=next_seen,
                )
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        object_id = id(value)
        if object_id in seen:
            return "<recursive>"
        next_seen = seen | {object_id}
        return [_redact_log_value(item, depth=depth + 1, seen=next_seen) for item in value]
    return value


class StructuredFormatter(logging.Formatter):
    """
    结构化日志格式化器

    输出 JSON 格式的日志，包含：
    - timestamp: ISO 8601 格式时间戳
    - level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
    - logger: logger 名称
    - message: 日志消息
    - module: 模块名
    - function: 函数名
    - line: 行号
    - trace_id: 追踪 ID（如果存在）
    - request_id: 请求 ID（如果存在）
    - extra: 额外字段（如果存在）
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录为 JSON。

        Args:
            record: 日志记录

        Returns:
            JSON 格式的日志字符串
        """
        # 基础日志数据
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName or "<unknown>",
            "line": record.lineno,
            "process": record.process,
            "thread": record.thread,
        }

        # 添加 trace_id（从当前线程获取）
        trace_id = get_trace_id()
        if trace_id:
            log_data["trace_id"] = trace_id

        # 添加 request_id（从 record 属性获取）
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        # 添加异常信息
        if record.exc_info:
            if isinstance(record.exc_info, tuple):
                log_data["exception"] = self.formatException(record.exc_info)
            elif record.exc_info is True:
                current_exc = sys.exc_info()
                if current_exc and current_exc[0] is not None:
                    log_data["exception"] = self.formatException(current_exc)

        # 添加额外字段
        extra_data: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
                "message",
                "asctime",
                "trace_id",
                "request_id",
            }:
                extra_data[key] = _REDACTED if _is_sensitive_key(key) else _redact_log_value(value)

        if extra_data:
            log_data["extra"] = extra_data

        return json.dumps(log_data, ensure_ascii=False, default=str)


class StructuredFormatterVerbose(StructuredFormatter):
    """
    详细版结构化日志格式化器

    除了基础字段外，还包含：
    - path: 代码文件路径
    - thread_name: 线程名称
    - process_name: 进程名称
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录为详细 JSON。

        Args:
            record: 日志记录

        Returns:
            JSON 格式的详细日志字符串
        """
        log_data = json.loads(super().format(record))

        # 添加额外详细信息
        log_data["path"] = record.pathname
        log_data["thread_name"] = record.threadName
        log_data["process_name"] = record.processName

        return json.dumps(log_data, ensure_ascii=False, default=str)


class TraceContextFilter(logging.Filter):
    """
    Ensure log records always have trace context fields required by formatters.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id") or not getattr(record, "trace_id", None):
            record.trace_id = get_trace_id() or "-"
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


# Thread-local storage for trace_id
_thread_local = threading.local()


def get_trace_id() -> str | None:
    """
    获取当前请求的 trace_id。

    Returns:
        当前线程的 trace_id，如果未设置则返回 None
    """
    trace_id = getattr(_thread_local, "trace_id", None)
    return trace_id if isinstance(trace_id, str) and trace_id else None


def set_trace_id(trace_id: str | None = None) -> str:
    """
    设置当前请求的 trace_id。

    Args:
        trace_id: trace_id，如果为 None 则自动生成

    Returns:
        设置的 trace_id
    """
    if trace_id is None:
        # 生成 8 位短 trace_id（适用于单次请求追踪）
        trace_id = str(uuid.uuid4())[:8]
    else:
        trace_id = trace_id.strip()
        if not _TRACE_ID_PATTERN.fullmatch(trace_id):
            raise ValueError("trace_id must contain 1-128 letters, digits, hyphens, or underscores")

    _thread_local.trace_id = trace_id
    return trace_id


def clear_trace_id() -> None:
    """清除当前线程的 trace_id"""
    if hasattr(_thread_local, "trace_id"):
        delattr(_thread_local, "trace_id")


def generate_full_trace_id() -> str:
    """
    生成完整的 trace_id（用于跨服务追踪）。

    Returns:
        完整的 UUID 格式 trace_id
    """
    return str(uuid.uuid4())


class StructuredLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    """
    结构化日志适配器

    为日志自动添加 trace_id/request_id 等上下文信息。

    Example:
        >>> logger = get_structured_logger(__name__)
        >>> logger.info("Processing request", extra={'request_id': 'req-123'})
    """

    def process(
        self,
        msg: object,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[object, MutableMapping[str, Any]]:
        """
        处理日志消息和参数。

        Args:
            msg: 日志消息
            kwargs: 日志参数

        Returns:
            处理后的消息和参数
        """
        processed_kwargs: MutableMapping[str, Any] = dict(kwargs)
        raw_call_extra = processed_kwargs.get("extra")
        if raw_call_extra is None:
            call_extra: dict[str, object] = {}
        elif isinstance(raw_call_extra, Mapping):
            call_extra = {str(key): value for key, value in raw_call_extra.items()}
        else:
            raise TypeError("logging extra must be a mapping")

        bound_extra = {str(key): value for key, value in (self.extra or {}).items()}
        merged_extra = {**bound_extra, **call_extra}

        # 自动添加 trace_id
        trace_id = get_trace_id()
        if trace_id:
            merged_extra["trace_id"] = trace_id

        processed_kwargs["extra"] = merged_extra
        return msg, processed_kwargs


def get_structured_logger(name: str) -> logging.Logger:
    """
    获取结构化日志记录器。

    Args:
        name: logger 名称（通常使用 __name__）

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 如果 logger 还没有 handler，添加一个
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

    return logger


def bind_logger(**kwargs: Any) -> StructuredLoggerAdapter:
    """
    创建一个绑定了额外字段的日志适配器。

    Args:
        **kwargs: 要绑定的字段

    Returns:
        绑定了字段的日志适配器

    Example:
        >>> logger = bind_logger(user_id=123, request_id='abc')
        >>> logger.info("User action")  # 自动包含 user_id 和 request_id
    """
    raw_logger_name = kwargs.pop("logger_name", __name__)
    logger_name = raw_logger_name if isinstance(raw_logger_name, str) else __name__
    base_logger = logging.getLogger(logger_name)
    return StructuredLoggerAdapter(base_logger, dict(kwargs))


# Log level 常量（与标准 logging 模块一致）
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL


def normalize_log_level(value: str | None, default: str = "INFO") -> str:
    """
    标准化日志级别字符串，避免批处理环境变量尾随空格导致 Django 启动失败。

    Args:
        value: 原始日志级别字符串
        default: 兜底日志级别

    Returns:
        去除首尾空格并转为大写后的日志级别；空值时返回默认值
    """
    normalized_default = (default or "INFO").strip().upper()
    if normalized_default not in _VALID_LOG_LEVELS:
        normalized_default = "INFO"
    normalized = (value or "").strip().upper()
    return normalized if normalized in _VALID_LOG_LEVELS else normalized_default
