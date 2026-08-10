"""Immutable cumulative anchors for the R3 run lifecycle stream."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ._runner_support import (
    canonical_json,
    hash_payload,
    require_positive,
    require_sha256,
    require_token,
)
from .lifecycle import MacroFactorLifecycleEvent, validate_lifecycle_chain
from .run_artifacts import ReproducibleMacroFactorRunArtifact


def _stream_hash(
    artifact: ReproducibleMacroFactorRunArtifact,
    events: tuple[MacroFactorLifecycleEvent, ...],
) -> str:
    return hash_payload(
        {
            "artifact_id": artifact.artifact_id,
            "artifact_hash": artifact.content_hash,
            "event_hashes": [event.content_hash for event in events],
        }
    )


@dataclass(frozen=True)
class MacroFactorLifecycleStreamCommit:
    """One immutable cumulative commitment to an exact lifecycle prefix."""

    commit_id: str
    artifact_id: str
    artifact_hash: str
    event_id: str
    event_hash: str
    sequence: int
    event_count: int
    head_event_hash: str
    previous_commit_hash: str | None
    stream_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.commit_id, "commit_id"),
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.event_hash, "event_hash"),
            (self.head_event_hash, "head_event_hash"),
            (self.stream_hash, "stream_hash"),
        ):
            require_sha256(value, f"LifecycleStreamCommit.{name}")
        if self.previous_commit_hash is not None:
            require_sha256(
                self.previous_commit_hash,
                "LifecycleStreamCommit.previous_commit_hash",
            )
        require_token(self.event_id, "LifecycleStreamCommit.event_id")
        require_positive(self.sequence, "LifecycleStreamCommit.sequence")
        require_positive(self.event_count, "LifecycleStreamCommit.event_count")
        if self.event_count != self.sequence:
            raise ValueError("lifecycle stream event_count must equal sequence")
        if self.head_event_hash != self.event_hash:
            raise ValueError("lifecycle stream head must equal committed event hash")
        if (self.sequence == 1) != (self.previous_commit_hash is None):
            raise ValueError("lifecycle stream previous-commit identity is invalid")
        expected_id = hash_payload(
            {
                "artifact_id": self.artifact_id,
                "sequence": self.sequence,
                "event_id": self.event_id,
                "event_hash": self.event_hash,
            }
        )
        if self.commit_id != expected_id:
            raise ValueError("lifecycle stream commit identity is invalid")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("lifecycle stream commits must remain research-only and blocked")

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return the complete immutable stream-commit row payload."""

        return {
            "commit_id": self.commit_id,
            "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
            "sequence": self.sequence,
            "event_count": self.event_count,
            "head_event_hash": self.head_event_hash,
            "previous_commit_hash": self.previous_commit_hash,
            "stream_hash": self.stream_hash,
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }

    @property
    def canonical_json(self) -> str:
        """Return canonical bytes-as-text for persistence."""

        return canonical_json(self.canonical_payload)

    @property
    def content_hash(self) -> str:
        """Seal every field of this cumulative stream commitment."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MacroFactorLifecycleStreamHead:
    """Independent mutable-row value that seals the latest committed stream prefix."""

    artifact_id: str
    artifact_hash: str
    latest_sequence: int
    event_count: int
    latest_event_hash: str
    latest_commit_hash: str
    stream_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.latest_event_hash, "latest_event_hash"),
            (self.latest_commit_hash, "latest_commit_hash"),
            (self.stream_hash, "stream_hash"),
        ):
            require_sha256(value, f"LifecycleStreamHead.{name}")
        require_positive(self.latest_sequence, "LifecycleStreamHead.latest_sequence")
        require_positive(self.event_count, "LifecycleStreamHead.event_count")
        if self.latest_sequence != self.event_count:
            raise ValueError("lifecycle stream head count must equal latest sequence")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("lifecycle stream head must remain research-only and blocked")

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return every independent latest-head identity canonically."""

        return {
            "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash,
            "latest_sequence": self.latest_sequence,
            "event_count": self.event_count,
            "latest_event_hash": self.latest_event_hash,
            "latest_commit_hash": self.latest_commit_hash,
            "stream_hash": self.stream_hash,
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }

    @property
    def canonical_json(self) -> str:
        """Return canonical latest-head content for persistence."""

        return canonical_json(self.canonical_payload)

    @property
    def content_hash(self) -> str:
        """Seal the authoritative per-artifact head and count."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


def build_lifecycle_stream_commits(
    artifact: ReproducibleMacroFactorRunArtifact,
    events: tuple[MacroFactorLifecycleEvent, ...],
) -> tuple[MacroFactorLifecycleStreamCommit, ...]:
    """Build the exact cumulative commitment expected for every lifecycle prefix."""

    validate_lifecycle_chain(artifact.artifact_id, artifact.content_hash, events)
    commits: list[MacroFactorLifecycleStreamCommit] = []
    for sequence, event in enumerate(events, 1):
        if event.sequence != sequence:
            raise ValueError("lifecycle stream event sequence is not contiguous")
        previous_commit_hash = None if not commits else commits[-1].content_hash
        commits.append(
            MacroFactorLifecycleStreamCommit(
                commit_id=hash_payload(
                    {
                        "artifact_id": artifact.artifact_id,
                        "sequence": sequence,
                        "event_id": event.event_id,
                        "event_hash": event.content_hash,
                    }
                ),
                artifact_id=artifact.artifact_id,
                artifact_hash=artifact.content_hash,
                event_id=event.event_id,
                event_hash=event.content_hash,
                sequence=sequence,
                event_count=sequence,
                head_event_hash=event.content_hash,
                previous_commit_hash=previous_commit_hash,
                stream_hash=_stream_hash(artifact, events[:sequence]),
            )
        )
    return tuple(commits)


def build_lifecycle_stream_head(
    artifact: ReproducibleMacroFactorRunArtifact,
    events: tuple[MacroFactorLifecycleEvent, ...],
    commits: tuple[MacroFactorLifecycleStreamCommit, ...],
) -> MacroFactorLifecycleStreamHead:
    """Build the one exact independent latest-head value for a committed stream."""

    expected_commits = build_lifecycle_stream_commits(artifact, events)
    if commits != expected_commits:
        raise ValueError("lifecycle stream head requires the exact cumulative commits")
    latest_event = events[-1]
    latest_commit = commits[-1]
    return MacroFactorLifecycleStreamHead(
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        latest_sequence=latest_event.sequence,
        event_count=len(events),
        latest_event_hash=latest_event.content_hash,
        latest_commit_hash=latest_commit.content_hash,
        stream_hash=latest_commit.stream_hash,
    )


__all__ = [
    "MacroFactorLifecycleStreamCommit",
    "MacroFactorLifecycleStreamHead",
    "build_lifecycle_stream_commits",
    "build_lifecycle_stream_head",
]
