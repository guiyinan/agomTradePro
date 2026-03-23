"""
Domain Entities for AI Provider Management.

Pure data classes using only Python standard library.
遵循项目架构约束：Domain层只使用Python标准库。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class AIProviderType(Enum):
    """AI提供商类型枚举"""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    MOONSHOT = "moonshot"
    CUSTOM = "custom"


@dataclass(frozen=True)
class AIProviderConfig:
    """AI提供商配置实体（值对象）"""
    name: str
    provider_type: AIProviderType
    base_url: str
    api_key: str
    default_model: str
    is_active: bool
    priority: int
    daily_budget_limit: float | None = None
    monthly_budget_limit: float | None = None
    description: str = ""
    extra_config: dict | None = None

    def __post_init__(self):
        if self.extra_config is None:
            object.__setattr__(self, 'extra_config', {})


@dataclass(frozen=True)
class AIUsageRecord:
    """AI API调用记录（值对象）"""
    provider_name: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    response_time_ms: int
    status: str
    error_message: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AIChatRequest:
    """AI聊天请求（值对象）"""
    messages: list  # List[Dict[str, str]]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list | None = None  # List[Dict] - OpenAI function calling format
    tool_choice: str | None = None  # "auto" | "none" | "required" | specific tool
    response_format: dict | None = None  # {"type": "json_object"} etc.
    metadata: dict | None = None


@dataclass(frozen=True)
class ToolCallInfo:
    """工具调用信息（值对象）"""
    id: str
    tool_name: str
    arguments: str  # JSON string of arguments


@dataclass(frozen=True)
class AIChatResponse:
    """AI聊天响应（值对象）"""
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    response_time_ms: int
    status: str
    error_message: str | None = None
    estimated_cost: float | None = None
    tool_calls: list | None = None  # List[ToolCallInfo]
    raw_response: dict | None = None
    request_type: str | None = None  # "responses" | "chat"
