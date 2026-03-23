"""
Shared Asset Eligibility Rules.

这个模块定义了资产准入矩阵和相关规则，是跨 app 共享的 Domain 层逻辑。
符合四层架构：Domain 层只使用 Python 标准库。
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Eligibility(Enum):
    """资产准入等级"""
    PREFERRED = "preferred"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"


# 默认准入矩阵配置（fallback）
DEFAULT_ELIGIBILITY_MATRIX: dict[str, dict[str, Eligibility]] = {
    "a_share_growth": {
        "Recovery": Eligibility.PREFERRED,
        "Overheat": Eligibility.NEUTRAL,
        "Stagflation": Eligibility.HOSTILE,
        "Deflation": Eligibility.NEUTRAL,
    },
    "a_share_value": {
        "Recovery": Eligibility.PREFERRED,
        "Overheat": Eligibility.PREFERRED,
        "Stagflation": Eligibility.NEUTRAL,
        "Deflation": Eligibility.HOSTILE,
    },
    "china_bond": {
        "Recovery": Eligibility.NEUTRAL,
        "Overheat": Eligibility.HOSTILE,
        "Stagflation": Eligibility.NEUTRAL,
        "Deflation": Eligibility.PREFERRED,
    },
    "gold": {
        "Recovery": Eligibility.NEUTRAL,
        "Overheat": Eligibility.PREFERRED,
        "Stagflation": Eligibility.PREFERRED,
        "Deflation": Eligibility.NEUTRAL,
    },
    "commodity": {
        "Recovery": Eligibility.NEUTRAL,
        "Overheat": Eligibility.PREFERRED,
        "Stagflation": Eligibility.HOSTILE,
        "Deflation": Eligibility.HOSTILE,
    },
    "cash": {
        "Recovery": Eligibility.HOSTILE,
        "Overheat": Eligibility.NEUTRAL,
        "Stagflation": Eligibility.PREFERRED,
        "Deflation": Eligibility.NEUTRAL,
    },
}

# 可配置的准入矩阵（可通过依赖注入设置）
_eligibility_matrix_provider: Callable[[], dict[str, dict[str, Eligibility]]] | None = None


def set_eligibility_matrix_provider(provider: Callable[[], dict[str, dict[str, Eligibility]]]):
    """
    设置准入矩阵提供者（依赖注入）

    Args:
        provider: 返回准入矩阵的函数
    """
    global _eligibility_matrix_provider
    _eligibility_matrix_provider = provider


def get_eligibility_matrix() -> dict[str, dict[str, Eligibility]]:
    """
    获取准入矩阵（优先使用提供者，否则使用默认值）

    Returns:
        准入矩阵字典
    """
    global _eligibility_matrix_provider
    if _eligibility_matrix_provider:
        try:
            return _eligibility_matrix_provider()
        except Exception:
            # 提供者失败，使用默认值
            pass
    return DEFAULT_ELIGIBILITY_MATRIX


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
    # 优先使用自定义矩阵，其次使用提供者，最后使用默认值
    matrix = custom_matrix or get_eligibility_matrix()

    if asset_class not in matrix:
        raise ValueError(f"Unknown asset class: {asset_class}")
    return matrix[asset_class].get(regime, Eligibility.NEUTRAL)


def get_preferred_asset_classes(regime: str) -> list[str]:
    """
    获取指定 Regime 下推荐的资产类别

    Args:
        regime: Regime 名称

    Returns:
        List[str]: 推荐的资产类别列表（PREFERRED 在前，NEUTRAL 在后）
    """
    preferred = []
    neutral = []

    matrix = get_eligibility_matrix()
    for asset_class, regime_map in matrix.items():
        eligibility = regime_map.get(regime, Eligibility.NEUTRAL)
        if eligibility == Eligibility.PREFERRED:
            preferred.append(asset_class)
        elif eligibility == Eligibility.NEUTRAL:
            neutral.append(asset_class)

    # PREFERRED 在前，NEUTRAL 在后
    return preferred + neutral
