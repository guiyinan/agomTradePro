"""Application orchestration for semantic-key governance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from apps.ai_capability.domain.entities import CapabilityDefinition
from apps.ai_capability.domain.semantic_governance import (
    SemanticAuditEntry,
    SemanticBatchPersistence,
    SemanticCatalogCapability,
    SemanticCorrectionBatch,
    SemanticValueSnapshot,
    canonical_batch_fingerprint,
)
from apps.ai_capability.domain.services import CapabilitySemanticDeduper


class SemanticGovernanceRepositoryProtocol(Protocol):
    """Persistence and catalog reads required by semantic governance."""

    def list_semantic_catalog(self) -> list[SemanticCatalogCapability]:
        """Return catalog definitions with collected semantic evidence."""

    def list_active_overrides(self) -> dict[str, str]:
        """Return active overrides keyed by capability key."""

    def apply_batch(
        self,
        batch: SemanticCorrectionBatch,
        *,
        operator_id: int,
        snapshots: Mapping[str, SemanticValueSnapshot],
    ) -> SemanticBatchPersistence:
        """Persist a correction batch atomically."""

    def list_semantic_audit(
        self,
        *,
        limit: int = 100,
        capability_key: str | None = None,
    ) -> tuple[SemanticAuditEntry, ...]:
        """Return immutable audit evidence."""


@dataclass(frozen=True)
class SemanticGovernanceSnapshot:
    """Current missing, conflicting, and orphaned semantic governance state."""

    missing_capability_keys: tuple[str, ...]
    conflicts: dict[str, tuple[str, ...]]
    orphaned_override_keys: tuple[str, ...]


@dataclass(frozen=True)
class SemanticCorrectionPreview:
    """Projected impact for one ordered correction."""

    capability_key: str
    action: str
    old_collected_value: str
    old_effective_value: str
    new_effective_value: str
    projected_winners: dict[str, str | None]


@dataclass(frozen=True)
class SemanticBatchResult:
    """Previewed or persisted semantic governance batch result."""

    batch_id: UUID | None
    request_fingerprint: str
    replayed: bool
    corrections: tuple[SemanticCorrectionPreview, ...]


def project_semantic_overrides(
    capabilities: list[CapabilityDefinition],
    overrides: Mapping[str, str],
) -> list[CapabilityDefinition]:
    """Return immutable capability copies with active overrides projected."""

    return [
        replace(
            capability,
            semantic_key=overrides.get(
                capability.capability_key,
                capability.semantic_key,
            ),
        )
        for capability in capabilities
    ]


class SemanticGovernanceService:
    """Inspect, preview, apply, and audit semantic-key corrections."""

    _ENTRYPOINTS = ("web", "terminal", "agent")

    def __init__(self, repository: SemanticGovernanceRepositoryProtocol):
        self.repository = repository
        self.deduper = CapabilitySemanticDeduper()

    def inspect(self) -> SemanticGovernanceSnapshot:
        """Return missing, conflicting, and orphaned effective groups."""

        entries, overrides = self._load_state()
        capabilities = self._project_entries(entries, overrides)
        groups: dict[str, list[str]] = {}
        missing: list[str] = []
        for capability in capabilities:
            if not capability.semantic_key:
                missing.append(capability.capability_key)
                continue
            groups.setdefault(capability.semantic_key, []).append(
                capability.capability_key
            )
        conflicts = {
            semantic_key: tuple(sorted(capability_keys))
            for semantic_key, capability_keys in sorted(groups.items())
            if len(capability_keys) > 1
        }
        catalog_keys = {
            entry.capability.capability_key for entry in entries
        }
        orphaned = tuple(sorted(set(overrides) - catalog_keys))
        return SemanticGovernanceSnapshot(
            missing_capability_keys=tuple(sorted(missing)),
            conflicts=conflicts,
            orphaned_override_keys=orphaned,
        )

    def preview(self, batch: SemanticCorrectionBatch) -> SemanticBatchResult:
        """Project a bounded correction batch without persistence."""

        result, _ = self._build_preview(batch)
        return result

    def apply(
        self,
        batch: SemanticCorrectionBatch,
        *,
        operator_id: int,
    ) -> SemanticBatchResult:
        """Revalidate and persist one semantic correction batch."""

        preview, snapshots = self._build_preview(batch)
        persisted = self.repository.apply_batch(
            batch,
            operator_id=operator_id,
            snapshots=snapshots,
        )
        projected_by_key = {
            correction.capability_key: correction
            for correction in preview.corrections
        }
        persisted_corrections = tuple(
            replace(
                projected_by_key[entry.capability_key],
                action=entry.action,
                old_collected_value=entry.old_collected_value,
                old_effective_value=entry.old_effective_value,
                new_effective_value=entry.new_effective_value,
            )
            for entry in persisted.entries
        )
        return SemanticBatchResult(
            batch_id=persisted.batch_id,
            request_fingerprint=persisted.request_fingerprint,
            replayed=persisted.replayed,
            corrections=persisted_corrections,
        )

    def list_audit(
        self,
        *,
        limit: int = 100,
        capability_key: str | None = None,
    ) -> tuple[SemanticAuditEntry, ...]:
        """Return immutable audit evidence through the repository boundary."""

        return self.repository.list_semantic_audit(
            limit=limit,
            capability_key=capability_key,
        )

    def _build_preview(
        self,
        batch: SemanticCorrectionBatch,
    ) -> tuple[SemanticBatchResult, dict[str, SemanticValueSnapshot]]:
        entries, overrides = self._load_state()
        entries_by_key = {
            entry.capability.capability_key: entry for entry in entries
        }
        projected_overrides = dict(overrides)
        snapshots: dict[str, SemanticValueSnapshot] = {}

        for correction in batch.corrections:
            entry = entries_by_key.get(correction.capability_key)
            if entry is None and correction.action == "set":
                raise ValueError(
                    f"unknown capability: {correction.capability_key}"
                )
            if entry is None and correction.capability_key not in overrides:
                raise ValueError(
                    f"unknown capability or override: {correction.capability_key}"
                )

            collected = entry.collected_semantic_key if entry is not None else ""
            effective = overrides.get(correction.capability_key, collected)
            snapshots[correction.capability_key] = SemanticValueSnapshot(
                capability_key=correction.capability_key,
                collected_semantic_key=collected,
                effective_semantic_key=effective,
            )
            if correction.action == "set":
                projected_overrides[correction.capability_key] = (
                    correction.semantic_key or ""
                )
            else:
                projected_overrides.pop(correction.capability_key, None)

        projected_capabilities = self._project_entries(
            entries,
            projected_overrides,
        )
        previews: list[SemanticCorrectionPreview] = []
        for correction in batch.corrections:
            snapshot = snapshots[correction.capability_key]
            new_effective = (
                correction.semantic_key or ""
                if correction.action == "set"
                else snapshot.collected_semantic_key
            )
            previews.append(
                SemanticCorrectionPreview(
                    capability_key=correction.capability_key,
                    action=correction.action,
                    old_collected_value=snapshot.collected_semantic_key,
                    old_effective_value=snapshot.effective_semantic_key,
                    new_effective_value=new_effective,
                    projected_winners=self._project_winners(
                        projected_capabilities,
                        semantic_key=new_effective,
                    ),
                )
            )

        return (
            SemanticBatchResult(
                batch_id=None,
                request_fingerprint=canonical_batch_fingerprint(batch),
                replayed=False,
                corrections=tuple(previews),
            ),
            snapshots,
        )

    def _load_state(
        self,
    ) -> tuple[list[SemanticCatalogCapability], dict[str, str]]:
        return (
            self.repository.list_semantic_catalog(),
            self.repository.list_active_overrides(),
        )

    @staticmethod
    def _project_entries(
        entries: list[SemanticCatalogCapability],
        overrides: Mapping[str, str],
    ) -> list[CapabilityDefinition]:
        collected_capabilities = [
            replace(
                entry.capability,
                semantic_key=entry.collected_semantic_key,
            )
            for entry in entries
        ]
        return project_semantic_overrides(collected_capabilities, overrides)

    def _project_winners(
        self,
        capabilities: list[CapabilityDefinition],
        *,
        semantic_key: str,
    ) -> dict[str, str | None]:
        if not semantic_key:
            return dict.fromkeys(self._ENTRYPOINTS)
        winners: dict[str, str | None] = {}
        for entrypoint in self._ENTRYPOINTS:
            deduped = self.deduper.deduplicate(
                capabilities,
                entrypoint=entrypoint,
            )
            winner = next(
                (
                    capability.capability_key
                    for capability in deduped
                    if capability.semantic_key == semantic_key
                ),
                None,
            )
            winners[entrypoint] = winner
        return winners
