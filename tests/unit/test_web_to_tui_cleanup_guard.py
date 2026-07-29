"""Fail-closed contracts for Web-to-TUI Classic cleanup."""

from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import check_web_to_tui_cleanup_guard as cleanup_guard

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
CATALOG_PATH = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
EVIDENCE_PATH = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"


def _matrix_rows() -> tuple[list[str], list[dict[str, str]]]:
    """Read the checked-in matrix with its deterministic field order."""

    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), list(reader)


def _write_matrix(
    path: Path,
    *,
    transform: Callable[[dict[str, str]], dict[str, str]],
) -> None:
    """Write one temporary matrix after applying a focused row transform."""

    fieldnames, rows = _matrix_rows()
    transformed = [transform(dict(row)) for row in rows]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(transformed)


def _evaluate(matrix_path: Path) -> cleanup_guard.CleanupGuardResult:
    """Evaluate one temporary matrix against checked-in M5 evidence."""

    return cleanup_guard.evaluate_cleanup_guard(
        matrix_path=matrix_path,
        catalog_path=CATALOG_PATH,
        evidence_path=EVIDENCE_PATH,
        as_of=date(2026, 7, 27),
    )


def test_checked_in_m0_d_baseline_does_not_require_m5_allow() -> None:
    """The seven reviewed shadow deletions remain valid while M5 is DENY."""

    result = _evaluate(MATRIX_PATH)

    assert result.allowed is True
    assert result.new_deleted_paths == ()


def test_new_deletion_without_m5_b_lifecycle_is_rejected(tmp_path: Path) -> None:
    """A new deleted row cannot disguise itself as another M0-D deletion."""

    target = "core/templates/sentiment/analyze.html"
    matrix_path = tmp_path / "matrix.csv"

    def transform(row: dict[str, str]) -> dict[str, str]:
        if row["template_path"] == target:
            row["status"] = "deleted"
            row["wave"] = "M0-D"
        return row

    _write_matrix(matrix_path, transform=transform)

    result = _evaluate(matrix_path)

    assert result.allowed is False
    assert result.new_deleted_paths == (target,)
    assert "must retain A/B lifecycle class and use an M5-B wave" in result.detail


def test_new_m5_b_deletion_requires_complete_cutover_allow(tmp_path: Path) -> None:
    """A well-classified M5-B row is still blocked by checked-in DENY evidence."""

    target = "core/templates/sentiment/analyze.html"
    matrix_path = tmp_path / "matrix.csv"

    def transform(row: dict[str, str]) -> dict[str, str]:
        if row["template_path"] == target:
            row["status"] = "deleted"
            row["wave"] = "M5-B-W1"
        return row

    _write_matrix(matrix_path, transform=transform)

    result = _evaluate(matrix_path)

    assert result.allowed is False
    assert result.new_deleted_paths == (target,)
    assert "cutover_decision=DENY" in result.detail


def test_new_m5_b_deletion_passes_only_when_readiness_is_allow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard delegates the final decision to the complete readiness evaluator."""

    target = "core/templates/sentiment/analyze.html"
    matrix_path = tmp_path / "matrix.csv"

    def transform(row: dict[str, str]) -> dict[str, str]:
        if row["template_path"] == target:
            row["status"] = "deleted"
            row["wave"] = "M5-B-W1"
        return row

    _write_matrix(matrix_path, transform=transform)
    monkeypatch.setattr(
        cleanup_guard,
        "evaluate_readiness",
        lambda **_kwargs: SimpleNamespace(decision="ALLOW"),
    )

    result = _evaluate(matrix_path)

    assert result.allowed is True
    assert result.new_deleted_paths == (target,)
    assert "cutover_decision=ALLOW" in result.detail
