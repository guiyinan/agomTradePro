"""
Eligibility Rules for Investment Signals.

Domain 层纯业务逻辑，只使用 Python 标准库。
"""

from dataclasses import dataclass

from apps.regime.domain.asset_eligibility import (
    Eligibility,
    get_eligibility_matrix,
)
from apps.regime.domain.asset_eligibility import (
    check_eligibility as _check_eligibility,
)

# 证伪逻辑量化关键词
QUANTIFIABLE_KEYWORDS = [
    "跌破", "突破", "低于", "高于", "<", ">", "<=", ">=",
    "低于阈值", "超过阈值", "低于", "超过", "触及",
    "低于前值", "高于前值", "连续回落", "连续上涨",
]

# 必须包含的证伪模式
INVALIDATION_PATTERNS = [
    "跌破", "突破", "<", ">", "低于", "超过",
]


@dataclass(frozen=True)
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class RejectionRecord:
    """拒绝记录"""
    asset_code: str
    asset_class: str
    current_regime: str
    eligibility: Eligibility
    reason: str
    policy_veto: bool = False


def check_eligibility(
    asset_class: str,
    regime: str,
    custom_matrix: dict[str, dict[str, Eligibility]] | None = None
) -> Eligibility:
    """
    检查资产在当前 Regime 下的适配性

    Args:
        asset_class: 资产类别
        regime: 当前 Regime（Recovery/Overheat/Stagflation/Deflation）
        custom_matrix: 自定义准入矩阵（可选，用于测试或特殊场景）

    Returns:
        Eligibility: 适配性等级

    Raises:
        ValueError: 未知的资产类别
    """
    return _check_eligibility(asset_class, regime, custom_matrix)


def validate_invalidation_logic(logic: str) -> ValidationResult:
    """
    验证证伪逻辑的完整性

    Args:
        logic: 证伪逻辑描述

    Returns:
        ValidationResult: 验证结果
    """
    errors = []
    warnings = []

    # 1. 长度检查
    if len(logic) < 10:
        errors.append("证伪逻辑描述过短，至少需要 10 个字符")

    # 2. 检查是否包含可量化关键词
    has_quantifiable = any(kw in logic for kw in QUANTIFIABLE_KEYWORDS)
    if not has_quantifiable:
        errors.append(
            "证伪逻辑必须包含可量化条件，如：'跌破 50'、'突破前值'、'PMI < 50' 等"
        )

    # 3. 检查是否包含明确的证伪模式
    has_pattern = any(p in logic for p in INVALIDATION_PATTERNS)
    if not has_pattern:
        warnings.append("建议使用更明确的证伪描述，如 '跌破'、'突破' 等")

    # 4. 检查是否过于宽泛
    vague_patterns = ["如果", "可能", "或许", "大概"]
    if any(vp in logic for vp in vague_patterns):
        warnings.append("证伪逻辑应避免模糊表述，建议使用明确的量化条件")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def should_reject_signal(
    asset_class: str,
    current_regime: str,
    policy_level: int,
    confidence: float = 0.0
) -> tuple[bool, str | None, Eligibility | None]:
    """
    判断是否应该拒绝信号

    拒绝条件：
    1. 资产在当前 Regime 下为 HOSTILE
    2. 政策档位为 P3（完全退出）

    Args:
        asset_class: 资产类别
        current_regime: 当前 Regime
        policy_level: 政策档位（0-3）
        confidence: Regime 判定置信度

    Returns:
        Tuple[bool, Optional[str], Optional[Eligibility]]:
            (是否拒绝, 拒绝原因, 适配性等级)
    """
    try:
        eligibility = check_eligibility(asset_class, current_regime)
    except ValueError:
        # 未知资产类别，中性处理
        eligibility = Eligibility.NEUTRAL

    # 检查 1: Regime 环境是否敌对
    if eligibility == Eligibility.HOSTILE:
        reason = (
            f"当前 Regime 为 {current_regime}，"
            f"资产 {asset_class} 适配性为 HOSTILE，"
            f"不建议在此环境下下注。"
        )
        return True, reason, eligibility

    # 检查 2: 政策档位是否为 P3（完全退出）
    if policy_level >= 3:
        reason = (
            f"当前政策档位为 P{policy_level}，"
            f"系统处于完全退出状态，"
            f"所有新信号均被拦截。"
        )
        return True, reason, eligibility

    # 检查 3: 低置信度警告
    if confidence > 0 and confidence < 0.3:
        # 低置信度时，NEUTRAL 资产也被拒绝
        if eligibility == Eligibility.NEUTRAL:
            reason = (
                f"当前 Regime 判定置信度较低 ({confidence:.2f})，"
                f"资产 {asset_class} 在 {current_regime} 下仅为 NEUTRAL，"
                f"建议观望。"
            )
            return True, reason, eligibility

    return False, None, eligibility


def create_rejection_record(
    asset_code: str,
    asset_class: str,
    current_regime: str,
    policy_level: int,
    confidence: float
) -> RejectionRecord | None:
    """
    创建拒绝记录

    Args:
        asset_code: 资产代码
        asset_class: 资产类别
        current_regime: 当前 Regime
        policy_level: 政策档位
        confidence: Regime 判定置信度

    Returns:
        Optional[RejectionRecord]: 如果信号被拒绝则返回记录，否则返回 None
    """
    should_reject, reason, eligibility = should_reject_signal(
        asset_class, current_regime, policy_level, confidence
    )

    if should_reject:
        return RejectionRecord(
            asset_code=asset_code,
            asset_class=asset_class,
            current_regime=current_regime,
            eligibility=eligibility,
            reason=reason,
            policy_veto=(policy_level >= 3)
        )

    return None


def get_recommended_asset_classes(regime: str) -> list[str]:
    """
    获取指定 Regime 下推荐的资产类别

    Args:
        regime: Regime 名称

    Returns:
        List[str]: 推荐的资产类别列表（按适配性排序）
    """
    recommended = []
    neutral = []

    matrix = get_eligibility_matrix()
    for asset_class, regime_map in matrix.items():
        eligibility = regime_map.get(regime, Eligibility.NEUTRAL)
        if eligibility == Eligibility.PREFERRED:
            recommended.append(asset_class)
        elif eligibility == Eligibility.NEUTRAL:
            neutral.append(asset_class)

    # PREFERRED 在前，NEUTRAL 在后
    return recommended + neutral


def analyze_regime_transition(
    from_regime: str,
    to_regime: str
) -> list[str]:
    """
    分析 Regime 转换对资产的影响

    Args:
        from_regime: 原始 Regime
        to_regime: 目标 Regime

    Returns:
        List[str]: 影响描述列表
    """
    impacts = []

    matrix = get_eligibility_matrix()
    for asset_class in matrix.keys():
        from_elig = check_eligibility(asset_class, from_regime)
        to_elig = check_eligibility(asset_class, to_regime)

        if from_elig != to_elig:
            if from_elig == Eligibility.HOSTILE and to_elig == Eligibility.PREFERRED:
                impacts.append(f"{asset_class}: 从敌对转为优选，可考虑入场")
            elif from_elig == Eligibility.PREFERRED and to_elig == Eligibility.HOSTILE:
                impacts.append(f"{asset_class}: 从优选转为敌对，建议退出")
            elif to_elig == Eligibility.HOSTILE:
                impacts.append(f"{asset_class}: 环境转为敌对，谨慎对待")
            elif to_elig == Eligibility.PREFERRED:
                impacts.append(f"{asset_class}: 环境转为优选，可关注机会")

    return impacts
