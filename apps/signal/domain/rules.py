"""
Eligibility Rules for Investment Signals.
"""

from typing import Dict
from .entities import Eligibility


# 准入矩阵配置
ELIGIBILITY_MATRIX: Dict[str, Dict[str, Eligibility]] = {
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


def check_eligibility(asset_class: str, regime: str) -> Eligibility:
    """检查资产在当前 Regime 下的适配性"""
    if asset_class not in ELIGIBILITY_MATRIX:
        raise ValueError(f"Unknown asset class: {asset_class}")
    return ELIGIBILITY_MATRIX[asset_class].get(regime, Eligibility.NEUTRAL)
