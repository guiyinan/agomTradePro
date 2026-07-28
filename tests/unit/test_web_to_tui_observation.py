"""Unit contracts for starting the Web-to-TUI M5 observation window."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts import start_web_to_tui_observation as observation


def _evidence() -> dict[str, Any]:
    """Build a minimal cutover evidence fixture."""

    return {
        "source_sha256": "a" * 64,
        "candidate": {
            "stable_version": None,
            "candidate_commit": None,
            "released_at": None,
            "observation_end": None,
        },
        "defects": {"open_p0": 1},
        "telemetry": {"tasks": [{"task_key": "old"}]},
        "rollback": {
            "passed": True,
            "environment": "local",
            "production_registry_backup": {"location": "artifact://old"},
        },
        "review_snapshot": {"evidence": "old", "sha256": "b" * 64},
        "approvals": {"owner": {"name": "old"}, "reviewer": {"name": "old-2"}},
    }


def test_prepare_starts_fourteen_day_window_and_clears_stale_evidence() -> None:
    """A new candidate starts a full window without inheriting old production proof."""

    commit = "c" * 40
    prepared = observation.prepare_observation_evidence(
        _evidence(),
        stable_version="0.9.0-rc1",
        candidate_commit=commit,
        released_at=date(2026, 7, 28),
        replace=False,
    )

    assert prepared["candidate"] == {
        "stable_version": "0.9.0-rc1",
        "candidate_commit": commit,
        "released_at": "2026-07-28",
        "observation_end": "2026-08-11",
    }
    assert prepared["defects"]["open_p0"] is None
    assert prepared["telemetry"]["tasks"] == []
    assert prepared["rollback"]["production_registry_backup"] is None
    assert prepared["review_snapshot"] == {"evidence": None, "sha256": None}
    assert prepared["approvals"] == {"owner": None, "reviewer": None}


def test_prepare_is_idempotent_for_same_candidate() -> None:
    """Repeating the exact candidate must preserve evidence already collected for it."""

    commit = "d" * 40
    initial = observation.prepare_observation_evidence(
        _evidence(),
        stable_version="0.9.0-rc1",
        candidate_commit=commit,
        released_at=date(2026, 7, 28),
        replace=False,
    )
    initial["telemetry"]["tasks"] = [{"task_key": "current"}]

    repeated = observation.prepare_observation_evidence(
        initial,
        stable_version="0.9.0-rc1",
        candidate_commit=commit,
        released_at=date(2026, 7, 28),
        replace=False,
    )

    assert repeated["telemetry"]["tasks"] == [{"task_key": "current"}]


def test_prepare_requires_explicit_replace_for_different_candidate() -> None:
    """A new version cannot silently reuse a previous candidate window."""

    commit = "e" * 40
    existing = observation.prepare_observation_evidence(
        _evidence(),
        stable_version="0.9.0-rc1",
        candidate_commit=commit,
        released_at=date(2026, 7, 28),
        replace=False,
    )

    with pytest.raises(observation.ObservationStartError, match="--replace"):
        observation.prepare_observation_evidence(
            existing,
            stable_version="0.9.0-rc2",
            candidate_commit="f" * 40,
            released_at=date(2026, 7, 29),
            replace=False,
        )


def test_prepare_replace_resets_previous_candidate_evidence() -> None:
    """An explicit candidate replacement restarts the window and clears old proof."""

    existing = observation.prepare_observation_evidence(
        _evidence(),
        stable_version="0.9.0-rc1",
        candidate_commit="e" * 40,
        released_at=date(2026, 7, 28),
        replace=False,
    )
    existing["telemetry"]["tasks"] = [{"task_key": "previous-candidate"}]

    replaced = observation.prepare_observation_evidence(
        existing,
        stable_version="0.9.0-rc2",
        candidate_commit="f" * 40,
        released_at=date(2026, 7, 29),
        replace=True,
    )

    assert replaced["candidate"]["observation_end"] == "2026-08-12"
    assert replaced["telemetry"]["tasks"] == []


def test_validate_candidate_requires_matching_committed_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit for a different migration scope cannot start observation."""

    matrix = tmp_path / "matrix.csv"
    matrix.write_text("current", encoding="utf-8")
    evidence = {"source_sha256": hashlib.sha256(b"current").hexdigest()}
    monkeypatch.setattr(observation, "_commit_is_ancestor", lambda *args, **kwargs: True)
    monkeypatch.setattr(observation, "_file_at_commit", lambda *args, **kwargs: b"old")

    with pytest.raises(observation.ObservationStartError, match="different migration matrix"):
        observation.validate_candidate_source(
            candidate_commit="a" * 40,
            matrix_path=matrix,
            evidence=evidence,
            require_clean=False,
            root=tmp_path,
        )


def test_validate_candidate_rejects_dirty_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uncommitted code cannot be represented by a stable candidate commit."""

    matrix = tmp_path / "matrix.csv"
    matrix.write_bytes(b"current")
    evidence = {"source_sha256": hashlib.sha256(b"current").hexdigest()}
    monkeypatch.setattr(observation, "_commit_is_ancestor", lambda *args, **kwargs: True)
    monkeypatch.setattr(observation, "_file_at_commit", lambda *args, **kwargs: b"current")
    monkeypatch.setattr(observation, "_worktree_changes", lambda **kwargs: [" M file.py"])

    with pytest.raises(observation.ObservationStartError, match="Worktree must be clean"):
        observation.validate_candidate_source(
            candidate_commit="a" * 40,
            matrix_path=matrix,
            evidence=evidence,
            require_clean=True,
            root=tmp_path,
        )
