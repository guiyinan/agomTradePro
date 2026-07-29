#!/usr/bin/env python
"""Block new Classic cleanup until the Web-to-TUI M5 gate is ALLOW.

The seven M0-D shadow-template deletions predate M5 and form the immutable
baseline. Any additional matrix row marked ``deleted`` is an M5-B cleanup and
must both use an M5-B wave and pass the complete cutover readiness evaluator.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_web_to_tui_cutover_readiness import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_EVIDENCE,
    DEFAULT_MATRIX,
    evaluate_readiness,
)

M0_D_BASELINE_PATHS = frozenset(
    {
        "apps/audit/templates/audit/attribution_report.html",
        "apps/audit/templates/audit/audit_page.html",
        "apps/data_center/templates/data_center/monitor.html",
        "apps/data_center/templates/data_center/providers.html",
        "core/templates/account/create_simulated_account.html",
        "core/templates/audit/audit_page.html",
        "core/templates/macro/data_controller.html",
    }
)


@dataclass(frozen=True)
class CleanupGuardResult:
    """One fail-closed decision for newly deleted Classic templates."""

    allowed: bool
    new_deleted_paths: tuple[str, ...]
    detail: str


def _read_matrix_rows(matrix_path: Path) -> list[dict[str, str]]:
    """Read reviewed migration rows from the CSV boundary."""

    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def evaluate_cleanup_guard(
    *,
    matrix_path: Path,
    catalog_path: Path,
    evidence_path: Path,
    as_of: date,
) -> CleanupGuardResult:
    """Require an ALLOW decision for every deletion beyond the M0-D baseline."""

    rows = _read_matrix_rows(matrix_path)
    rows_by_path = {row.get("template_path", "").strip(): row for row in rows}
    deleted_paths = {
        path
        for path, row in rows_by_path.items()
        if path and row.get("status", "").strip() == "deleted"
    }
    missing_baseline = sorted(M0_D_BASELINE_PATHS - deleted_paths)
    if missing_baseline:
        return CleanupGuardResult(
            allowed=False,
            new_deleted_paths=(),
            detail=f"M0-D baseline drift: missing={missing_baseline}",
        )

    new_deleted_paths = tuple(sorted(deleted_paths - M0_D_BASELINE_PATHS))
    if not new_deleted_paths:
        return CleanupGuardResult(
            allowed=True,
            new_deleted_paths=(),
            detail="no cleanup beyond the reviewed M0-D baseline",
        )

    invalid_rows = [
        path
        for path in new_deleted_paths
        if rows_by_path[path].get("destination_class", "").strip() not in {"A", "B"}
        or not rows_by_path[path].get("wave", "").strip().startswith("M5-B")
    ]
    if invalid_rows:
        return CleanupGuardResult(
            allowed=False,
            new_deleted_paths=new_deleted_paths,
            detail=(
                "new deletions must retain A/B lifecycle class and use an M5-B wave: "
                f"invalid={invalid_rows}"
            ),
        )

    readiness = evaluate_readiness(
        matrix_path=matrix_path,
        catalog_path=catalog_path,
        evidence_path=evidence_path,
        as_of=as_of,
    )
    return CleanupGuardResult(
        allowed=readiness.decision == "ALLOW",
        new_deleted_paths=new_deleted_paths,
        detail=(f"new_deleted={len(new_deleted_paths)}; " f"cutover_decision={readiness.decision}"),
    )


def main() -> None:
    """Run the Classic cleanup guard for CI and local release checks."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    result = evaluate_cleanup_guard(
        matrix_path=args.matrix.resolve(),
        catalog_path=args.catalog.resolve(),
        evidence_path=args.evidence.resolve(),
        as_of=args.as_of,
    )
    marker = "PASS" if result.allowed else "FAIL"
    print(f"Web-to-TUI Classic cleanup guard: {marker} - {result.detail}")
    if not result.allowed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
