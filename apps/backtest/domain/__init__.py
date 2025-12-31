"""
Domain Layer for Backtest Module.

包含：
- entities: 回测实体（BacktestConfig, BacktestResult, Trade 等）
- services: 回测引擎服务（BacktestEngine, PITDataProcessor 等）
"""

from .entities import (
    RebalanceFrequency,
    AssetClass,
    BacktestStatus,
    BacktestConfig,
    Trade,
    PortfolioState,
    BacktestResult,
    RebalanceResult,
    AttributionEntry,
    AttributionReport,
    PITDataConfig,
    DEFAULT_PUBLICATION_LAGS,
)

from .services import (
    PITDataProcessor,
    BacktestEngine,
)

__all__ = [
    # Entities
    "RebalanceFrequency",
    "AssetClass",
    "BacktestStatus",
    "BacktestConfig",
    "Trade",
    "PortfolioState",
    "BacktestResult",
    "RebalanceResult",
    "AttributionEntry",
    "AttributionReport",
    "PITDataConfig",
    "DEFAULT_PUBLICATION_LAGS",
    # Services
    "PITDataProcessor",
    "BacktestEngine",
]
