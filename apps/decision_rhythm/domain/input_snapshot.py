"""Immutable, replayable decision input snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class DecisionInputSnapshot:
    """Canonical frozen input package for decisions and executions."""

    snapshot_id: str
    schema_version: str
    as_of_time: datetime
    state_hash: str
    pit_manifest_id: str
    components: dict[str, dict[str, Any]]
    portfolio_snapshot_id: str
    config_version: str
    strategy_version: str
    prompt_version: str
    freshness: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    must_not_use: bool = False
    missing_components: tuple[str, ...] = ()
    creation_reason: str = ""
    correlation_id: str = ""
    caller: str = ""

    REQUIRED_COMPONENTS = frozenset(
        {"regime", "policy", "risk", "beta_gate", "decision_rhythm"}
    )

    def verify(self) -> None:
        """Fail closed when evidence is incomplete, late, or tampered with."""

        if self.as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware")
        if not self.pit_manifest_id:
            raise ValueError("pit_manifest_id is required")
        if self.must_not_use:
            raise ValueError("snapshot is marked must_not_use")
        if self.missing_components:
            raise ValueError(f"missing decision components: {', '.join(self.missing_components)}")
        absent = sorted(self.REQUIRED_COMPONENTS - set(self.components))
        if absent:
            raise ValueError(f"missing decision components: {', '.join(absent)}")
        if any(
            isinstance(value, dict) and value.get("is_stale")
            for value in self.freshness.values()
        ):
            raise ValueError("snapshot contains stale decision evidence")
        for name, component in self.components.items():
            if not component.get("version") or not component.get("event_id"):
                raise ValueError(f"component {name} lacks version or event_id")
            raw_time = component.get("as_of_time")
            if raw_time:
                component_time = datetime.fromisoformat(str(raw_time))
                if component_time.tzinfo is None or component_time > self.as_of_time:
                    raise ValueError(f"component {name} is not valid at snapshot as_of_time")
            if component.get("must_not_use"):
                raise ValueError(f"component {name} is marked must_not_use")
        expected = calculate_decision_state_hash(self.canonical_payload())
        if expected != self.state_hash:
            raise ValueError("decision snapshot state_hash mismatch")

    def canonical_payload(self) -> dict[str, Any]:
        """Return fields covered by the state hash."""

        return {
            "schema_version": self.schema_version,
            "as_of_time": self.as_of_time.astimezone(UTC).isoformat(),
            "pit_manifest_id": self.pit_manifest_id,
            "components": self.components,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "config_version": self.config_version,
            "strategy_version": self.strategy_version,
            "prompt_version": self.prompt_version,
            "freshness": self.freshness,
            "quality": self.quality,
            "must_not_use": self.must_not_use,
            "missing_components": list(self.missing_components),
        }


def calculate_decision_state_hash(payload: dict[str, Any]) -> str:
    """Calculate a deterministic SHA-256 digest for decision evidence."""

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
