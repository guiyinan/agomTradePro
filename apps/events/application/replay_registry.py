"""Application registry for explicitly approved event replay targets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from apps.events.domain.entities import EventHandler, EventType


@dataclass(frozen=True)
class ReplayTarget:
    """One stable replay target and its declared side effects."""

    key: str
    supported_event_types: tuple[EventType, ...]
    side_effect_description: str
    factory: Callable[[], EventHandler]


class ReplayTargetRegistry:
    """Resolve only composition-time replay targets by stable key."""

    def __init__(self, targets: list[ReplayTarget]) -> None:
        self._targets = {target.key: target for target in targets}
        if len(self._targets) != len(targets):
            raise ValueError("Duplicate replay target key.")

    def keys(self) -> tuple[str, ...]:
        """Return stable target keys in deterministic order."""

        return tuple(sorted(self._targets))

    def list_targets(self) -> tuple[ReplayTarget, ...]:
        """Return target metadata in deterministic order."""

        return tuple(self._targets[key] for key in self.keys())

    def resolve(self, key: str) -> ReplayTarget:
        """Resolve a target or reject non-registry input."""

        normalized = str(key or "").strip()
        if not normalized:
            raise ValueError("Replay target key is required.")
        try:
            return self._targets[normalized]
        except KeyError as exc:
            raise KeyError(f"Unknown replay target: {normalized}") from exc

    def resolve_for_event(self, key: str, event_type: EventType) -> ReplayTarget:
        """Resolve a target and validate its declared event compatibility."""

        target = self.resolve(key)
        if event_type not in target.supported_event_types:
            raise ValueError(
                f"Replay target {target.key} does not support {event_type.value}."
            )
        return target
