"""
Domain Entities for AI Provider Management.

Pure data classes using only Python standard library.
遵循项目架构约束：Domain层只使用Python标准库。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict
from datetime import datetime


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
    daily_budget_limit: Optional[float] = None
    monthly_budget_limit: Optional[float] = None
    description: str = ""
    extra_config: Optional[Dict] = None

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
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AIChatRequest:
    """AI聊天请求（值对象）"""
    messages: list  # List[Dict[str, str]]
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    tools: Optional[list] = None  # List[Dict] - OpenAI function calling format
    tool_choice: Optional[str] = None  # "auto" | "none" | "required" | specific tool
    response_format: Optional[Dict] = None  # {"type": "json_object"} etc.
    metadata: Optional[Dict] = None


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
    error_message: Optional[str] = None
    estimated_cost: Optional[float] = None
    tool_calls: Optional[list] = None  # List[ToolCallInfo]
    raw_response: Optional[Dict] = None
    request_type: Optional[str] = None  # "responses" | "chat"
