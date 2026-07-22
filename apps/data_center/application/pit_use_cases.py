"""Application use cases for immutable PIT manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from apps.data_center.domain.pit import KnowledgeScope, PITDatasetManifest


class PITManifestGateway(Protocol):
    """Persistence boundary for manifest operations."""

    def build(
        self,
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        calendar_version: str,
        query_spec: dict[str, dict[str, Any]],
        required_keys: dict[str, list[str]] | None = None,
    ) -> PITDatasetManifest:
        """Build and persist a manifest."""

    def get(self, manifest_id: str) -> PITDatasetManifest | None:
        """Get a manifest."""

    def list_recent(self, limit: int = 100) -> list[PITDatasetManifest]:
        """List recent manifests."""


@dataclass(frozen=True)
class BuildPITManifestRequest:
    """Validated request for a PIT manifest."""

    as_of_time: datetime
    knowledge_scope: KnowledgeScope
    calendar_version: str
    query_spec: dict[str, dict[str, Any]]
    required_keys: dict[str, list[str]] = field(default_factory=dict)


class BuildPITManifestUseCase:
    """Resolve a query into an immutable evidence manifest."""

    def __init__(self, repository: PITManifestGateway):
        self._repository = repository

    def execute(self, request: BuildPITManifestRequest) -> PITDatasetManifest:
        """Build the requested manifest after time validation."""

        if request.as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware")
        return self._repository.build(
            as_of_time=request.as_of_time,
            knowledge_scope=request.knowledge_scope,
            calendar_version=request.calendar_version,
            query_spec=request.query_spec,
            required_keys=request.required_keys,
        )


class QueryPITManifestUseCase:
    """Read immutable manifests for API and audit consumers."""

    def __init__(self, repository: PITManifestGateway):
        self._repository = repository

    def get(self, manifest_id: str) -> PITDatasetManifest | None:
        """Return one manifest."""

        return self._repository.get(manifest_id)

    def list_recent(self, limit: int = 100) -> list[PITDatasetManifest]:
        """Return recent manifests with a bounded result size."""

        return self._repository.list_recent(max(1, min(limit, 500)))
