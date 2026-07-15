"""Pure request normalization and outcome classification for event replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from .entities import EventType


@dataclass(frozen=True)
class ReplayFilter:
    """Bounded, deterministic event selection for one explicit event type."""

    event_type: EventType
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = 100

    MAX_LIMIT: ClassVar[int] = 1000
    MAX_RANGE: ClassVar[timedelta] = timedelta(days=31)

    def __post_init__(self) -> None:
        for value in (self.start_at, self.end_at):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError("Replay timestamps must be timezone-aware.")
        if self.start_at is not None and self.end_at is not None:
            if self.start_at > self.end_at:
                raise ValueError("start_at must not be later than end_at.")
            if self.end_at - self.start_at > self.MAX_RANGE:
                raise ValueError("Replay time range must not exceed 31 days.")
        if not 1 <= self.limit <= self.MAX_LIMIT:
            raise ValueError("Replay limit must be between 1 and 1000.")

    def normalized(self) -> dict[str, Any]:
        """Return stable primitive values for audit and fingerprinting."""

        return {
            "event_type": self.event_type.value,
            "start_at": self._iso_utc(self.start_at),
            "end_at": self._iso_utc(self.end_at),
            "limit": self.limit,
        }

    @staticmethod
    def _iso_utc(value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value is not None else None


@dataclass(frozen=True)
class ReplayEventResult:
    """Payload-free public result for one replay candidate."""

    event_id: str
    status: str
    error_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "skipped", "failed"}:
            raise ValueError("Unknown replay event status.")
        if self.message is not None:
            sanitized = " ".join(str(self.message).split())[:240]
            object.__setattr__(self, "message", sanitized)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result."""

        return {
            "event_id": self.event_id,
            "status": self.status,
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ReplaySummary:
    """Aggregate replay counts with explicit completed/partial/failed outcome."""

    outcome: str
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    results: tuple[ReplayEventResult, ...]

    @classmethod
    def from_results(cls, results: list[ReplayEventResult]) -> ReplaySummary:
        """Classify a bounded list of per-event results."""

        succeeded = sum(item.status == "succeeded" for item in results)
        skipped = sum(item.status == "skipped" for item in results)
        failed = sum(item.status == "failed" for item in results)
        outcome = "completed"
        if failed and succeeded:
            outcome = "partial"
        elif failed and not succeeded:
            outcome = "failed"
        return cls(
            outcome=outcome,
            attempted=len(results),
            succeeded=succeeded,
            skipped=skipped,
            failed=failed,
            results=tuple(results),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return counts, bounded failures, and per-event outcomes."""

        return {
            "outcome": self.outcome,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "failures": [
                item.to_dict() for item in self.results if item.status == "failed"
            ][:20],
            "results": [item.to_dict() for item in self.results],
        }


@dataclass(frozen=True)
class ReplayRunReservation:
    """Outcome of atomically reserving one idempotent replay run."""

    state: str
    run_id: int
    stored_result: dict[str, Any] | None = None


def replay_fingerprint(target_key: str, replay_filter: ReplayFilter) -> str:
    """Hash a normalized target and filter for idempotency conflict detection."""

    payload = {
        "target_key": target_key.strip(),
        "filter": replay_filter.normalized(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
