"""
External API Adapters for Macro Data.

Exports:
    - TushareAdapter: Tushare Pro 数据源
    - AKShareAdapter: AKShare 数据源
    - FailoverAdapter: 容错切换适配器
    - MultiSourceAdapter: 多源聚合适配器
    - create_default_adapter: 创建默认适配器工厂函数
"""

from .akshare_adapter import AKShareAdapter
from .base import (
    BaseMacroAdapter,
    DataSourceUnavailableError,
    DataValidationError,
    MacroAdapterProtocol,
    MacroDataPoint,
    PublicationLag,
    get_publication_lags,
)
from .failover_adapter import (
    FailoverAdapter,
    MultiSourceAdapter,
    create_default_adapter,
)
from .tushare_adapter import TushareAdapter

__all__ = [
    # Protocol
    "MacroAdapterProtocol",
    # Base
    "BaseMacroAdapter",
    # Data Models
    "MacroDataPoint",
    "PublicationLag",
    "get_publication_lags",
    # Exceptions
    "DataSourceUnavailableError",
    "DataValidationError",
    # Adapters
    "TushareAdapter",
    "AKShareAdapter",
    "FailoverAdapter",
    "MultiSourceAdapter",
    # Factory
    "create_default_adapter",
]
