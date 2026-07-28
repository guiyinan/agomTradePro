"""Catalog routing services for AI capabilities."""

from apps.ai_capability.application.repository_provider import (
    DjangoCapabilityRepository,
)

from ..domain.entities import (
    CapabilityDefinition,
    RoutingContext,
    SourceType,
)
from ..domain.services import (
    CapabilityFilter,
    CapabilityRetrievalScorer,
    CapabilitySemanticDeduper,
    RetrievalScore,
)


class CapabilityRegistryService:
    """System-level capability registry service."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        filter_service: CapabilityFilter | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.filter_service = filter_service or CapabilityFilter()
        self.semantic_deduper = CapabilitySemanticDeduper()

    def get_routable_capabilities(self, context: RoutingContext) -> list[CapabilityDefinition]:
        capabilities = self.capability_repo.get_all_for_routing()
        filtered = self.filter_service.filter_by_context(capabilities, context)
        return self._apply_entrypoint_source_policy(filtered, context)

    def _apply_entrypoint_source_policy(
        self,
        capabilities: list[CapabilityDefinition],
        context: RoutingContext,
    ) -> list[CapabilityDefinition]:
        """Apply entrypoint-specific source preference and MCP de-dup policy."""
        deduped = self.semantic_deduper.deduplicate(
            capabilities,
            entrypoint=context.entrypoint,
        )
        if context.entrypoint in {"web", "chat"}:
            non_mcp = [cap for cap in deduped if cap.source_type != SourceType.MCP_TOOL]
            if non_mcp:
                return non_mcp
            return []
        return deduped


class CapabilityRetrievalService:
    """Deterministic capability retrieval service."""

    def __init__(self, scorer: CapabilityRetrievalScorer | None = None):
        self.scorer = scorer or CapabilityRetrievalScorer()

    def retrieve(
        self,
        capabilities: list[CapabilityDefinition],
        message: str,
        k: int,
    ) -> list[RetrievalScore]:
        return self.scorer.retrieve_top_k(capabilities, message, k=k)


__all__ = ["CapabilityRegistryService", "CapabilityRetrievalService"]
