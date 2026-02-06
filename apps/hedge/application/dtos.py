"""
Hedge Module Application Layer - DTOs

Data Transfer Objects for the hedge module.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


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
    asset_codes: List[str]
    window_days: int = 60


@dataclass
class CorrelationMatrixResponse:
    """Response DTO for correlation matrix"""
    matrix: Dict[str, Dict[str, float]]
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
