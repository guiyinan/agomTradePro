"""
Policy Response Rules - Domain Layer

定义政策档位的响应规则。
本层只使用 Python 标准库，不依赖 Django 或外部库。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

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
    signal_pause_hours: Optional[int]  # 暂停信号时长（小时）
    requires_manual_approval: bool  # 是否需要人工审批
    alert_triggered: bool  # 是否触发告警


# 政策档位响应规则配置
POLICY_RESPONSE_RULES: Dict[PolicyLevel, PolicyResponse] = {
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


def get_signal_pause_duration_hours(level: PolicyLevel) -> Optional[int]:
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
) -> tuple[bool, List[str]]:
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
    from_level: Optional[PolicyLevel]
    to_level: PolicyLevel
    transition_date: str  # ISO 格式日期字符串
    is_upgrade: bool  # 是否升级（P0->P1, P1->P2 等）


def analyze_policy_transition(
    from_level: Optional[PolicyLevel],
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


def get_recommendations_for_level(level: PolicyLevel) -> List[str]:
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
    keywords: List[str]  # 如 ["降息", "降准"] for P2
    weight: int = 1  # 权重，支持多规则匹配
    category: Optional[str] = None  # 可选：按分类应用不同规则


# 默认关键词规则配置（可通过数据库覆盖）
DEFAULT_KEYWORD_RULES: List[PolicyLevelKeywordRule] = [
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
