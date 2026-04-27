"""
Asset eligibility rules owned by the regime module.

This domain module defines the regime x asset eligibility matrix and related
selection helpers. It intentionally contains only standard-library code.
"""

from collections.abc import Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Eligibility(Enum):
    """资产准入等级"""

    PREFERRED = "preferred"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"


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

_eligibility_matrix_provider: Callable[[], dict[str, dict[str, Eligibility]]] | None = None


def set_eligibility_matrix_provider(
    provider: Callable[[], dict[str, dict[str, Eligibility]]],
) -> None:
    """设置准入矩阵提供者（依赖注入）"""

    global _eligibility_matrix_provider
    _eligibility_matrix_provider = provider


def get_eligibility_matrix() -> dict[str, dict[str, Eligibility]]:
    """获取准入矩阵，优先使用注入 provider，否则回退默认矩阵。"""

    provider = _eligibility_matrix_provider
    if provider is not None:
        try:
            return provider()
        except Exception as exc:
            logger.debug("Eligibility matrix provider failed, using default matrix: %s", exc)
    return DEFAULT_ELIGIBILITY_MATRIX


def check_eligibility(
    asset_class: str,
    regime: str,
    custom_matrix: dict[str, dict[str, Eligibility]] | None = None,
) -> Eligibility:
    """检查资产在当前 Regime 下的适配性。"""

    matrix = custom_matrix or get_eligibility_matrix()
    if asset_class not in matrix:
        raise ValueError(f"Unknown asset class: {asset_class}")
    return matrix[asset_class].get(regime, Eligibility.NEUTRAL)


def get_preferred_asset_classes(regime: str) -> list[str]:
    """获取指定 Regime 下推荐的资产类别，PREFERRED 在前，NEUTRAL 在后。"""

    preferred: list[str] = []
    neutral: list[str] = []

    matrix = get_eligibility_matrix()
    for asset_class, regime_map in matrix.items():
        eligibility = regime_map.get(regime, Eligibility.NEUTRAL)
        if eligibility == Eligibility.PREFERRED:
            preferred.append(asset_class)
        elif eligibility == Eligibility.NEUTRAL:
            neutral.append(asset_class)

    return preferred + neutral


__all__ = [
    "DEFAULT_ELIGIBILITY_MATRIX",
    "Eligibility",
    "check_eligibility",
    "get_eligibility_matrix",
    "get_preferred_asset_classes",
    "set_eligibility_matrix_provider",
]
