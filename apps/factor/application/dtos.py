"""
Factor Module Application Layer - DTOs

Data Transfer Objects for the factor module.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class FactorCalculationRequest:
    """Request DTO for factor calculation"""
    trade_date: date
    universe: List[str]  # Stock universe
    factor_codes: List[str]  # Factors to calculate


@dataclass
class FactorScoreResponse:
    """Response DTO for factor scores"""
    stock_code: str
    stock_name: str
    composite_score: float
    percentile_rank: float
    factor_scores: Dict[str, float]
    sector: str
    market_cap: Optional[Decimal]


@dataclass
class FactorPortfolioRequest:
    """Request DTO for creating a factor portfolio"""
    config_name: str
    trade_date: date
    top_n: Optional[int] = None


@dataclass
class FactorPortfolioResponse:
    """Response DTO for factor portfolio"""
    config_name: str
    trade_date: date
    holdings: List[Dict]
    total_weight: float
