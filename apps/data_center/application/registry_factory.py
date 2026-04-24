"""
Data Center — Registry Factory

Builds and manages the module-level SourceRegistry singleton.

Capability declarations are derived from source_type so the registry
accurately reflects what each configured provider can supply — even before
any live calls flow through it.  Circuit-breaker state starts at HEALTHY /
UNKNOWN and updates as calls are made.

This factory is intentionally self-contained and does NOT import from
business modules for runtime registration. Business modules depend on
data_center, not the other way around.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.data_center.domain.enums import DataCapability
from apps.data_center.infrastructure.registries.source_registry import SourceRegistry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Singleton — reset with reset_registry() in tests
_global_registry: SourceRegistry | None = None

# ---------------------------------------------------------------------------
# Source-type → capability mapping
# Providers declare which domains they cover based on what the underlying
# API actually supplies.  Err on the side of accuracy over optimism.
# ---------------------------------------------------------------------------
_SOURCE_TYPE_CAPABILITIES: dict[str, list[DataCapability]] = {
    "tushare": [
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
        DataCapability.FUND_NAV,
        DataCapability.FINANCIAL,
        DataCapability.VALUATION,
    ],
    "akshare": [
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
        DataCapability.FUND_NAV,
        DataCapability.FINANCIAL,
        DataCapability.VALUATION,
        DataCapability.SECTOR_MEMBERSHIP,
        DataCapability.NEWS,
        DataCapability.CAPITAL_FLOW,
    ],
    "eastmoney": [
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
        DataCapability.NEWS,
        DataCapability.CAPITAL_FLOW,
    ],
    "qmt": [
        DataCapability.REALTIME_QUOTE,
        DataCapability.HISTORICAL_PRICE,
    ],
    "fred": [
        DataCapability.MACRO,
    ],
    "wind": [
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.FINANCIAL,
        DataCapability.VALUATION,
        DataCapability.SECTOR_MEMBERSHIP,
    ],
    "choice": [
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.FINANCIAL,
    ],
}


class _DbProvider:
    """Lightweight provider stub backed by a DB config row.

    Satisfies ProviderProtocol without importing any gateway library so
    the factory has zero external dependencies.  Real data fetching is
    handled by the data_center provider adapters that call
    record_success / record_failure on this registry.
    """

    def __init__(self, name: str, source_type: str) -> None:
        self._name = name
        self._caps: frozenset[DataCapability] = frozenset(
            _SOURCE_TYPE_CAPABILITIES.get(source_type, [])
        )

    def provider_name(self) -> str:
        return self._name

    def supports(self, cap: DataCapability) -> bool:
        return cap in self._caps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_registry() -> SourceRegistry:
    """Return the module-level SourceRegistry singleton.

    If not yet initialised, builds it from active ProviderConfigModel rows.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = _build_registry()
    return _global_registry


def refresh_registry() -> SourceRegistry:
    """Rebuild the registry from the current DB state and return it.

    Call this after adding / updating provider configs at runtime.
    """
    global _global_registry
    _global_registry = _build_registry()
    return _global_registry


def reset_registry() -> None:
    """Reset to uninitialised state — use in tests only."""
    global _global_registry
    _global_registry = None


# ---------------------------------------------------------------------------
# Internal builder
# ---------------------------------------------------------------------------

def _build_registry() -> SourceRegistry:
    registry = SourceRegistry()
    try:
        from apps.data_center.infrastructure.repositories import ProviderConfigRepository

        for config in ProviderConfigRepository().list_active():
            provider = _DbProvider(config.name, config.source_type)
            if not provider._caps:
                logger.warning(
                    "Provider '%s' (source_type='%s') has no mapped capabilities — skipping",
                    config.name,
                    config.source_type,
                )
                continue
            registry.register(provider, priority=config.priority)
            logger.info(
                "Registered data_center provider '%s' (source_type=%s, priority=%d, caps=%d)",
                config.name,
                config.source_type,
                config.priority,
                len(provider._caps),
            )
    except Exception:
        logger.warning("Failed to build data_center registry from DB", exc_info=True)
    return registry
