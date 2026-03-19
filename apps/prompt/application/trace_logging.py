"""
Trace Logging Service.

为 AgentRuntime 提供执行追踪和审计日志记录。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..domain.agent_entities import (
    AgentExecutionRequest,
    AgentExecutionResponse,
    ToolCallRecord,
)

logger = logging.getLogger(__name__)


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

    def __init__(self, execution_log_repository: Any = None):
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
        # 构建 trace 元数据（存入 parsed_output JSON 字段）
        trace_meta = {
            "task_type": request.task_type,
            "session_id": request.session_id,
            "turn_count": response.turn_count,
            "used_context": response.used_context or [],
            "tool_calls": json.loads(
                self._serialize_tool_calls(response.tool_calls) or "[]"
            ),
            "structured_output": response.structured_output,
        }

        # 映射到 PromptExecutionLogORM 字段
        log_data = {
            "execution_id": response.execution_id,
            "rendered_prompt": _truncate(request.user_input, 5000) or "",
            "ai_response": _truncate(response.final_answer, 5000) or "",
            "parsed_output": trace_meta,
            "placeholder_values": {
                "context_scope": request.context_scope or [],
                "tool_names": request.tool_names or [],
                "context_params": request.context_params or {},
            },
            "provider_used": response.provider_used or "",
            "model_used": response.model_used or "",
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "estimated_cost": response.estimated_cost or 0,
            "response_time_ms": response.response_time_ms,
            "status": "success" if response.success else "error",
            "error_message": response.error_message or "",
        }

        # 记录到标准 logger
        if response.success:
            logger.info(
                "Agent execution [%s] completed: turns=%d, tokens=%d, tools=%d, time=%dms",
                response.execution_id,
                response.turn_count,
                response.total_tokens,
                len(response.tool_calls) if response.tool_calls else 0,
                response.response_time_ms,
            )
        else:
            logger.warning(
                "Agent execution [%s] failed: %s",
                response.execution_id,
                response.error_message,
            )

        # 持久化到数据库（如果有 repo）
        if self._repo:
            try:
                self._repo.create_log(log_data)
            except Exception as exc:
                logger.warning("Failed to persist agent execution log: %s", exc)

    def _serialize_tool_calls(
        self, tool_calls: Optional[list]
    ) -> Optional[str]:
        """序列化工具调用列表。"""
        if not tool_calls:
            return None
        records = []
        for tc in tool_calls:
            if isinstance(tc, ToolCallRecord):
                records.append({
                    "tool_name": tc.tool_name,
                    "arguments": tc.arguments,
                    "success": tc.success,
                    "duration_ms": tc.duration_ms,
                    "error": tc.error_message,
                })
            elif isinstance(tc, dict):
                records.append(tc)
        return json.dumps(records, ensure_ascii=False, default=str)


def _truncate(text: Optional[str], max_length: int) -> Optional[str]:
    """截断文本。"""
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
