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
    signal_date: date | None = None


@dataclass
class RotationSignalResponse:
    """Response DTO for rotation signal"""
    config_name: str
    signal_date: date
    target_allocation: dict[str, float]
    current_regime: str
    action_required: str
    reason: str
    momentum_ranking: list[dict[str, float]]


@dataclass
class AssetComparisonRequest:
    """Request DTO for comparing assets"""
    asset_codes: list[str]
    lookback_days: int = 60


@dataclass
class AssetComparisonResponse:
    """Response DTO for asset comparison"""
    assets: dict[str, dict]
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
    assets: list[dict]
    categories: dict[str, dict]
    momentum_scores: dict[str, AssetMomentumScore]
    latest_calc_date: date | None
    maintenance_notice: str = ""


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
    target_allocation: dict[str, float]


@dataclass
class RotationConfigsViewResponse:
    """Response DTO for rotation configs view page"""
    configs: list[dict]
    latest_signals: dict[int, ConfigLatestSignal]
    strategy_types: list[tuple]
    frequencies: list[str]


@dataclass
class RotationSignalsViewRequest:
    """Request DTO for rotation signals view page"""
    config_filter: str = ''
    regime_filter: str = ''
    action_filter: str = ''


@dataclass
class RotationSignalsViewResponse:
    """Response DTO for rotation signals view page"""
    signals: list[dict]
    configs: list[dict]
    latest_by_config: dict[int, dict]
    current_regime: str | None
    regime_choices: list[str]
    action_choices: list[str]
    filter_config: str
    filter_regime: str
    filter_action: str
