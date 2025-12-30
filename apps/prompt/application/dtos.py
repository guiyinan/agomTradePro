"""
DTOs for AI Prompt Management.

Data Transfer Objects for request/response handling
in the Application layer.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import date


@dataclass
class TemplateCreateRequest:
    """创建模板请求"""
    name: str
    category: str
    template_content: str
    placeholders: List[Dict[str, Any]]
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    description: str = ""


@dataclass
class TemplateUpdateRequest:
    """更新模板请求"""
    template_id: int
    name: str
    category: str
    template_content: str
    placeholders: List[Dict[str, Any]]
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
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
    placeholders: List[Dict[str, Any]]
    system_prompt: Optional[str]
    temperature: float
    max_tokens: Optional[int]
    description: str
    is_active: bool
    created_at: Optional[date]


@dataclass
class ChainCreateRequest:
    """创建链配置请求"""
    name: str
    category: str
    description: str
    steps: List[Dict[str, Any]]
    execution_mode: str
    aggregate_step: Optional[Dict[str, Any]] = None


@dataclass
class ChainResponse:
    """链配置响应"""
    id: str
    name: str
    category: str
    description: str
    steps: List[Dict[str, Any]]
    execution_mode: str
    aggregate_step: Optional[Dict[str, Any]]
    is_active: bool
    created_at: Optional[date]


@dataclass
class ExecutePromptRequest:
    """执行Prompt的请求DTO"""
    template_id: int
    placeholder_values: Dict[str, Any]
    provider_name: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


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
    error_message: Optional[str]
    parsed_output: Optional[Dict[str, Any]]
    template_name: str


@dataclass
class ExecuteChainRequest:
    """执行链式的请求DTO"""
    chain_id: int
    placeholder_values: Dict[str, Any]
    provider_name: Optional[str] = None
    model: Optional[str] = None


@dataclass
class ExecuteChainResponse:
    """执行链式的响应DTO"""
    success: bool
    chain_name: str
    execution_mode: str
    step_results: Dict[str, Dict[str, Any]]
    final_output: Optional[str]
    total_tokens: int
    total_cost: float
    total_time_ms: int
    error_message: Optional[str]


@dataclass
class GenerateReportRequest:
    """生成投资分析报告的请求DTO"""
    as_of_date: date
    include_regime: bool = True
    include_policy: bool = True
    include_macro: bool = True
    indicators: Optional[List[str]] = None
    provider_name: Optional[str] = None
    model: Optional[str] = None


@dataclass
class GenerateReportResponse:
    """生成投资分析报告的响应DTO"""
    report: str
    metadata: Dict[str, Any]


@dataclass
class GenerateSignalRequest:
    """生成投资信号的请求DTO"""
    asset_code: str
    analysis_context: Dict[str, Any]
    provider_name: Optional[str] = None


@dataclass
class GenerateSignalResponse:
    """生成投资信号的响应DTO"""
    asset_code: str
    direction: str
    logic_desc: str
    invalidation_logic: str
    invalidation_threshold: Optional[float]
    target_regime: str
    confidence: float


@dataclass
class ChatRequest:
    """聊天请求"""
    message: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    provider_name: Optional[str] = None
    model: Optional[str] = None


@dataclass
class ChatResponse:
    """聊天响应"""
    reply: str
    session_id: str
    metadata: Dict[str, Any]


@dataclass
class ValidationErrorResponse:
    """验证错误响应"""
    field: str
    message: str
    code: str


@dataclass
class ListTemplatesRequest:
    """列出模板请求"""
    category: Optional[str] = None
    is_active: bool = True
    page: int = 1
    page_size: int = 20


@dataclass
class ListTemplatesResponse:
    """列出模板响应"""
    templates: List[TemplateResponse]
    total: int
    page: int
    page_size: int


@dataclass
class ListChainsRequest:
    """列出链配置请求"""
    category: Optional[str] = None
    is_active: bool = True
    page: int = 1
    page_size: int = 20


@dataclass
class ListChainsResponse:
    """列出链配置响应"""
    chains: List[ChainResponse]
    total: int
    page: int
    page_size: int


@dataclass
class ExecutionLogResponse:
    """执行日志响应"""
    id: str
    execution_id: str
    template_name: Optional[str]
    chain_name: Optional[str]
    step_id: Optional[str]
    status: str
    provider_used: str
    model_used: str
    total_tokens: int
    estimated_cost: float
    response_time_ms: int
    error_message: Optional[str]
    created_at: date


@dataclass
class ListLogsRequest:
    """列出日志请求"""
    template_id: Optional[int] = None
    chain_id: Optional[int] = None
    execution_id: Optional[str] = None
    status: Optional[str] = None
    limit: int = 50


@dataclass
class ListLogsResponse:
    """列出日志响应"""
    logs: List[ExecutionLogResponse]
    total: int
