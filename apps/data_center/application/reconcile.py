"""Deterministic desired-state reconciliation ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DesiredStateEntry:
    """One versioned runtime catalog entry."""

    key: str
    version: str
    owner: str
    content_hash: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.key, self.version, self.owner, self.content_hash)):
            raise ValueError("DesiredStateEntry identifiers cannot be empty")


@dataclass(frozen=True)
class ReconcileResult:
    """Deterministic diff between desired and observed state."""

    missing: tuple[str, ...]
    drifted: tuple[str, ...]
    extra: tuple[str, ...]
    applied: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        """Return whether observed state exactly matches desired state."""

        return not self.missing and not self.drifted and not self.extra


class DesiredStateSink(Protocol):
    """Idempotent sink for one runtime catalog family."""

    def apply(self, entry: DesiredStateEntry) -> None: ...


class ReconcileRuntimeCatalogUseCase:
    """Compare and optionally apply provider/beat/MCP/TUI desired state."""

    def __init__(self, sink: DesiredStateSink | None = None) -> None:
        self._sink = sink

    def execute(
        self,
        desired: tuple[DesiredStateEntry, ...],
        observed: Mapping[str, str],
        *,
        apply: bool = False,
    ) -> ReconcileResult:
        """Return a stable diff; apply only missing or drifted entries."""

        desired_map = {entry.key: entry for entry in desired}
        missing = tuple(sorted(set(desired_map).difference(observed)))
        drifted = tuple(
            sorted(
                key
                for key, entry in desired_map.items()
                if key in observed and observed[key] != entry.content_hash
            )
        )
        extra = tuple(sorted(set(observed).difference(desired_map)))
        applied: list[str] = []
        if apply and self._sink is not None:
            for key in (*missing, *drifted):
                self._sink.apply(desired_map[key])
                applied.append(key)
        return ReconcileResult(missing, drifted, extra, tuple(applied))


__all__ = [
    "DesiredStateEntry",
    "DesiredStateSink",
    "ReconcileResult",
    "ReconcileRuntimeCatalogUseCase",
]
