"""Runtime registry for asset-analysis market integrations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class MarketAssetRepositoryProtocol(Protocol):
    """Minimal repository contract consumed by asset_analysis."""

    def get_assets_by_filter(
        self,
        asset_type: str,
        filters: dict,
        max_count: int = 100,
    ) -> list[Any]:
        """Return assets matching the given filters."""

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> Any | None:
        """Return one asset by code."""


AssetRepositoryFactory = Callable[[], MarketAssetRepositoryProtocol]
AssetPoolScreener = Callable[[Any, dict[str, Any]], list[Any]]
AssetNameResolver = Callable[[list[str]], dict[str, str]]


@dataclass
class AssetAnalysisMarketRegistry:
    """Runtime registry for asset-analysis integrations."""

    _repository_factories: dict[str, AssetRepositoryFactory] = field(default_factory=dict)
    _pool_screeners: dict[str, AssetPoolScreener] = field(default_factory=dict)
    _name_resolvers: dict[str, AssetNameResolver] = field(default_factory=dict)

    def register_asset_repository(
        self,
        asset_type: str,
        factory: AssetRepositoryFactory,
    ) -> None:
        self._repository_factories[asset_type] = factory

    def get_asset_repository(self, asset_type: str) -> MarketAssetRepositoryProtocol:
        try:
            factory = self._repository_factories[asset_type]
        except KeyError as exc:
            raise LookupError(f"No asset repository registered for {asset_type}") from exc
        return factory()

    def register_pool_screener(
        self,
        asset_type: str,
        screener: AssetPoolScreener,
    ) -> None:
        self._pool_screeners[asset_type] = screener

    def get_pool_screener(self, asset_type: str) -> AssetPoolScreener:
        try:
            return self._pool_screeners[asset_type]
        except KeyError as exc:
            raise LookupError(f"No pool screener registered for {asset_type}") from exc

    def register_name_resolver(
        self,
        source_name: str,
        resolver: AssetNameResolver,
    ) -> None:
        self._name_resolvers[source_name] = resolver

    def get_name_resolver(self, source_name: str) -> AssetNameResolver:
        try:
            return self._name_resolvers[source_name]
        except KeyError as exc:
            raise LookupError(f"No name resolver registered for {source_name}") from exc

    def clear(self) -> None:
        self._repository_factories.clear()
        self._pool_screeners.clear()
        self._name_resolvers.clear()


_registry: AssetAnalysisMarketRegistry | None = None


def get_asset_analysis_market_registry() -> AssetAnalysisMarketRegistry:
    """Return the singleton registry instance."""
    global _registry
    if _registry is None:
        _registry = AssetAnalysisMarketRegistry()
    return _registry
