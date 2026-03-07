"""
Asset Price Adapters for Backtest Module.
"""

from .base import (
    AssetPriceAdapterProtocol,
    BaseAssetPriceAdapter,
    AssetPricePoint,
    AssetPriceUnavailableError,
    AssetPriceValidationError,
    get_asset_class_tickers,
)
from .tushare_price_adapter import TushareAssetPriceAdapter
from .composite_price_adapter import CompositeAssetPriceAdapter

__all__ = [
    'AssetPriceAdapterProtocol',
    'BaseAssetPriceAdapter',
    'AssetPricePoint',
    'AssetPriceUnavailableError',
    'AssetPriceValidationError',
    'get_asset_class_tickers',
    'TushareAssetPriceAdapter',
    'CompositeAssetPriceAdapter',
]
