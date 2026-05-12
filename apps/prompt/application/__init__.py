"""
Domain Entities for AI Prompt Management.

This file defines pure data classes using only Python standard library.
No Django, Pandas, or external dependencies allowed.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional


class PlaceholderType(Enum):
    """占位符类型"""
    SIMPLE = "simple"           # {{PMI}} -> 直接值替换
    STRUCTURED = "structured"   # {{MACRO_DATA}} -> 表格/JSON
    FUNCTION = "function"       # {{TREND(PMI,6m)}} -> 函数调用
    CONDITIONAL = "conditional" # {%if%} -> 模板语法


class ChainExecutionMode(Enum):
    """链式执行模式"""
    SERIAL = "serial"           # 串行：Step1 -> Step2 -> Step3
    PARALLEL = "parallel"       # 并行：多个Step同时执行 -> 汇总
    TOOL_CALLING = "tool"       # 工具调用：AI主动调用函数
    HYBRID = "hybrid"           # 混合模式


class PromptCategory(Enum):
    """Prompt分类"""
    REPORT_ANALYSIS = "report"      # 投资分析报告生成
    SIGNAL_GENERATION = "signal"    # 投资信号自动生成
    DATA_ANALYSIS = "analysis"      # 通用数据分析
    CHAT = "chat"                   # 聊天提问


@dataclass(frozen=True)
class PlaceholderDef:
    """占位符定义（值对象）

    Attributes:
        name: 占位符名称，如 "PMI", "MACRO_DATA"
        type: 占位符类型
        description: 描述
        default_value: 默认值
        required: 是否必填
        function_name: FUNCTION类型的函数名
        function_params: FUNCTION类型的函数参数
    """
    name: str
    type: PlaceholderType
    description: str
    default_value: Any | None = None
    required: bool = True
    function_name: str | None = None
    function_params: dict[str, Any] | None = None


@dataclass(frozen=True)
class PromptTemplate:
    """Prompt模板实体（值对象）

    Attributes:
        id: 模板ID（可选，新建时为None）
        name: 模板名称（唯一标识）
        category: 分类
        version: 版本号
        template_content: 模板内容（支持Jinja2语法）
        placeholders: 占位符定义列表
        system_prompt: 系统提示词
        temperature: 默认温度参数
        max_tokens: 最大token数
        description: 模板描述
        is_active: 是否激活
        created_at: 创建日期
    """
    id: str | None
    name: str
    category: PromptCategory
    version: str
    template_content: str
    placeholders: list[PlaceholderDef]
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    description: str = ""
    is_active: bool = True
    created_at: date | None = None

    def __post_init__(self):
        """验证数据一致性"""
        # 确保temperature在有效范围内
        if self.temperature < 0 or self.temperature > 2:
            raise ValueError(f"temperature must be between 0 and 2, got {self.temperature}")
        # 确保max_tokens为正数
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")


@dataclass(frozen=True)
class ChainStep:
    """链式步骤定义（值对象）

    Attributes:
        step_id: 步骤ID
        template_id: 引用的模板ID
        step_name: 步骤名称
        order: 执行顺序
        input_mapping: 输入映射，将前序步骤的输出映射到当前模板的占位符
                       {"PMI": "step1.output.growth.pmi"}
        output_parser: 输出解析规则（JSON提取规则）
        parallel_group: 并行分组（同组的步骤并行执行）
        enable_tool_calling: 是否启用工具调用
        available_tools: 可用工具列表
    """
    step_id: str
    template_id: str
    step_name: str
    order: int
    input_mapping: dict[str, str]
    output_parser: str | None = None
    parallel_group: str | None = None
    enable_tool_calling: bool = False
    available_tools: list[str] | None = None


@dataclass(frozen=True)
class ChainConfig:
    """链式配置实体（值对象）

    Attributes:
        id: 配置ID（可选，新建时为None）
        name: 链名称（唯一标识）
        category: 分类
        description: 描述
        steps: 步骤列表
        execution_mode: 执行模式
        aggregate_step: 汇总步骤（用于并行模式）
        is_active: 是否激活
        created_at: 创建日期
    """
    id: str | None
    name: str
    category: PromptCategory
    description: str
    steps: list[ChainStep]
    execution_mode: ChainExecutionMode
    aggregate_step: ChainStep | None = None
    is_active: bool = True
    created_at: date | None = None

    def __post_init__(self):
        """验证数据一致性"""
        # 验证步骤order的唯一性
        # - 非并行步骤的order必须唯一
        # - 同一parallel_group内的步骤可以有相同order（并行执行）
        # - 不同parallel_group不能有相同的order
        from collections import defaultdict

        # 收集非并行步骤的order
        non_parallel_orders = [s.order for s in self.steps if not s.parallel_group]
        if len(non_parallel_orders) != len(set(non_parallel_orders)):
            raise ValueError("Non-parallel ChainStep orders must be unique")

        # 收集每个parallel_group使用的order
        group_orders = defaultdict(set)
        for step in self.steps:
            if step.parallel_group:
                group_orders[step.parallel_group].add(step.order)

        # 检查parallel_group之间没有order冲突
        all_parallel_orders = set()
        for _group, orders in group_orders.items():
            for order in orders:
                if order in all_parallel_orders:
                    raise ValueError(f"Order {order} is used by multiple parallel groups")
                all_parallel_orders.add(order)


@dataclass(frozen=True)
class PromptExecutionContext:
    """Prompt执行上下文（值对象）

    Attributes:
        placeholder_values: 占位符值
        regime_snapshot: Regime快照数据
        policy_level: 政策档位
        provider_ref: 指定AI提供商标识，可为名称或ID
        provider_name: 兼容旧字段，等价于 provider_ref
        model: 指定模型
        chain_execution_id: 链式执行ID
        step_outputs: 前序步骤输出
    """
    placeholder_values: dict[str, Any]
    regime_snapshot: dict | None = None
    policy_level: int | None = None
    provider_ref: Any | None = None
    provider_name: str | None = None
    model: str | None = None
    chain_execution_id: str | None = None
    step_outputs: dict[str, Any] | None = None


@dataclass(frozen=True)
class PromptExecutionResult:
    """Prompt执行结果（值对象）

    Attributes:
        success: 是否成功
        content: AI生成内容
        provider_used: 实际使用的提供商
        model_used: 实际使用的模型
        prompt_tokens: 输入token数
        completion_tokens: 输出token数
        total_tokens: 总token数
        estimated_cost: 预估成本
        response_time_ms: 响应时间（毫秒）
        error_message: 错误信息
        parsed_output: 解析后的结构化输出
    """
    success: bool
    content: str
    provider_used: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    response_time_ms: int
    error_message: str | None = None
    parsed_output: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChainExecutionResult:
    """链式执行结果（值对象）

    Attributes:
        success: 是否成功
        chain_name: 链名称
        execution_mode: 执行模式
        step_results: 每个步骤的结果
        final_output: 最终输出（汇总步骤或最后一步）
        total_tokens: 总token数
        total_cost: 总成本
        total_time_ms: 总时间（毫秒）
        error_message: 错误信息
    """
    success: bool
    chain_name: str
    execution_mode: ChainExecutionMode
    step_results: dict[str, PromptExecutionResult]
    final_output: str | None = None
    total_tokens: int = 0
    total_cost: float = 0.0
    total_time_ms: int = 0
    error_message: str | None = None

