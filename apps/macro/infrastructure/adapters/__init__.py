"""
External API Adapters for Macro Data.

Exports:
    - TushareAdapter: Tushare Pro 数据源
    - AKShareAdapter: AKShare 数据源
    - FailoverAdapter: 容错切换适配器
    - MultiSourceAdapter: 多源聚合适配器
    - create_default_adapter: 创建默认适配器工厂函数
"""

from collections.abc import Iterator, Mapping

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


class _PublicationLagView(Mapping[str, PublicationLag]):
    """Read-only compatibility view backed by runtime metadata."""

    def _data(self) -> dict[str, PublicationLag]:
        return get_publication_lags()

    def __getitem__(self, key: str) -> PublicationLag:
        return self._data()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())


PUBLICATION_LAGS = _PublicationLagView()

__all__ = [
    # Protocol
    "MacroAdapterProtocol",
    # Base
    "BaseMacroAdapter",
    # Data Models
    "MacroDataPoint",
    "PublicationLag",
    "get_publication_lags",
    "PUBLICATION_LAGS",
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
