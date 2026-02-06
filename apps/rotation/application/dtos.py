"""
Rotation Module Application Layer - DTOs

Data Transfer Objects for the rotation module.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


@dataclass
class RotationSignalRequest:
    """Request DTO for generating rotation signal"""
    config_name: str
    signal_date: Optional[date] = None


@dataclass
class RotationSignalResponse:
    """Response DTO for rotation signal"""
    config_name: str
    signal_date: date
    target_allocation: Dict[str, float]
    current_regime: str
    action_required: str
    reason: str
    momentum_ranking: List[Dict[str, float]]


@dataclass
class AssetComparisonRequest:
    """Request DTO for comparing assets"""
    asset_codes: List[str]
    lookback_days: int = 60


@dataclass
class AssetComparisonResponse:
    """Response DTO for asset comparison"""
    assets: Dict[str, Dict]
    comparison_date: date
