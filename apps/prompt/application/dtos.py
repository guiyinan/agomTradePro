"""
DTOs for AI Prompt Management.

Data Transfer Objects for request/response handling
in the Application layer.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass
class TemplateCreateRequest:
    """创建模板请求"""
    name: str
    category: str
    template_content: str
    placeholders: list[dict[str, Any]]
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    description: str = ""


@dataclass
class TemplateUpdateRequest:
    """更新模板请求"""
    template_id: int
    name: str
    category: str
    template_content: str
    placeholders: list[dict[str, Any]]
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    description: str = ""
    is_active: bool = True


@dataclass
class TemplateResponse:
    """模板响应"""
    id: str
    name: str
    category: str
    version: str
    template_content: str
    placeholders: list[dict[str, Any]]
    system_prompt: str | None
    temperature: float
    max_tokens: int | None
    description: str
    is_active: bool
    created_at: date | None


@dataclass
class ChainCreateRequest:
    """创建链配置请求"""
    name: str
    category: str
    description: str
    steps: list[dict[str, Any]]
    execution_mode: str
    aggregate_step: dict[str, Any] | None = None


@dataclass
class ChainResponse:
    """链配置响应"""
    id: str
    name: str
    category: str
    description: str
    steps: list[dict[str, Any]]
    execution_mode: str
    aggregate_step: dict[str, Any] | None
    is_active: bool
    created_at: date | None


@dataclass
class ExecutePromptRequest:
    """执行Prompt的请求DTO"""
    template_id: int
    placeholder_values: dict[str, Any]
    provider_ref: Any | None = None
    provider_name: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    user_id: int | None = None


@dataclass
class ExecutePromptResponse:
    """执行Prompt的响应DTO"""
    success: bool
    content: str
    provider_used: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    response_time_ms: int
    error_message: str | None
    parsed_output: dict[str, Any] | None
    template_name: str


@dataclass
class ExecuteChainRequest:
    """执行链式的请求DTO"""
    chain_id: int
    placeholder_values: dict[str, Any]
    provider_ref: Any | None = None
    provider_name: str | None = None
    model: str | None = None
    user_id: int | None = None


@dataclass
class ExecuteChainResponse:
    """执行链式的响应DTO"""
    success: bool
    chain_name: str
    execution_mode: str
    step_results: dict[str, dict[str, Any]]
    final_output: str | None
    total_tokens: int
    total_cost: float
    total_time_ms: int
    error_message: str | None


@dataclass
class GenerateReportRequest:
    """生成投资分析报告的请求DTO"""
    as_of_date: date
    include_regime: bool = True
    include_policy: bool = True
    include_macro: bool = True
    indicators: list[str] | None = None
    provider_ref: Any | None = None
    provider_name: str | None = None
    model: str | None = None
    user_id: int | None = None


@dataclass
class GenerateReportResponse:
    """生成投资分析报告的响应DTO"""
    report: str
    metadata: dict[str, Any]


@dataclass
class GenerateSignalRequest:
    """生成投资信号的请求DTO"""
    asset_code: str
    analysis_context: dict[str, Any]
    provider_ref: Any | None = None
    provider_name: str | None = None
    user_id: int | None = None


@dataclass
class GenerateSignalResponse:
    """生成投资信号的响应DTO"""
    asset_code: str
    direction: str
    logic_desc: str
    invalidation_logic: str
    invalidation_threshold: float | None
    target_regime: str
    confidence: float


@dataclass
class ChatRequest:
    """聊天请求"""
    message: str
    session_id: str | None = None
    context: dict[str, Any] | None = None
    provider_ref: Any | None = None
    provider_name: str | None = None
    model: str | None = None


@dataclass
class ChatResponse:
    """聊天响应"""
    reply: str
    session_id: str
    metadata: dict[str, Any]


@dataclass
class ValidationErrorResponse:
    """验证错误响应"""
    field: str
    message: str
    code: str


@dataclass
class ListTemplatesRequest:
    """列出模板请求"""
    category: str | None = None
    is_active: bool = True
    page: int = 1
    page_size: int = 20


@dataclass
class ListTemplatesResponse:
    """列出模板响应"""
    templates: list[TemplateResponse]
    total: int
    page: int
    page_size: int


@dataclass
class ListChainsRequest:
    """列出链配置请求"""
    category: str | None = None
    is_active: bool = True
    page: int = 1
    page_size: int = 20


@dataclass
class ListChainsResponse:
    """列出链配置响应"""
    chains: list[ChainResponse]
    total: int
    page: int
    page_size: int


@dataclass
class ExecutionLogResponse:
    """执行日志响应"""
    id: str
    execution_id: str
    template_name: str | None
    chain_name: str | None
    step_id: str | None
    status: str
    provider_used: str
    model_used: str
    total_tokens: int
    estimated_cost: float
    response_time_ms: int
    error_message: str | None
    created_at: date


@dataclass
class ListLogsRequest:
    """列出日志请求"""
    template_id: int | None = None
    chain_id: int | None = None
    execution_id: str | None = None
    status: str | None = None
    limit: int = 50


@dataclass
class ListLogsResponse:
    """列出日志响应"""
    logs: list[ExecutionLogResponse]
    total: int
