"""Tests for exact Web-to-TUI rollback commit evidence generation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from scripts import build_web_to_tui_rollback_catalog as rollback_catalog

FIELDNAMES = (
    "template_path",
    "template_role",
    "destination_class",
    "status",
    "rollback_commit",
)


def _write_matrix(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a minimal migration matrix fixture."""

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _row(template_path: str, commit: str) -> dict[str, str]:
    return {
        "template_path": template_path,
        "template_role": "route_page",
        "destination_class": "A",
        "status": "migrated",
        "rollback_commit": commit,
    }


def _evidence(route_pages: list[str]) -> dict[str, Any]:
    scopes = {
        key: {"all_required": True, "route_pages": list(route_pages)}
        for key in (
            "primary_task",
            "permission",
            "empty_state",
            "error_state",
            "legacy_url",
            "rollback",
        )
    }
    return {
        "cleanup": {
            "passed_route_pages": list(route_pages),
            "scope_coverage": scopes,
            "route_rollback_commits": {},
        }
    }


def test_catalog_rejects_pending_or_unresolvable_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = tmp_path / "matrix.csv"
    _write_matrix(matrix, [_row("templates/one.html", "pending_commit")])
    monkeypatch.setattr(rollback_catalog, "_git_commit_is_usable", lambda *args, **kwargs: False)

    with pytest.raises(rollback_catalog.RollbackCatalogError, match="not ready for 1/1"):
        rollback_catalog.build_rollback_catalog(matrix, root=tmp_path)


def test_catalog_syncs_exact_routes_and_fully_closed_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    routes = ["templates/one.html", "templates/two.html"]
    matrix = tmp_path / "matrix.csv"
    _write_matrix(matrix, [_row(route, commit) for route in routes])
    monkeypatch.setattr(rollback_catalog, "_git_commit_is_usable", lambda *args, **kwargs: True)

    catalog = rollback_catalog.build_rollback_catalog(matrix, root=tmp_path)
    evidence = _evidence(routes)
    synchronized = rollback_catalog.synchronize_evidence(evidence, catalog)

    assert synchronized["cleanup"]["route_rollback_commits"] == dict.fromkeys(routes, commit)
    assert synchronized["cleanup"]["passed_route_pages"] == routes
    rollback_catalog.verify_evidence(synchronized, catalog)


def test_catalog_check_rejects_evidence_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "b" * 40
    matrix = tmp_path / "matrix.csv"
    _write_matrix(matrix, [_row("templates/one.html", commit)])
    monkeypatch.setattr(rollback_catalog, "_git_commit_is_usable", lambda *args, **kwargs: True)
    catalog = rollback_catalog.build_rollback_catalog(matrix, root=tmp_path)
    evidence = _evidence(["templates/one.html"])

    with pytest.raises(rollback_catalog.RollbackCatalogError, match="does not match"):
        rollback_catalog.verify_evidence(evidence, catalog)
