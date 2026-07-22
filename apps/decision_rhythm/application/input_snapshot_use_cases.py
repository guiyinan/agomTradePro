"""Use cases for building replayable decision input snapshots."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from apps.decision_rhythm.domain.input_snapshot import (
    DecisionInputSnapshot,
    calculate_decision_state_hash,
)


class DecisionSnapshotGateway(Protocol):
    """Persistence boundary for immutable snapshots."""

    def save(self, snapshot: DecisionInputSnapshot) -> DecisionInputSnapshot:
        """Persist a snapshot."""

    def get(self, snapshot_id: str) -> DecisionInputSnapshot | None:
        """Return one snapshot."""


@dataclass(frozen=True)
class BuildDecisionInputSnapshotRequest:
    """Inputs required to freeze one decision state."""

    as_of_time: datetime
    pit_manifest_id: str
    components: dict[str, dict[str, Any]]
    portfolio_snapshot_id: str
    config_version: str
    strategy_version: str
    prompt_version: str = ""
    freshness: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    must_not_use: bool = False
    missing_components: tuple[str, ...] = ()
    creation_reason: str = ""
    correlation_id: str = ""
    caller: str = ""
    schema_version: str = "v1"


class BuildDecisionInputSnapshotUseCase:
    """Freeze decision evidence and reject incomplete or future state."""

    def __init__(self, repository: DecisionSnapshotGateway):
        self._repository = repository

    def execute(self, request: BuildDecisionInputSnapshotRequest) -> DecisionInputSnapshot:
        """Build, verify and persist a deterministic snapshot."""

        if request.as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware")
        canonical_as_of = request.as_of_time.astimezone(UTC)
        payload = {
            "schema_version": request.schema_version,
            "as_of_time": canonical_as_of.isoformat(),
            "pit_manifest_id": request.pit_manifest_id,
            "components": request.components,
            "portfolio_snapshot_id": request.portfolio_snapshot_id,
            "config_version": request.config_version,
            "strategy_version": request.strategy_version,
            "prompt_version": request.prompt_version,
            "freshness": request.freshness,
            "quality": request.quality,
            "must_not_use": request.must_not_use,
            "missing_components": list(request.missing_components),
        }
        state_hash = calculate_decision_state_hash(payload)
        snapshot = DecisionInputSnapshot(
            snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, state_hash).hex,
            state_hash=state_hash,
            **{**request.__dict__, "as_of_time": canonical_as_of},
        )
        snapshot.verify()
        return self._repository.save(snapshot)


class GetDecisionInputSnapshotUseCase:
    """Read and verify a frozen decision package."""

    def __init__(self, repository: DecisionSnapshotGateway):
        self._repository = repository

    def execute(self, snapshot_id: str) -> DecisionInputSnapshot | None:
        """Return a verified snapshot or fail on evidence corruption."""

        snapshot = self._repository.get(snapshot_id)
        if snapshot:
            snapshot.verify()
        return snapshot
