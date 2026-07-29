"""
Trace Logging Service.

为 AgentRuntime 提供执行追踪和审计日志记录。
"""

import json
import logging
import math
import re
from collections.abc import Sequence
from itertools import islice
from typing import Any, Protocol

from ..domain.agent_entities import (
    AgentExecutionRequest,
    AgentExecutionResponse,
    ToolCallRecord,
)

logger = logging.getLogger(__name__)

_TRACE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key|authorization|cookie|credential)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_TRACE_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_TRACE_CREDENTIAL_URL_PATTERN = re.compile(
    r"(?i)\b(https?|postgres(?:ql)?|redis)://[^\s/@:]+:[^\s/@]+@"
)
_TRACE_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "private_key",
        "secret",
        "session",
        "session_id",
        "token",
    }
)


def _safe_trace_text(value: str | None, max_length: int) -> str:
    """Redact common credential forms from optional trace text."""

    if not value:
        return ""
    redacted = _TRACE_CREDENTIAL_URL_PATTERN.sub(r"\1://***@", value)
    redacted = _TRACE_BEARER_PATTERN.sub("Bearer ***", redacted)
    redacted = _TRACE_SECRET_PATTERN.sub(r"\1=***", redacted)
    if len(redacted) > max_length:
        suffix = "...[truncated]"
        return f"{redacted[: max(0, max_length - len(suffix))]}{suffix}"
    return redacted


def _trace_sensitive_key(value: str) -> bool:
    """Return whether a trace metadata key conventionally carries credentials."""

    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized in _TRACE_SENSITIVE_KEYS or normalized.endswith(
        ("_password", "_secret", "_token", "_credential")
    )


def _safe_trace_value(value: object, *, depth: int = 0) -> object:
    """Detach and redact bounded JSON-like trace metadata."""

    if depth > 20:
        return "[truncated]"
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[non_finite_number]"
    if isinstance(value, str):
        return _safe_trace_text(value, 10_000)
    if isinstance(value, dict):
        return {
            str(key)[:200]: (
                "***"
                if _trace_sensitive_key(str(key))
                else _safe_trace_value(item, depth=depth + 1)
            )
            for key, item in islice(value.items(), 1_000)
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_safe_trace_value(item, depth=depth + 1) for item in islice(value, 1_000)]
    return f"[{type(value).__name__}]"


class ExecutionLogWriter(Protocol):
    """Persistence boundary used by the optional Agent trace logger."""

    def create_log(self, log_data: dict[str, Any]) -> object:
        """Persist one execution evidence record."""


class AgentExecutionLogger:
    """
    Agent 执行日志记录器。

    记录每次 AgentRuntime 执行的完整 trace，包括：
    - 执行请求参数
    - 上下文域使用情况
    - 工具调用轨迹
    - 每轮模型输入输出摘要
    - token、耗时、错误
    """

    def __init__(self, execution_log_repository: ExecutionLogWriter | None = None) -> None:
        """
        Args:
            execution_log_repository: 执行日志仓储
        """
        self._repo = execution_log_repository

    def log_agent_execution(
        self,
        request: AgentExecutionRequest,
        response: AgentExecutionResponse,
    ) -> None:
        """
        记录 Agent 执行日志。

        Args:
            request: 执行请求
            response: 执行响应
        """
        execution_id = _safe_trace_text(response.execution_id, 100) or "unknown"
        # 构建 trace 元数据（存入 parsed_output JSON 字段）
        trace_meta = {
            "task_type": _safe_trace_text(request.task_type, 100),
            "session_id": "***" if request.session_id else None,
            "turn_count": response.turn_count,
            "used_context": _safe_trace_value(response.used_context or []),
            "tool_calls": json.loads(self._serialize_tool_calls(response.tool_calls) or "[]"),
            "structured_output": _safe_trace_value(response.structured_output),
        }

        # 映射到 PromptExecutionLogORM 字段
        log_data = {
            "execution_id": execution_id,
            "rendered_prompt": _safe_trace_text(request.user_input, 5_000),
            "ai_response": _safe_trace_text(response.final_answer, 5_000),
            "parsed_output": trace_meta,
            "placeholder_values": {
                "context_scope": _safe_trace_value(request.context_scope or []),
                "tool_names": _safe_trace_value(request.tool_names or []),
                "context_params": _safe_trace_value(request.context_params or {}),
            },
            "provider_used": _safe_trace_text(response.provider_used, 50),
            "model_used": _safe_trace_text(response.model_used, 50),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "estimated_cost": response.estimated_cost or 0,
            "response_time_ms": response.response_time_ms,
            "status": "success" if response.success else "error",
            "error_message": "" if response.success else "prompt_agent_execution_failed",
        }

        # 记录到标准 logger
        if response.success:
            logger.info(
                "Agent execution [%s] completed: turns=%d, tokens=%d, tools=%d, time=%dms",
                execution_id,
                response.turn_count,
                response.total_tokens,
                len(response.tool_calls) if response.tool_calls else 0,
                response.response_time_ms,
            )
        else:
            logger.warning("Agent execution [%s] failed", execution_id)

        # 持久化到数据库（如果有 repo）
        if self._repo:
            try:
                self._repo.create_log(log_data)
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Failed to persist agent execution log: error_type=%s",
                    type(exc).__name__,
                )

    def _serialize_tool_calls(
        self, tool_calls: Sequence[ToolCallRecord | dict[str, Any]] | None
    ) -> str | None:
        """序列化工具调用列表。"""
        if not tool_calls:
            return None
        records: list[dict[str, Any]] = []
        for tc in tool_calls:
            if isinstance(tc, ToolCallRecord):
                records.append(
                    {
                        "tool_name": _safe_trace_text(tc.tool_name, 100),
                        "arguments": _safe_trace_value(tc.arguments),
                        "success": tc.success,
                        "duration_ms": tc.duration_ms,
                        "error": "" if tc.success else "tool_call_failed",
                    }
                )
            elif isinstance(tc, dict):
                sanitized = _safe_trace_value(tc)
                if isinstance(sanitized, dict):
                    records.append(sanitized)
        return json.dumps(records, ensure_ascii=False, default=str)
