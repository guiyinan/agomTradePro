"""
Domain Layer for Backtest Module.

包含：
- entities: 回测实体（BacktestConfig, BacktestResult, Trade 等）
- services: 回测引擎服务（BacktestEngine, PITDataProcessor 等）
- stock_selection_backtest: 股票筛选回测服务
- alpha_backtest: Alpha 信号回测服务
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
    DataVersion,
    DataVersionHistory,
)

from .services import (
    PITDataProcessor,
    BacktestEngine,
)

from .stock_selection_backtest import (
    StockSelectionBacktestConfig,
    StockSelectionBacktestResult,
    StockSelectionBacktestEngine,
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
    "DataVersion",
    "DataVersionHistory",
    # Services
    "PITDataProcessor",
    "BacktestEngine",
    # Stock Selection Backtest
    "StockSelectionBacktestConfig",
    "StockSelectionBacktestResult",
    "StockSelectionBacktestEngine",
]
