"""Read-only catalog query use cases for AI capabilities."""

from typing import Any

from apps.ai_capability.application.repository_provider import (
    DjangoCapabilityRepository,
)

from ..application.dtos import (
    CapabilitySummaryDTO,
)
from ..domain.entities import (
    CapabilityDefinition,
)


class GetCapabilityListUseCase:
    """Use case for getting capability list."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()

    def execute(
        self,
        source_type: str | None = None,
        route_group: str | None = None,
        category: str | None = None,
        enabled_only: bool = True,
    ) -> list[CapabilitySummaryDTO]:
        """Get list of capabilities."""
        capabilities = self.capability_repo.list_capabilities(
            source_type=source_type,
            route_group=route_group,
            category=category,
            enabled_only=enabled_only,
        )

        return [
            CapabilitySummaryDTO(
                capability_key=cap.capability_key,
                name=cap.name,
                summary=cap.summary,
                source_type=cap.source_type.value,
                route_group=cap.route_group.value,
                category=cap.category,
                risk_level=cap.risk_level.value,
                enabled_for_routing=cap.enabled_for_routing,
                requires_confirmation=cap.requires_confirmation,
            )
            for cap in capabilities
        ]


class GetCapabilityDetailUseCase:
    """Use case for getting a capability by key."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()

    def execute(self, capability_key: str) -> CapabilityDefinition | None:
        """Get a single capability definition."""
        return self.capability_repo.get_by_key(capability_key)


class GetCatalogStatsUseCase:
    """Use case for fetching catalog statistics."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()

    def execute(self) -> dict[str, Any]:
        """Get catalog statistics."""
        return self.capability_repo.get_stats()


__all__ = [
    "GetCapabilityListUseCase",
    "GetCapabilityDetailUseCase",
    "GetCatalogStatsUseCase",
]
