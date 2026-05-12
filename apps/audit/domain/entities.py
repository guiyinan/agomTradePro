"""
Domain Entities for Attribution Analysis.

This module contains the core data entities for the audit module.
Following four-layer architecture, this file uses ONLY Python standard library.
"""

from dataclasses import dataclass
from datetime import UTC, date
from enum import Enum
from typing import Any


class LossSource(Enum):
    """损失来源归因"""
    REGIME_TIMING_ERROR = "regime_timing"  # Regime 判断错误
    ASSET_SELECTION_ERROR = "asset_selection"  # 资产选择错误
    POLICY_INTERVENTION = "policy_intervention"  # 政策干预
    MARKET_VOLATILITY = "market_volatility"  # 市场波动
    TRANSACTION_COST = "transaction_cost"  # 交易成本
    UNKNOWN = "unknown"


class RegimeTransition(Enum):
    """Regime 转换类型"""
    SAME = "same"  # 保持不变
    CORRECT_PREDICTION = "correct_prediction"  # 正确预测转换
    MISSED_PREDICTION = "missed_prediction"  # 错过转换
    WRONG_PREDICTION = "wrong_prediction"  # 错误预测


class AttributionMethod(Enum):
    """归因方法"""
    HEURISTIC = "heuristic"  # 启发式方法（30%/50% 规则）
    BRINSON = "brinson"  # 标准 Brinson 模型


@dataclass(frozen=True)
class RegimePeriod:
    """Regime 周期"""
    start_date: date
    end_date: date
    regime: str
    actual_regime: str | None = None  # 实际发生的 Regime（用于验证）
    confidence: float = 0.0

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days


@dataclass(frozen=True)
class PeriodPerformance:
    """周期表现"""
    period: RegimePeriod
    portfolio_return: float
    benchmark_return: float
    best_asset_return: float  # 该周期表现最好的资产收益
    worst_asset_return: float  # 该周期表现最差的资产收益
    asset_returns: dict[str, float]  # 各资产收益


@dataclass(frozen=True)
class AttributionResult:
    """归因分析结果

    ⚠️ 归因方法说明：
    - HEURISTIC: 启发式方法（30%/50% 规则），用于快速识别收益来源
    - BRINSON: 标准 Brinson 模型，提供严格的配置/选股/交互效应分解

    启发式方法注意事项：
    - 择时收益：正收益的 30% 归因于 Regime 择时
    - 选资产收益：超额收益的 50% 归因于资产选择
    - 这是简化估算，如需严格归因应使用 Brinson 模型
    """
    # 收益归因
    total_return: float
    regime_timing_pnl: float  # 择时收益（Regime 判断正确带来的收益）
    asset_selection_pnl: float  # 选资产收益（在正确 Regime 下选对资产）
    interaction_pnl: float  # 交互收益
    transaction_cost_pnl: float  # 交易成本

    # 损失分析
    loss_source: LossSource
    loss_amount: float  # 损失金额
    loss_periods: list[RegimePeriod]  # 亏损周期

    # 经验总结
    lesson_learned: str
    improvement_suggestions: list[str]

    # 详细分解
    period_attributions: list[dict]  # 每个周期的归因

    # 归因方法标识（放在最后，因为有默认值）
    attribution_method: AttributionMethod = AttributionMethod.HEURISTIC  # 使用的归因方法


@dataclass(frozen=True)
class BrinsonAttributionResult:
    """Brinson 归因模型结果

    标准 Brinson 模型将超额收益分解为：
    - Allocation Effect: 配置效应（资产配置偏离基准的收益）
    - Selection Effect: 选股效应（同类资产内选股能力的收益）
    - Interaction Effect: 交互效应（配置和选股的交互影响）

    公式:
    - Allocation Effect = Σ(wp_i - wb_i) * (rb_i - rb)
    - Selection Effect = Σ wb_i * (rp_i - rb_i)
    - Interaction Effect = Σ(wp_i - wb_i) * (rp_i - rb_i)

    其中:
    - wp_i: 组合中资产 i 的权重
    - wb_i: 基准中资产 i 的权重
    - rp_i: 组合中资产 i 的收益
    - rb_i: 基准中资产 i 的收益
    - rb: 基准整体收益
    """
    # 总体指标
    benchmark_return: float  # 基准收益率
    portfolio_return: float  # 组合收益率
    excess_return: float  # 超额收益 = portfolio_return - benchmark_return

    # Brinson 分解
    allocation_effect: float  # 配置效应
    selection_effect: float  # 选股效应
    interaction_effect: float  # 交互效应

    # 验证：三项之和应等于超额收益
    attribution_sum: float  # allocation + selection + interaction

    # 分时段分解
    period_breakdown: list[dict]  # 各时段的 Brinson 分解

    # 分资产类别分解
    sector_breakdown: dict[str, dict]  # 各资产类别的详细分解
    # 格式: {asset_class: {"allocation": float, "selection": float, "interaction": float}}


@dataclass(frozen=True)
class AttributionConfig:
    """归因分析配置"""
    risk_free_rate: float = 0.03  # 无风险利率
    benchmark_return: float = 0.08  # 基准收益（年化）
    min_confidence_threshold: float = 0.3  # 最低置信度阈值
    attribution_method: AttributionMethod = AttributionMethod.HEURISTIC  # 归因方法


# ============ 指标表现评估相关实体 ============

class ValidationStatus(Enum):
    """验证状态"""
    PENDING = "pending"  # 待验证
    IN_PROGRESS = "in_progress"  # 验证中
    PASSED = "passed"  # 通过验证
    FAILED = "failed"  # 未通过验证
    SHADOW_RUN = "shadow_run"  # 影子模式运行


class RecommendedAction(Enum):
    """建议操作"""
    KEEP = "keep"  # 保持当前配置
    INCREASE = "increase"  # 增加权重
    DECREASE = "decrease"  # 降低权重
    REMOVE = "remove"  # 移除指标


@dataclass(frozen=True)
class IndicatorPerformanceReport:
    """指标表现报告

    评估单个指标对 Regime 判断的预测能力。
    """
    indicator_code: str
    evaluation_period_start: date
    evaluation_period_end: date

    # 混淆矩阵
    true_positive_count: int
    false_positive_count: int
    true_negative_count: int
    false_negative_count: int

    # 统计指标
    precision: float
    recall: float
    f1_score: float
    accuracy: float

    # 领先时间（月）
    lead_time_mean: float
    lead_time_std: float

    # 稳定性（分段相关性）
    pre_2015_correlation: float | None
    post_2015_correlation: float | None
    stability_score: float

    # 建议
    recommended_action: str  # "KEEP" / "INCREASE" / "DECREASE" / "REMOVE"
    recommended_weight: float
    confidence_level: float

    # 详细分析
    decay_rate: float = 0.0  # 信号衰减率
    signal_strength: float = 0.0  # 信号强度


@dataclass(frozen=True)
class IndicatorThresholdConfig:
    """指标阈值配置（Domain 层值对象）"""
    indicator_code: str
    indicator_name: str

    # 阈值定义
    level_low: float | None
    level_high: float | None

    # 权重配置
    base_weight: float = 1.0
    min_weight: float = 0.0
    max_weight: float = 1.0

    # 验证阈值（可调整）
    decay_threshold: float = 0.2  # F1 分数低于此值视为衰减
    decay_penalty: float = 0.5  # 衰减惩罚系数
    improvement_threshold: float = 0.1  # 改进阈值
    improvement_bonus: float = 1.2  # 改进奖励系数

    # 行为阈值
    keep_min_f1: float = 0.6  # 保持当前权重的最低 F1
    reduce_min_f1: float = 0.4  # 降低权重的最高 F1
    remove_max_f1: float = 0.3  # 建议移除的最高 F1


@dataclass(frozen=True)
class ThresholdValidationReport:
    """阈值验证报告

    验证历史阈值配置的表现。
    """
    validation_run_id: str
    run_date: date
    evaluation_period_start: date
    evaluation_period_end: date

    total_indicators: int
    approved_indicators: int  # 通过验证
    rejected_indicators: int  # 未通过验证
    pending_indicators: int  # 需要更多数据

    # 各指标的详细报告
    indicator_reports: list[IndicatorPerformanceReport]

    # 总体建议
    overall_recommendation: str

    # 验证状态
    status: ValidationStatus


@dataclass(frozen=True)
class DynamicWeightConfig:
    """动态权重配置

    根据指标表现动态调整权重。
    """
    indicator_code: str
    current_weight: float
    original_weight: float

    # 调整依据
    f1_score: float
    stability_score: float
    decay_rate: float

    # 调整参数
    adjustment_factor: float  # 调整系数
    new_weight: float  # 调整后权重

    # 调整原因
    reason: str
    confidence: float


@dataclass(frozen=True)
class SignalEvent:
    """信号事件"""
    indicator_code: str
    signal_date: date
    signal_type: str  # "BULLISH" / "BEARISH" / "NEUTRAL"
    signal_value: float
    threshold_used: float
    confidence: float


@dataclass(frozen=True)
class RegimeSnapshot:
    """Regime 快照（用于验证）"""
    observed_at: date
    dominant_regime: str
    confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    distribution: dict[str, float]  # 各 Regime 的概率分布


# ============ MCP/SDK 操作审计日志实体 ============

class OperationSource(Enum):
    """操作来源"""
    MCP = "MCP"
    SDK = "SDK"
    API = "API"


class OperationType(Enum):
    """操作类型"""
    MCP_CALL = "MCP_CALL"
    API_ACCESS = "API_ACCESS"
    DATA_MODIFY = "DATA_MODIFY"


class OperationAction(Enum):
    """操作动作"""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"


@dataclass(frozen=True)
class OperationLog:
    """MCP/SDK 操作审计日志实体

    记录所有通过 MCP 和 SDK 进行的工具调用，用于审计追踪。
    遵循四层架构，此文件仅使用 Python 标准库。
    """
    # 唯一标识
    id: str  # UUID
    request_id: str  # 链路追踪ID

    # 操作者身份
    user_id: int | None
    username: str
    ip_address: str | None
    user_agent: str

    # 来源与租户
    source: OperationSource
    client_id: str

    # 操作描述
    operation_type: OperationType
    module: str
    action: OperationAction
    resource_type: str
    resource_id: str | None

    # MCP 特定字段
    mcp_tool_name: str | None
    mcp_client_id: str
    mcp_role: str
    sdk_version: str

    # 请求详情
    request_method: str
    request_path: str
    request_params: dict[str, Any]  # 已脱敏
    response_payload: Any | None
    response_text: str
    response_status: int
    response_message: str
    error_code: str
    exception_traceback: str

    # 时间与性能
    timestamp: str  # ISO 8601 格式
    duration_ms: int | None

    # 完整性
    checksum: str

    @classmethod
    def create(
        cls,
        request_id: str,
        user_id: int | None,
        username: str,
        source: OperationSource,
        operation_type: OperationType,
        module: str,
        action: OperationAction,
        mcp_tool_name: str | None = None,
        request_params: dict[str, Any] | None = None,
        response_payload: Any | None = None,
        response_text: str = "",
        response_status: int = 200,
        response_message: str = "",
        error_code: str = "",
        exception_traceback: str = "",
        duration_ms: int | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
        client_id: str = "",
        resource_type: str = "",
        resource_id: str | None = None,
        mcp_client_id: str = "",
        mcp_role: str = "",
        sdk_version: str = "",
        request_method: str = "MCP",
        request_path: str = "",
    ) -> 'OperationLog':
        """创建操作日志实体"""
        import uuid
        from datetime import datetime

        # 生成 UUID
        log_id = str(uuid.uuid4())

        # 时间戳
        timestamp = datetime.now(UTC).isoformat()

        # 脱敏参数
        masked_params = mask_sensitive_params(request_params or {})
        masked_response_payload = mask_sensitive_params(response_payload)
        normalized_response_text = response_text or ""

        # 计算校验和
        checksum = cls._compute_checksum(
            log_id,
            request_id,
            timestamp,
            masked_params,
            masked_response_payload,
            normalized_response_text,
        )

        return cls(
            id=log_id,
            request_id=request_id,
            user_id=user_id,
            username=username or "anonymous",
            ip_address=ip_address,
            user_agent=user_agent,
            source=source,
            client_id=client_id,
            operation_type=operation_type,
            module=module,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            mcp_tool_name=mcp_tool_name,
            mcp_client_id=mcp_client_id,
            mcp_role=mcp_role,
            sdk_version=sdk_version,
            request_method=request_method,
            request_path=request_path,
            request_params=masked_params,
            response_payload=masked_response_payload,
            response_text=normalized_response_text,
            response_status=response_status,
            response_message=response_message,
            error_code=error_code,
            exception_traceback=exception_traceback or "",
            timestamp=timestamp,
            duration_ms=duration_ms,
            checksum=checksum,
        )

    @staticmethod
    def _compute_checksum(
        log_id: str,
        request_id: str,
        timestamp: str,
        params: dict,
        response_payload: Any,
        response_text: str,
    ) -> str:
        """计算校验和"""
        import hashlib
        import json

        payload_json = json.dumps(response_payload, sort_keys=True, ensure_ascii=False, default=str)
        params_json = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
        data = f"{log_id}:{request_id}:{timestamp}:{params_json}:{payload_json}:{response_text}"
        return hashlib.sha256(data.encode()).hexdigest()


# 敏感字段关键词（用于脱敏）
SENSITIVE_KEYWORDS = frozenset([
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "credential",
    "private_key",
    "access_key",
    "secret_key",
])


def mask_sensitive_params(params: Any, mask: str = "***") -> Any:
    """脱敏敏感参数

    递归处理字典和列表，将敏感字段的值替换为掩码。

    Args:
        params: 原始参数（可以是 dict、list 或其他类型）
        mask: 掩码字符串

    Returns:
        脱敏后的参数
    """
    if isinstance(params, dict):
        masked = {}
        for key, value in params.items():
            key_lower = key.lower()
            # 检查是否为敏感字段
            if any(keyword in key_lower for keyword in SENSITIVE_KEYWORDS):
                masked[key] = mask
            else:
                # 递归处理嵌套结构
                masked[key] = mask_sensitive_params(value, mask)
        return masked
    elif isinstance(params, list):
        return [mask_sensitive_params(item, mask) for item in params]
    else:
        return params


def infer_action_from_tool(tool_name: str) -> OperationAction:
    """从工具名推断操作动作

    Args:
        tool_name: MCP 工具名

    Returns:
        推断的操作动作
    """
    name_lower = tool_name.lower()

    if name_lower.startswith("create_") or name_lower.startswith("add_"):
        return OperationAction.CREATE
    elif name_lower.startswith("update_") or name_lower.startswith("modify_") or name_lower.startswith("edit_"):
        return OperationAction.UPDATE
    elif name_lower.startswith("delete_") or name_lower.startswith("remove_"):
        return OperationAction.DELETE
    elif name_lower.startswith("execute_") or name_lower.startswith("run_") or name_lower.startswith("submit_"):
        return OperationAction.EXECUTE
    else:
        return OperationAction.READ


def infer_module_from_tool(tool_name: str) -> str:
    """从工具名推断所属模块

    Args:
        tool_name: MCP 工具名

    Returns:
        推断的模块名
    """
    name_lower = tool_name.lower()

    # 模块关键词映射
    module_keywords = {
        "signal": ["signal"],
        "policy": ["policy"],
        "backtest": ["backtest"],
        "regime": ["regime"],
        "macro": ["macro"],
        "account": ["account", "portfolio", "position", "transaction"],
        "equity": ["equity", "stock"],
        "fund": ["fund"],
        "sector": ["sector"],
        "strategy": ["strategy"],
        "alpha": ["alpha"],
        "factor": ["factor"],
        "rotation": ["rotation"],
        "hedge": ["hedge"],
        "realtime": ["realtime", "price"],
        "sentiment": ["sentiment"],
        "simulated": ["simulated", "trading"],
        "dashboard": ["dashboard"],
        "filter": ["filter"],
        "event": ["event"],
        "decision": ["decision"],
        "task": ["task", "monitor"],
        "ai_provider": ["ai_provider", "provider", "llm"],
        "prompt": ["prompt"],
    }

    for module, keywords in module_keywords.items():
        if any(kw in name_lower for kw in keywords):
            return module

    return "general"
