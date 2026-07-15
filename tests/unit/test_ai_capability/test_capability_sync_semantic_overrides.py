"""Tests that active semantic overrides survive catalog synchronization."""

from __future__ import annotations

from apps.ai_capability.application.semantic_governance import (
    project_semantic_overrides,
)
from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase
from apps.ai_capability.domain.entities import CapabilityDefinition, SourceType


def _collected_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_key="mcp_tool.replay_events",
        source_type=SourceType.MCP_TOOL,
        source_ref="replay_events",
        name="replay_events",
        summary="Replay events",
        semantic_key="legacy.mcp.replay_events",
    )


def test_project_semantic_overrides_preserves_collected_values_immutably() -> None:
    """Projection changes only effective copies and leaves source values intact."""

    collected = _collected_capability()

    projected = project_semantic_overrides(
        [collected],
        {"mcp_tool.replay_events": "events.replay.events"},
    )

    assert collected.semantic_key == "legacy.mcp.replay_events"
    assert projected[0].semantic_key == "events.replay.events"


class FakeSyncCapabilityRepository:
    def __init__(self) -> None:
        self.saved: list[CapabilityDefinition] = []
        self.collected_semantic_keys: dict[str, str] = {}

    def list_active_overrides(self) -> dict[str, str]:
        return {"mcp_tool.replay_events": "events.replay.events"}

    def bulk_upsert(self, capabilities, *, collected_semantic_keys=None):
        self.saved.extend(capabilities)
        self.collected_semantic_keys.update(collected_semantic_keys or {})
        return {"created": len(capabilities), "updated": 0, "total": len(capabilities)}

    def disable_missing(self, source_type, existing_keys):
        return 0


class FakeSyncLogRepository:
    def save(self, log):
        return log


def test_sync_persists_effective_override_instead_of_collected_key() -> None:
    """Sync applies active overrides before handing capabilities to persistence."""

    repository = FakeSyncCapabilityRepository()
    use_case = SyncCapabilitiesUseCase(
        capability_repo=repository,
        sync_log_repo=FakeSyncLogRepository(),
    )
    use_case._sync_mcp_tools = lambda: [_collected_capability()]

    result = use_case.execute(source="mcp_tool")

    assert result.error_count == 0
    assert repository.saved[0].semantic_key == "events.replay.events"
    assert repository.collected_semantic_keys == {
        "mcp_tool.replay_events": "legacy.mcp.replay_events"
    }
