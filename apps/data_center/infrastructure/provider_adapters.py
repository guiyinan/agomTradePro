"""Stable exports for canonical Data Center provider adapters."""

from apps.data_center.infrastructure._provider_adapter_akshare import (
    AkshareUnifiedProviderAdapter,
)
from apps.data_center.infrastructure._provider_adapter_base import BaseUnifiedProviderAdapter
from apps.data_center.infrastructure._provider_adapter_specialized import (
    EastMoneyUnifiedProviderAdapter,
    FredUnifiedProviderAdapter,
    QmtUnifiedProviderAdapter,
    build_unified_provider_adapter,
)
from apps.data_center.infrastructure._provider_adapter_tushare import (
    TushareUnifiedProviderAdapter,
)

__all__ = [
    "AkshareUnifiedProviderAdapter",
    "BaseUnifiedProviderAdapter",
    "EastMoneyUnifiedProviderAdapter",
    "FredUnifiedProviderAdapter",
    "QmtUnifiedProviderAdapter",
    "TushareUnifiedProviderAdapter",
    "build_unified_provider_adapter",
]
