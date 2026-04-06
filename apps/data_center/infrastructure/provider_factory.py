"""Provider factory for Data Center Phase 3."""

from __future__ import annotations

from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    UnifiedDataProviderProtocol,
)
from apps.data_center.infrastructure.provider_adapters import build_unified_provider_adapter


class UnifiedProviderFactory:
    """Instantiate standardized provider adapters from stored configs."""

    def __init__(self, repo: ProviderConfigRepositoryProtocol) -> None:
        self._repo = repo

    def get_by_id(self, provider_id: int) -> UnifiedDataProviderProtocol | None:
        config = self._repo.get_by_id(provider_id)
        if config is None:
            return None
        return build_unified_provider_adapter(config)

    def get_by_name(self, provider_name: str) -> UnifiedDataProviderProtocol | None:
        config = self._repo.get_by_name(provider_name)
        if config is None:
            return None
        return build_unified_provider_adapter(config)
