"""Point-in-time data contracts owned by the data center domain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol


class KnowledgeScope(str, Enum):
    """Clock used to decide whether a fact version was knowable."""

    PUBLIC = "public"
    SYSTEM = "system"


class PITQuality(str, Enum):
    """Evidence quality for a point-in-time version."""

    VERIFIED = "verified"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PITFactVersion:
    """An immutable bitemporal fact version returned to research consumers."""

    version_id: int
    dataset: str
    business_key: str
    effective_at: datetime
    effective_to: datetime | None
    available_at: datetime | None
    ingested_at: datetime
    superseded_at: datetime | None
    revision_number: int
    source_record_id: str
    content_hash: str
    pit_quality: PITQuality
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PITDatasetManifest:
    """Immutable evidence describing the exact versions selected by a query."""

    manifest_id: str
    as_of_time: datetime
    knowledge_scope: KnowledgeScope
    calendar_version: str
    query_spec: dict[str, dict[str, Any]]
    selected_versions: tuple[dict[str, Any], ...]
    coverage: dict[str, float]
    missing: tuple[dict[str, Any], ...]
    estimated: tuple[dict[str, Any], ...]
    unknown: tuple[dict[str, Any], ...]
    manifest_hash: str

    @property
    def is_verified(self) -> bool:
        """Return whether the manifest is eligible for trusted research."""

        return (
            bool(self.selected_versions)
            and bool(self.coverage)
            and all(value >= 1.0 for value in self.coverage.values())
            and not self.missing
            and not self.estimated
            and not self.unknown
            and self.manifest_hash == calculate_pit_manifest_hash(self)
        )


def calculate_pit_manifest_hash(manifest: PITDatasetManifest) -> str:
    """Calculate the canonical digest that seals all manifest evidence."""

    canonical = {
        "as_of_time": manifest.as_of_time.astimezone(UTC).isoformat(),
        "knowledge_scope": manifest.knowledge_scope.value,
        "calendar_version": manifest.calendar_version,
        "query_spec": manifest.query_spec,
        "selected_versions": list(manifest.selected_versions),
        "coverage": manifest.coverage,
        "missing": list(manifest.missing),
        "estimated": list(manifest.estimated),
        "unknown": list(manifest.unknown),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class PITDataView(Protocol):
    """Read-only PIT query contract consumed by backtests and decisions."""

    def query(
        self,
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> list[PITFactVersion]:
        """Return the versions knowable at ``as_of_time``."""
