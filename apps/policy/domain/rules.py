"""
Policy Response Rules - Domain Layer

定义政策档位的响应规则。
本层只使用 Python 标准库，不依赖 Django 或外部库。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .entities import PolicyLevel


class MarketAction(Enum):
    """市场行动类型"""
    NORMAL_OPERATION = "normal_operation"  # 正常运行
    INCREASE_CASH = "increase_cash"        # 提升现金权重
    PAUSE_SIGNALS = "pause_signals"        # 暂停信号
    FULL_HEDGING = "full_hedging"          # 全仓对冲
    MANUAL_TAKEOVER = "manual_takeover"    # 人工接管


@dataclass(frozen=True)
class PolicyResponse:
    """政策响应配置"""
    level: PolicyLevel
    name: str
    description: str
    market_action: MarketAction
    cash_adjustment: float  # 现金权重调整（百分比）
    signal_pause_hours: int | None  # 暂停信号时长（小时）
    requires_manual_approval: bool  # 是否需要人工审批
    alert_triggered: bool  # 是否触发告警


# 政策档位响应规则配置
POLICY_RESPONSE_RULES: dict[PolicyLevel, PolicyResponse] = {
    PolicyLevel.P0: PolicyResponse(
        level=PolicyLevel.P0,
        name="常态",
        description="无重大政策干预，市场正常运行",
        market_action=MarketAction.NORMAL_OPERATION,
        cash_adjustment=0.0,
        signal_pause_hours=None,
        requires_manual_approval=False,
        alert_triggered=False
    ),
    PolicyLevel.P1: PolicyResponse(
        level=PolicyLevel.P1,
        name="预警",
        description="政策信号出现，但尚未落地。如央行官员讲话、政治局会议定调",
        market_action=MarketAction.INCREASE_CASH,
        cash_adjustment=10.0,  # 提升现金权重 5-10%
        signal_pause_hours=None,
        requires_manual_approval=False,
        alert_triggered=False
    ),
    PolicyLevel.P2: PolicyResponse(
        level=PolicyLevel.P2,
        name="干预",
        description="实质性政策出台。如降息/加息、降准、财政刺激方案公布",
        market_action=MarketAction.PAUSE_SIGNALS,
        cash_adjustment=20.0,
        signal_pause_hours=48,  # 暂停 Regime 信号 24-48 小时
        requires_manual_approval=True,
        alert_triggered=True
    ),
    PolicyLevel.P3: PolicyResponse(
        level=PolicyLevel.P3,
        name="危机",
        description="极端政策或市场熔断。如熔断、汇率一次性调整、紧急救市",
        market_action=MarketAction.MANUAL_TAKEOVER,
        cash_adjustment=100.0,  # 全仓转现金
        signal_pause_hours=None,  # 人工接管，无需自动恢复
        requires_manual_approval=True,
        alert_triggered=True
    ),
}


def get_policy_response(level: PolicyLevel) -> PolicyResponse:
    """
    获取政策档位对应的响应配置

    Args:
        level: 政策档位

    Returns:
        PolicyResponse: 响应配置

    Raises:
        ValueError: 未知的政策档位
    """
    if level not in POLICY_RESPONSE_RULES:
        raise ValueError(f"Unknown policy level: {level}")
    return POLICY_RESPONSE_RULES[level]


def should_pause_trading_signals(level: PolicyLevel) -> bool:
    """
    判断是否应该暂停交易信号

    Args:
        level: 政策档位

    Returns:
        bool: 是否暂停
    """
    response = get_policy_response(level)
    return response.market_action in [
        MarketAction.PAUSE_SIGNALS,
        MarketAction.MANUAL_TAKEOVER
    ]


def get_signal_pause_duration_hours(level: PolicyLevel) -> int | None:
    """
    获取信号暂停时长

    Args:
        level: 政策档位

    Returns:
        Optional[int]: 暂停小时数，None 表示不暂停或无限期暂停
    """
    response = get_policy_response(level)
    return response.signal_pause_hours


def should_trigger_alert(level: PolicyLevel) -> bool:
    """
    判断是否应该触发告警

    Args:
        level: 政策档位

    Returns:
        bool: 是否告警
    """
    response = get_policy_response(level)
    return response.alert_triggered


def requires_manual_intervention(level: PolicyLevel) -> bool:
    """
    判断是否需要人工干预

    Args:
        level: 政策档位

    Returns:
        bool: 是否需要人工干预
    """
    response = get_policy_response(level)
    return response.requires_manual_approval


def get_cash_allocation_adjustment(level: PolicyLevel) -> float:
    """
    获取现金配置调整比例

    Args:
        level: 政策档位

    Returns:
        float: 现金权重调整百分比
    """
    response = get_policy_response(level)
    return response.cash_adjustment


def is_high_risk_level(level: PolicyLevel) -> bool:
    """
    判断是否为高风险档位

    P2 和 P3 被认为是高风险档位

    Args:
        level: 政策档位

    Returns:
        bool: 是否高风险
    """
    return level in [PolicyLevel.P2, PolicyLevel.P3]


def validate_policy_event(
    level: PolicyLevel,
    title: str,
    description: str,
    evidence_url: str
) -> tuple[bool, list[str]]:
    """
    验证政策事件的有效性

    Args:
        level: 政策档位
        title: 标题
        description: 描述
        evidence_url: 证据 URL

    Returns:
        tuple[bool, List[str]]: (是否有效, 错误信息列表)
    """
    errors = []

    # 标题不能为空
    if not title or not title.strip():
        errors.append("标题不能为空")

    # 描述不能为空
    if not description or not description.strip():
        errors.append("描述不能为空")

    # 描述长度检查（P2/P3 需要详细说明）
    if level in [PolicyLevel.P2, PolicyLevel.P3]:
        if len(description) < 20:
            errors.append(f"{level.value} 档位的描述需要至少 20 个字符")

    # 证据 URL 检查
    if not evidence_url or not evidence_url.strip():
        errors.append("必须提供证据 URL（新闻链接或官方公告）")
    else:
        # 简单的 URL 格式检查
        if not (evidence_url.startswith("http://") or evidence_url.startswith("https://")):
            errors.append("证据 URL 必须以 http:// 或 https:// 开头")

    return len(errors) == 0, errors


@dataclass(frozen=True)
class PolicyTransition:
    """政策档位变更记录"""
    from_level: PolicyLevel | None
    to_level: PolicyLevel
    transition_date: str  # ISO 格式日期字符串
    is_upgrade: bool  # 是否升级（P0->P1, P1->P2 等）


def analyze_policy_transition(
    from_level: PolicyLevel | None,
    to_level: PolicyLevel
) -> PolicyTransition:
    """
    分析政策档位变更

    Args:
        from_level: 原档位（None 表示初始状态）
        to_level: 新档位

    Returns:
        PolicyTransition: 变更分析结果
    """
    from datetime import date

    is_upgrade = False
    if from_level is not None:
        level_order = {PolicyLevel.P0: 0, PolicyLevel.P1: 1, PolicyLevel.P2: 2, PolicyLevel.P3: 3}
        is_upgrade = level_order.get(to_level, 0) > level_order.get(from_level, 0)

    return PolicyTransition(
        from_level=from_level,
        to_level=to_level,
        transition_date=date.today().isoformat(),
        is_upgrade=is_upgrade
    )


def get_recommendations_for_level(level: PolicyLevel) -> list[str]:
    """
    根据政策档位获取操作建议

    Args:
        level: 政策档位

    Returns:
        List[str]: 建议列表
    """
    response = get_policy_response(level)

    recommendations = [f"当前档位：{response.name} - {response.description}"]

    if level == PolicyLevel.P0:
        recommendations.append("正常运行 Regime 逻辑，无需特殊调整")
    elif level == PolicyLevel.P1:
        recommendations.append(f"建议提升现金权重 {response.cash_adjustment}%")
        recommendations.append("缩短组合久期，降低风险敞口")
    elif level == PolicyLevel.P2:
        recommendations.append(f"暂停交易信号 {response.signal_pause_hours} 小时，等待市场消化")
        recommendations.append(f"提升现金权重至 {response.cash_adjustment}%")
        recommendations.append("密切关注政策落地后的市场反应")
    elif level == PolicyLevel.P3:
        recommendations.append("危机模式！启动人工接管程序")
        recommendations.append("全仓转现金或对冲")
        recommendations.append("等待进一步指示")

    return recommendations


@dataclass(frozen=True)
class PolicyLevelKeywordRule:
    """政策档位关键词规则

    用于从RSS条目标题中自动提取政策档位
    """
    level: PolicyLevel
    keywords: list[str]  # 如 ["降息", "降准"] for P2
    weight: int = 1  # 权重，支持多规则匹配
    category: str | None = None  # 可选：按分类应用不同规则


# 默认关键词规则配置（可通过数据库覆盖）
DEFAULT_KEYWORD_RULES: list[PolicyLevelKeywordRule] = [
    PolicyLevelKeywordRule(
        level=PolicyLevel.P3,
        keywords=["熔断", "紧急", "救市", "危机", "恐慌"],
        weight=1
    ),
    PolicyLevelKeywordRule(
        level=PolicyLevel.P2,
        keywords=["降息", "降准", "加息", "加准", "刺激", "干预", "调整"],
        weight=1
    ),
    PolicyLevelKeywordRule(
        level=PolicyLevel.P1,
        keywords=["酝酿", "研究", "考虑", "拟", "或将", "讨论"],
        weight=1
    ),
]


# ============================================================
# 工作台闸门规则
# ============================================================

from .entities import (
    EventType,
    GateLevel,
    IngestionConfig,
    SentimentGateThresholds,
)


def calculate_gate_level(
    heat_score: float | None,
    sentiment_score: float | None,
    config: SentimentGateThresholds
) -> GateLevel:
    """
    计算热点情绪闸门等级（纯函数）

    规则：热度或情绪任一触发即升级
    - L3: 热度>=L3阈值 OR 情绪<=L3阈值
    - L2: 热度>=L2阈值 OR 情绪<=L2阈值
    - L1: 热度>=L1阈值 OR 情绪<=L1阈值
    - L0: 其他情况

    Args:
        heat_score: 热度评分 (0-100)，None 表示无数据
        sentiment_score: 情绪评分 (-1.0 ~ +1.0)，None 表示无数据
        config: 闸门阈值配置

    Returns:
        GateLevel: 计算出的闸门等级
    """
    # 如果都没有数据，返回正常状态
    if heat_score is None and sentiment_score is None:
        return GateLevel.L0

    # L3 检查（最严格）
    if heat_score is not None and heat_score >= config.heat_l3_threshold:
        return GateLevel.L3
    if sentiment_score is not None and sentiment_score <= config.sentiment_l3_threshold:
        return GateLevel.L3

    # L2 检查
    if heat_score is not None and heat_score >= config.heat_l2_threshold:
        return GateLevel.L2
    if sentiment_score is not None and sentiment_score <= config.sentiment_l2_threshold:
        return GateLevel.L2

    # L1 检查
    if heat_score is not None and heat_score >= config.heat_l1_threshold:
        return GateLevel.L1
    if sentiment_score is not None and sentiment_score <= config.sentiment_l1_threshold:
        return GateLevel.L1

    # 默认正常
    return GateLevel.L0


def should_auto_approve(
    policy_level: PolicyLevel,
    ai_confidence: float | None,
    config: IngestionConfig
) -> tuple[bool, str]:
    """
    判断是否应自动生效（纯函数）

    规则：
    1. 自动生效开关必须开启
    2. 档位必须满足最低要求（如 P2/P3）
    3. AI 置信度必须达到阈值

    Args:
        policy_level: 政策档位
        ai_confidence: AI 置信度 (0.0-1.0)
        config: 摄入配置

    Returns:
        tuple[bool, str]: (是否自动生效, 原因说明)
    """
    # 检查开关
    if not config.auto_approve_enabled:
        return False, "自动生效功能未启用"

    # 检查置信度
    if ai_confidence is None:
        return False, "缺少 AI 置信度"
    if ai_confidence < config.auto_approve_threshold:
        return False, f"AI 置信度 {ai_confidence:.2f} 低于阈值 {config.auto_approve_threshold}"

    # 检查档位
    level_order = {
        PolicyLevel.P0: 0,
        PolicyLevel.P1: 1,
        PolicyLevel.P2: 2,
        PolicyLevel.P3: 3,
        PolicyLevel.PENDING: -1,
    }
    policy_level_value = level_order.get(policy_level, -1)
    min_level_value = level_order.get(config.auto_approve_min_level, 2)

    if policy_level_value < min_level_value:
        return False, f"档位 {policy_level.value} 低于自动生效最低档位 {config.auto_approve_min_level.value}"

    return True, f"满足自动生效条件：档位 {policy_level.value}，置信度 {ai_confidence:.2f}"


def normalize_sentiment_score(raw_score: float, score_range: tuple = (-3.0, 3.0)) -> float:
    """
    将原始情绪评分归一化为标准范围 (-1.0 ~ +1.0)

    Args:
        raw_score: 原始评分
        score_range: 原始评分范围，默认 (-3.0, 3.0)

    Returns:
        float: 归一化后的评分 (-1.0 ~ +1.0)
    """
    min_val, max_val = score_range
    # 线性归一化到 [-1, 1]
    normalized = 2 * (raw_score - min_val) / (max_val - min_val) - 1
    # 限制在 [-1, 1] 范围内
    return max(-1.0, min(1.0, normalized))


def is_sla_exceeded(
    created_at: datetime,
    policy_level: PolicyLevel,
    config: IngestionConfig,
    now: datetime | None = None
) -> tuple[bool, int]:
    """
    检查是否超出 SLA（纯函数）

    Args:
        created_at: 事件创建时间
        policy_level: 政策档位
        config: 摄入配置
        now: 当前时间（用于测试），默认使用当前时间

    Returns:
        tuple[bool, int]: (是否超出 SLA, 超出小时数)
    """
    from datetime import datetime, timezone

    if now is None:
        now = datetime.now(UTC)

    # 计算经过的小时数
    elapsed = now - created_at
    elapsed_hours = elapsed.total_seconds() / 3600

    # 根据档位确定 SLA
    if policy_level in [PolicyLevel.P2, PolicyLevel.P3]:
        sla_hours = config.p23_sla_hours
    else:
        sla_hours = config.normal_sla_hours

    exceeded_hours = int(elapsed_hours - sla_hours)
    is_exceeded = exceeded_hours > 0

    return is_exceeded, max(0, exceeded_hours)


def get_max_position_cap(gate_level: GateLevel, config: dict) -> float:
    """
    获取闸门等级对应的最大仓位上限

    Args:
        gate_level: 闸门等级
        config: 仓位配置字典，包含 max_position_cap_l2, max_position_cap_l3

    Returns:
        float: 最大仓位比例 (0.0-1.0)，1.0 表示无限制
    """
    if gate_level == GateLevel.L3:
        return config.get('max_position_cap_l3', 0.3)
    elif gate_level == GateLevel.L2:
        return config.get('max_position_cap_l2', 0.7)
    else:
        return 1.0  # L0/L1 无仓位限制


def can_event_affect_policy_level(event_type: EventType) -> bool:
    """
    判断事件类型是否可以影响政策档位

    关键约束：热点情绪闸门不直接修改 P0-P3

    Args:
        event_type: 事件类型

    Returns:
        bool: True 表示可以影响政策档位
    """
    return event_type == EventType.POLICY


def should_event_count_in_gate(event_type: EventType, gate_effective: bool) -> bool:
    """
    判断事件是否应计入闸门状态计算

    Args:
        event_type: 事件类型
        gate_effective: 是否已生效

    Returns:
        bool: True 表示应计入闸门状态
    """
    # 只有已生效的事件才计入
    if not gate_effective:
        return False
    # 热点和情绪事件计入闸门
    return event_type in [EventType.HOTSPOT, EventType.SENTIMENT, EventType.MIXED]
