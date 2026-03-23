"""
Data Transfer Objects for AI Provider Management.

DTOs 用于在 Application 层和 Interface 层之间传递数据。
只使用 Python 标准库。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ProviderStatsDTO:
    """提供商统计数据传输对象"""
    provider_id: int
    provider_name: str
    today_requests: int
    today_cost: float
    month_requests: int
    month_cost: float
    usage_by_date: list[dict[str, Any]]
    model_stats: list[dict[str, Any]]


@dataclass(frozen=True)
class UsageStatsDTO:
    """使用统计数据传输对象"""
    total_requests: int
    success_requests: int
    total_tokens: int
    total_cost: float
    avg_response_time_ms: float


@dataclass(frozen=True)
class OverallStatsDTO:
    """总体统计数据传输对象"""
    total_providers: int
    active_providers: int
    total_requests_today: int
    total_cost_today: float


@dataclass(frozen=True)
class ProviderListItemDTO:
    """提供商列表项数据传输对象"""
    id: int
    name: str
    provider_type: str
    is_active: bool
    priority: int
    base_url: str
    default_model: str
    api_mode: str
    fallback_enabled: bool
    description: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    # 统计数据
    today_requests: int
    today_cost: float
    month_requests: int
    month_cost: float


@dataclass(frozen=True)
class BudgetCheckResultDTO:
    """预算检查结果数据传输对象"""
    daily_allowed: bool
    daily_message: str
    daily_spent: float
    daily_limit: float | None
    monthly_allowed: bool
    monthly_message: str
    monthly_spent: float
    monthly_limit: float | None


@dataclass(frozen=True)
class UsageLogListItemDTO:
    """使用日志列表项数据传输对象"""
    id: int
    provider_id: int
    provider_name: str
    model: str
    request_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    response_time_ms: int
    status: str
    error_message: str
    created_at: datetime
