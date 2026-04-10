"""
Domain entities for AI provider management.

Domain 层只定义纯 Python 值对象与枚举。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class AIProviderType(Enum):
    """AI提供商类型枚举"""

    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    MOONSHOT = "moonshot"
    CUSTOM = "custom"


class ProviderScope(Enum):
    """Provider ownership scope."""

    SYSTEM = "system"
    USER = "user"


class UsageProviderScope(Enum):
    """Runtime attribution scope for usage logs."""

    SYSTEM_GLOBAL = "system_global"
    SYSTEM_FALLBACK = "system_fallback"
    PERSONAL = "personal"


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
    scope: ProviderScope = ProviderScope.SYSTEM
    owner_user_id: int | None = None
    daily_budget_limit: float | None = None
    monthly_budget_limit: float | None = None
    description: str = ""
    extra_config: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.extra_config is None:
            object.__setattr__(self, "extra_config", {})


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
    provider_scope: UsageProviderScope = UsageProviderScope.SYSTEM_GLOBAL
    user_id: int | None = None
    quota_charged: bool = False
    error_message: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AIUserFallbackQuota:
    """用户系统兜底额度值对象"""

    user_id: int
    daily_limit: float | None
    monthly_limit: float | None
    is_active: bool = True
    admin_note: str = ""
    daily_spent: float = 0.0
    monthly_spent: float = 0.0


@dataclass(frozen=True)
class AIChatRequest:
    """AI聊天请求（值对象）"""

    messages: list[dict[str, Any]]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None
    response_format: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCallInfo:
    """工具调用信息（值对象）"""

    id: str
    tool_name: str
    arguments: str


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
    provider_scope: UsageProviderScope = UsageProviderScope.SYSTEM_GLOBAL
    quota_charged: bool = False
    error_message: str | None = None
    estimated_cost: float | None = None
    tool_calls: list[ToolCallInfo] | None = None
    raw_response: dict[str, Any] | None = None
    request_type: str | None = None
