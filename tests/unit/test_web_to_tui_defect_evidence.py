"""Unit contracts for Web-to-TUI M5 blocking-defect evidence generation."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from scripts import build_web_to_tui_defect_evidence as defect_evidence

SOURCE_SHA256 = "a" * 64
CANDIDATE_COMMIT = "b" * 40


@pytest.fixture(autouse=True)
def usable_candidate_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat the synthetic commit as part of the current branch history."""

    monkeypatch.setattr(
        defect_evidence,
        "_git_commit_is_usable",
        lambda *args, **kwargs: True,
    )


def _evidence() -> dict[str, Any]:
    """Build candidate-bound cutover evidence."""

    return {
        "source_sha256": SOURCE_SHA256,
        "candidate": {
            "stable_version": "0.9.0-rc1",
            "candidate_commit": CANDIDATE_COMMIT,
            "released_at": "2026-07-28",
            "observation_end": "2026-08-11",
        },
        "defects": {},
    }


def _snapshot() -> dict[str, Any]:
    """Build one empty, reviewed issue-tracker snapshot."""

    return {
        "version": defect_evidence.SNAPSHOT_VERSION,
        "source_sha256": SOURCE_SHA256,
        "candidate_version": "0.9.0-rc1",
        "candidate_commit": CANDIDATE_COMMIT,
        "window_start": "2026-07-28",
        "window_end": "2026-08-11",
        "queried_at": "2026-08-11",
        "query_scope": defect_evidence.QUERY_SCOPE,
        "tracker": {
            "system": "github",
            "project": "agom/agomTradePro",
            "endpoint": "https://github.com/agom/agomTradePro/issues",
            "query_filter": (
                "candidate=0.9.0-rc1 priority in (P0,P1) " "created-or-open=2026-07-28..2026-08-11"
            ),
            "queried_by": "release-owner",
        },
        "issues": [],
    }


def _build(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build defect evidence from one synthetic snapshot."""

    return defect_evidence.build_defect_evidence(
        snapshot=snapshot,
        evidence=_evidence(),
        snapshot_evidence_path="docs/plans/blocking-defects.json",
        snapshot_sha256="c" * 64,
        as_of=date(2026, 8, 11),
    )


def test_builds_clear_candidate_bound_defect_evidence() -> None:
    """An empty exact-scope snapshot produces four explicit zero counts."""

    prepared = _build(_snapshot())
    defects = prepared["defects"]

    assert defects["candidate_commit"] == CANDIDATE_COMMIT
    assert defects["query_scope"] == defect_evidence.QUERY_SCOPE
    assert {defects[key] for key in ("new_p0", "new_p1", "open_p0", "open_p1")} == {0}
    assert defects["snapshot_sha256"] == "c" * 64


def test_rejects_snapshot_for_another_candidate_or_window() -> None:
    """Defect evidence cannot carry across candidate versions or observation windows."""

    other_candidate = _snapshot()
    other_candidate["candidate_version"] = "0.9.0-rc2"
    with pytest.raises(defect_evidence.DefectEvidenceError, match="different candidate"):
        _build(other_candidate)

    wrong_window = _snapshot()
    wrong_window["window_end"] = "2026-08-12"
    with pytest.raises(defect_evidence.DefectEvidenceError, match="exactly match"):
        _build(wrong_window)


def test_counts_new_issue_even_when_closed_inside_window() -> None:
    """Closing a newly opened P1 does not erase the window violation."""

    snapshot = _snapshot()
    snapshot["issues"] = [
        {
            "id": "GH-101",
            "priority": "P1",
            "state": "closed",
            "created_at": "2026-08-01",
            "closed_at": "2026-08-02",
        }
    ]

    defects = _build(snapshot)["defects"]

    assert defects["new_p1"] == 1
    assert defects["open_p1"] == 1


def test_counts_preexisting_issue_open_during_window() -> None:
    """A pre-window P0 that remains open into the window is still blocking."""

    snapshot = _snapshot()
    snapshot["issues"] = [
        {
            "id": "GH-100",
            "priority": "P0",
            "state": "closed",
            "created_at": "2026-07-20",
            "closed_at": "2026-07-29",
        }
    ]

    defects = _build(snapshot)["defects"]

    assert defects["new_p0"] == 0
    assert defects["open_p0"] == 1


def test_rejects_duplicate_or_out_of_scope_issue_records() -> None:
    """Tracker exports must contain unique P0/P1 records limited to the declared window."""

    duplicate = _snapshot()
    issue = {
        "id": "GH-102",
        "priority": "P1",
        "state": "open",
        "created_at": "2026-08-01",
        "closed_at": None,
    }
    duplicate["issues"] = [issue, dict(issue)]
    with pytest.raises(defect_evidence.DefectEvidenceError, match="Duplicate issue"):
        _build(duplicate)

    out_of_scope = _snapshot()
    out_of_scope["issues"] = [
        {
            "id": "GH-103",
            "priority": "P2",
            "state": "open",
            "created_at": "2026-08-01",
            "closed_at": None,
        }
    ]
    with pytest.raises(defect_evidence.DefectEvidenceError, match="outside the P0/P1"):
        _build(out_of_scope)


def test_rejects_invalid_issue_lifecycle() -> None:
    """Issue state and dates must form a coherent auditable lifecycle."""

    snapshot = _snapshot()
    snapshot["issues"] = [
        {
            "id": "GH-104",
            "priority": "P0",
            "state": "closed",
            "created_at": "2026-08-02",
            "closed_at": "2026-08-01",
        }
    ]
    with pytest.raises(defect_evidence.DefectEvidenceError, match="before it was created"):
        _build(snapshot)


def test_rejects_unsafe_tracker_metadata_or_incomplete_scope() -> None:
    """Tracker provenance cannot embed credentials or omit the reviewed query scope."""

    unsafe = _snapshot()
    unsafe["tracker"]["endpoint"] = "https://user:secret@github.com/issues"
    with pytest.raises(defect_evidence.DefectEvidenceError, match="credential-free"):
        _build(unsafe)

    incomplete = _snapshot()
    incomplete["query_scope"] = "open_at_end_only"
    with pytest.raises(defect_evidence.DefectEvidenceError, match="query_scope"):
        _build(incomplete)
