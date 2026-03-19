"""
Agent Runtime Domain Entities.

纯 Python 数据结构，定义 Agent 执行请求、响应和工具调用记录。
遵循项目架构约束：Domain 层只使用 Python 标准库。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentTaskType(Enum):
    """Agent 任务类型"""
    CHAT = "chat"
    ANALYSIS = "analysis"
    SIGNAL = "signal"
    REPORT = "report"
    STRATEGY = "strategy"


@dataclass(frozen=True)
class ToolCallRecord:
    """单次工具调用记录（值对象）

    Attributes:
        tool_name: 工具名称
        arguments: 调用参数
        success: 是否成功
        result: 执行结果
        error_message: 错误信息
        duration_ms: 执行耗时（毫秒）
    """
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    result: Any
    error_message: Optional[str] = None
    duration_ms: int = 0


@dataclass(frozen=True)
class AgentTurnResult:
    """单轮推理结果（值对象）

    Attributes:
        turn_number: 第几轮
        has_tool_calls: 本轮是否产生了工具调用
        tool_calls: 本轮执行的工具调用列表
        content: 模型本轮的文本输出（可能为空）
        prompt_tokens: 本轮 prompt tokens
        completion_tokens: 本轮 completion tokens
        finish_reason: 模型结束原因
    """
    turn_number: int
    has_tool_calls: bool
    tool_calls: List[ToolCallRecord]
    content: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: Optional[str] = None


@dataclass
class AgentExecutionRequest:
    """Agent 执行请求

    Attributes:
        task_type: 任务类型
        user_input: 用户输入 / 任务描述
        provider_ref: AI 提供商标识
        model: 模型名称
        temperature: 温度
        max_tokens: 最大 token 数
        context_scope: 需要构建的上下文域列表
        context_params: 上下文构建参数
        tool_names: 允许使用的工具白名单
        response_schema: 结构化输出的 JSON Schema
        max_rounds: 最大工具调用轮次
        session_id: 会话 ID
        system_prompt: 系统提示词（可选，覆盖模板）
        metadata: 附加元数据
    """
    task_type: str
    user_input: str
    provider_ref: Any = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_scope: Optional[List[str]] = None
    context_params: Optional[Dict[str, Any]] = None
    tool_names: Optional[List[str]] = None
    response_schema: Optional[Dict[str, Any]] = None
    max_rounds: int = 4
    session_id: Optional[str] = None
    system_prompt: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class AgentExecutionResponse:
    """Agent 执行响应（值对象）

    Attributes:
        success: 是否成功
        final_answer: 最终文本答案
        structured_output: 结构化输出
        used_context: 使用的上下文域列表
        tool_calls: 所有工具调用记录
        turns: 各轮推理结果
        turn_count: 总轮次
        provider_used: 使用的提供商
        model_used: 使用的模型
        total_tokens: 总 token 数
        prompt_tokens: 总 prompt tokens
        completion_tokens: 总 completion tokens
        estimated_cost: 预估成本
        response_time_ms: 总响应时间（毫秒）
        error_message: 错误信息
        execution_id: 执行 ID
    """
    success: bool
    final_answer: Optional[str]
    structured_output: Optional[Dict[str, Any]] = None
    used_context: Optional[List[str]] = None
    tool_calls: Optional[List[ToolCallRecord]] = None
    turns: Optional[List[AgentTurnResult]] = None
    turn_count: int = 0
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0
    response_time_ms: int = 0
    error_message: Optional[str] = None
    execution_id: Optional[str] = None
