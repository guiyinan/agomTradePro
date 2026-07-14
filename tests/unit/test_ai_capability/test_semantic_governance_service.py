"""Application tests for semantic-key governance inspection and correction."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.ai_capability.application.semantic_governance import (
    SemanticGovernanceService,
)
from apps.ai_capability.domain.entities import CapabilityDefinition, SourceType
from apps.ai_capability.domain.semantic_governance import (
    SemanticAuditEntry,
    SemanticBatchPersistence,
    SemanticCatalogCapability,
    SemanticCorrection,
    SemanticCorrectionBatch,
)


def _capability(
    capability_key: str,
    semantic_key: str,
    *,
    source_type: SourceType = SourceType.API,
    priority_weight: float = 1.0,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_key=capability_key,
        source_type=source_type,
        source_ref=capability_key,
        name=capability_key,
        summary=capability_key,
        semantic_key=semantic_key,
        priority_weight=priority_weight,
    )


class FakeSemanticGovernanceRepository:
    """In-memory Protocol implementation that records persistence calls."""

    def __init__(self) -> None:
        self.capabilities = [
            _capability("api.shared", "semantic.shared", priority_weight=2.0),
            _capability(
                "mcp.shared",
                "semantic.shared",
                source_type=SourceType.MCP_TOOL,
            ),
            _capability("api.missing", ""),
        ]
        self.overrides = {"removed.capability": "semantic.orphan"}
        self.apply_calls: list[tuple] = []
        self.audit_calls: list[tuple[int, str | None]] = []
        self.audit_entries: tuple[SemanticAuditEntry, ...] = ()

    def list_semantic_catalog(self) -> list[SemanticCatalogCapability]:
        return [
            SemanticCatalogCapability(
                capability=capability,
                collected_semantic_key=capability.semantic_key,
            )
            for capability in self.capabilities
        ]

    def list_active_overrides(self) -> dict[str, str]:
        return dict(self.overrides)

    def apply_batch(self, batch, *, operator_id, snapshots):
        self.apply_calls.append((batch, operator_id, snapshots))
        batch_id = uuid4()
        entries = tuple(
            SemanticAuditEntry(
                batch_id=batch_id,
                idempotency_key=batch.idempotency_key,
                capability_key=correction.capability_key,
                action=correction.action,
                old_collected_value=snapshots[
                    correction.capability_key
                ].collected_semantic_key,
                old_effective_value=snapshots[
                    correction.capability_key
                ].effective_semantic_key,
                new_effective_value=(
                    correction.semantic_key
                    if correction.action == "set"
                    else snapshots[correction.capability_key].collected_semantic_key
                )
                or "",
                reason=batch.reason,
                operator_id=operator_id,
                request_fingerprint="f" * 64,
                created_at=datetime.now(UTC),
            )
            for correction in batch.corrections
        )
        return SemanticBatchPersistence(batch_id, "f" * 64, False, entries)

    def list_semantic_audit(self, *, limit=100, capability_key=None):
        self.audit_calls.append((limit, capability_key))
        return self.audit_entries


def test_inspect_reports_missing_conflicting_and_orphaned_groups() -> None:
    """Inspection reflects effective keys and never hides orphan overrides."""

    snapshot = SemanticGovernanceService(
        FakeSemanticGovernanceRepository()
    ).inspect()

    assert snapshot.missing_capability_keys == ("api.missing",)
    assert snapshot.conflicts == {
        "semantic.shared": ("api.shared", "mcp.shared")
    }
    assert snapshot.orphaned_override_keys == ("removed.capability",)


def test_preview_is_zero_write_and_projects_entrypoint_winners() -> None:
    """Preview returns effective changes and winners without persistence."""

    repository = FakeSemanticGovernanceRepository()
    service = SemanticGovernanceService(repository)
    batch = SemanticCorrectionBatch(
        "preview-001",
        "Separate duplicate semantics",
        (SemanticCorrection("mcp.shared", "set", "semantic.mcp_shared"),),
    )

    result = service.preview(batch)

    assert repository.apply_calls == []
    assert result.replayed is False
    assert result.corrections[0].old_effective_value == "semantic.shared"
    assert result.corrections[0].new_effective_value == "semantic.mcp_shared"
    assert result.corrections[0].projected_winners == {
        "web": None,
        "terminal": "mcp.shared",
        "agent": "mcp.shared",
    }


def test_preview_allows_removing_an_orphan_but_rejects_unknown_set() -> None:
    """Operators can clean orphan evidence but cannot invent catalog entries."""

    service = SemanticGovernanceService(FakeSemanticGovernanceRepository())
    removal = service.preview(
        SemanticCorrectionBatch(
            "preview-orphan",
            "Remove orphan",
            (SemanticCorrection("removed.capability", "remove"),),
        )
    )

    assert removal.corrections[0].old_effective_value == "semantic.orphan"
    assert removal.corrections[0].new_effective_value == ""

    with pytest.raises(ValueError, match="unknown capability"):
        service.preview(
            SemanticCorrectionBatch(
                "preview-unknown",
                "Invalid set",
                (SemanticCorrection("unknown.capability", "set", "semantic.new"),),
            )
        )


def test_apply_revalidates_and_delegates_one_transactional_batch() -> None:
    """Apply builds source snapshots and delegates exactly once."""

    repository = FakeSemanticGovernanceRepository()
    service = SemanticGovernanceService(repository)
    batch = SemanticCorrectionBatch(
        "apply-001",
        "Correct one semantic key",
        (SemanticCorrection("mcp.shared", "set", "semantic.mcp_shared"),),
    )

    result = service.apply(batch, operator_id=42)

    assert result.batch_id is not None
    assert len(repository.apply_calls) == 1
    applied_batch, operator_id, snapshots = repository.apply_calls[0]
    assert applied_batch == batch
    assert operator_id == 42
    assert snapshots["mcp.shared"].collected_semantic_key == "semantic.shared"
    assert snapshots["mcp.shared"].effective_semantic_key == "semantic.shared"


def test_list_audit_delegates_bounded_filters() -> None:
    """Audit queries remain repository-bounded and capability-filterable."""

    repository = FakeSemanticGovernanceRepository()
    service = SemanticGovernanceService(repository)

    assert service.list_audit(limit=25, capability_key="api.shared") == ()
    assert repository.audit_calls == [(25, "api.shared")]
