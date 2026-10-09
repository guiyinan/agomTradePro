"""
Hedge Module Application Layer - DTOs

Data Transfer Objects for the hedge module.
"""

from dataclasses import dataclass
from datetime import date
from typing import TypedDict


class HedgePairWriteData(TypedDict, total=False):
    """Validated writable hedge configuration fields; defaults belong to the model."""

    name: str
    long_asset: str
    hedge_asset: str
    hedge_method: str
    target_long_weight: float
    target_hedge_weight: float
    rebalance_trigger: float
    correlation_window: int
    min_correlation: float
    max_correlation: float
    correlation_alert_threshold: float
    max_hedge_cost: float
    beta_target: float | None
    is_active: bool


@dataclass
class HedgeEffectivenessRequest:
    """Request DTO for checking hedge effectiveness"""

    pair_name: str
    lookback_days: int = 60


@dataclass
class HedgeEffectivenessResponse:
    """Response DTO for hedge effectiveness"""

    pair_name: str
    correlation: float
    beta: float
    hedge_ratio: float
    hedge_method: str
    effectiveness: float
    rating: str
    recommendation: str


@dataclass
class CorrelationMatrixRequest:
    """Request DTO for correlation matrix"""

    asset_codes: list[str]
    window_days: int = 60


@dataclass
class CorrelationMatrixResponse:
    """Response DTO for correlation matrix"""

    matrix: dict[str, dict[str, float]]
    calc_date: date
    window_days: int


@dataclass
class HedgeAlertResponse:
    """Response DTO for hedge alerts"""

    pair_name: str
    alert_date: date
    alert_type: str
    severity: str
    message: str
    action_required: str
    priority: int
