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


@dataclass
class AssetsViewRequest:
    """Request DTO for assets view page"""
    pass


@dataclass
class AssetMomentumScore:
    """DTO for asset momentum score"""
    composite_score: float
    rank: int
    momentum_1m: float
    momentum_3m: float
    momentum_6m: float
    trend_strength: float
    calc_date: date


@dataclass
class AssetsViewResponse:
    """Response DTO for assets view page"""
    assets: List[Dict]
    categories: Dict[str, Dict]
    momentum_scores: Dict[str, AssetMomentumScore]
    latest_calc_date: Optional[date]


@dataclass
class RotationConfigsViewRequest:
    """Request DTO for rotation configs view page"""
    pass


@dataclass
class ConfigLatestSignal:
    """DTO for config's latest signal"""
    signal_date: date
    current_regime: str
    action_required: str
    target_allocation: Dict[str, float]


@dataclass
class RotationConfigsViewResponse:
    """Response DTO for rotation configs view page"""
    configs: List[Dict]
    latest_signals: Dict[int, ConfigLatestSignal]
    strategy_types: List[tuple]
    frequencies: List[str]


@dataclass
class RotationSignalsViewRequest:
    """Request DTO for rotation signals view page"""
    config_filter: str = ''
    regime_filter: str = ''
    action_filter: str = ''


@dataclass
class RotationSignalsViewResponse:
    """Response DTO for rotation signals view page"""
    signals: List[Dict]
    configs: List[Dict]
    latest_by_config: Dict[int, Dict]
    current_regime: Optional[str]
    regime_choices: List[str]
    action_choices: List[str]
    filter_config: str
    filter_regime: str
    filter_action: str
