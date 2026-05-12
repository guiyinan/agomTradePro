"""
Dashboard Application DTOs
"""

from dataclasses import dataclass


@dataclass
class PortfolioSummaryDTO:
    """组合摘要"""
    portfolio_id: int
    total_value: float
    cash_balance: float
    invested_value: float
    invested_ratio: float
    total_return: float
    total_return_pct: float


@dataclass
class PositionSummaryDTO:
    """持仓摘要"""
    id: int
    asset_code: str
    asset_class: str
    region: str
    shares: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
