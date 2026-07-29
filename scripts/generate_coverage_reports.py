#!/usr/bin/env python
"""Generate branch-aware coverage reports for governed Python source scopes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coverage import Coverage

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_coverage_ratchet import main as check_coverage_ratchet

DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "quality"
SCOPE_INCLUDES: Mapping[str, tuple[str, ...]] = {
    "apps": ("apps/*",),
    "core": ("core/*",),
    "shared": ("shared/*",),
    "sdk": ("sdk/agomtradepro/*", "sdk/agomtradepro_mcp/*"),
}


@dataclass
class InventoryTotals:
    """Mutable counters used while building the coverage risk inventory."""

    covered_lines: int = 0
    num_statements: int = 0
    covered_branches: int = 0
    num_branches: int = 0

    def add(self, summary: Mapping[str, Any]) -> None:
        """Accumulate one coverage.py file summary."""
        self.covered_lines += int(summary.get("covered_lines", 0))
        self.num_statements += int(summary.get("num_statements", 0))
        self.covered_branches += int(summary.get("covered_branches", 0))
        self.num_branches += int(summary.get("num_branches", 0))

    def as_dict(self) -> dict[str, int | float]:
        """Return stable machine-readable totals and percentages."""
        return {
            "covered_lines": self.covered_lines,
            "num_statements": self.num_statements,
            "missing_lines": self.num_statements - self.covered_lines,
            "line_percent": (
                round(self.covered_lines * 100 / self.num_statements, 2)
                if self.num_statements
                else 100.0
            ),
            "covered_branches": self.covered_branches,
            "num_branches": self.num_branches,
            "missing_branches": self.num_branches - self.covered_branches,
            "branch_percent": (
                round(self.covered_branches * 100 / self.num_branches, 2)
                if self.num_branches
                else 100.0
            ),
        }


def _source_coordinates(filename: str) -> tuple[str, str | None, str | None]:
    """Return scope, app module, and architecture layer for a source path."""
    parts = Path(filename.replace("\\", "/")).parts
    if not parts:
        return "unknown", None, None
    if parts[0] == "apps" and len(parts) >= 2:
        module = parts[1]
        if len(parts) >= 3 and parts[2] in {
            "domain",
            "application",
            "infrastructure",
            "interface",
        }:
            return "apps", module, parts[2]
        if len(parts) >= 4 and parts[2:4] == ("management", "commands"):
            return "apps", module, "management_commands"
        return "apps", module, "other"
    if parts[0] in {"core", "shared"}:
        return parts[0], None, None
    if parts[0] == "sdk":
        return "sdk", None, None
    return "unknown", None, None


def _inventory_file_sort_key(item: Mapping[str, object]) -> tuple[int, int, str]:
    """Sort files by missing lines, missing branches, then path."""
    missing_lines = item.get("missing_lines", 0)
    missing_branches = item.get("missing_branches", 0)
    return (
        -missing_lines if isinstance(missing_lines, int) else 0,
        -missing_branches if isinstance(missing_branches, int) else 0,
        str(item.get("path", "")),
    )


def write_inventory(*, details_path: Path, output_dir: Path) -> Path:
    """Summarize missing lines and branches by scope, module, layer, and file."""
    payload = json.loads(details_path.read_text(encoding="utf-8"))
    file_payloads = payload.get("files", {})
    if not isinstance(file_payloads, dict):
        raise ValueError("coverage JSON does not contain a files mapping")

    scope_totals: dict[str, InventoryTotals] = {}
    module_totals: dict[str, InventoryTotals] = {}
    layer_totals: dict[str, InventoryTotals] = {}
    files: list[dict[str, object]] = []
    for raw_filename, raw_metrics in file_payloads.items():
        if not isinstance(raw_filename, str) or not isinstance(raw_metrics, dict):
            continue
        summary = raw_metrics.get("summary", {})
        if not isinstance(summary, dict):
            continue
        scope, module, layer = _source_coordinates(raw_filename)
        scope_totals.setdefault(scope, InventoryTotals()).add(summary)
        if module is not None:
            module_totals.setdefault(module, InventoryTotals()).add(summary)
        if layer is not None:
            layer_totals.setdefault(layer, InventoryTotals()).add(summary)
        files.append(
            {
                "path": raw_filename.replace("\\", "/"),
                "scope": scope,
                "module": module,
                "layer": layer,
                **InventoryTotals(
                    covered_lines=int(summary.get("covered_lines", 0)),
                    num_statements=int(summary.get("num_statements", 0)),
                    covered_branches=int(summary.get("covered_branches", 0)),
                    num_branches=int(summary.get("num_branches", 0)),
                ).as_dict(),
                "missing_line_numbers": raw_metrics.get("missing_lines", []),
                "missing_branch_arcs": raw_metrics.get("missing_branches", []),
            }
        )

    files.sort(key=_inventory_file_sort_key)
    inventory_path = output_dir / "coverage-inventory.json"
    inventory = {
        "schema_version": 1,
        "source_details": str(details_path.resolve()),
        "scopes": {name: totals.as_dict() for name, totals in sorted(scope_totals.items())},
        "modules": {name: totals.as_dict() for name, totals in sorted(module_totals.items())},
        "architecture_layers": {
            name: totals.as_dict() for name, totals in sorted(layer_totals.items())
        },
        "files": files,
    }
    inventory_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return inventory_path


def _git_commit() -> str:
    """Return the exact commit used to generate the coverage reports."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_is_dirty() -> bool:
    """Return whether tracked or untracked source changes are present."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _sha256(path: Path) -> str:
    """Return a stable SHA-256 digest for a report input."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_reports(
    *,
    data_file: Path,
    config_file: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Write combined and per-scope XML reports from one coverage data file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage = Coverage(
        data_file=str(data_file),
        config_file=str(config_file),
    )
    coverage.load()

    combined_report = output_dir / "coverage-final.xml"
    coverage.xml_report(outfile=str(combined_report))
    reports: dict[str, Path] = {"combined": combined_report}
    details_report = output_dir / "coverage-final-details.json"
    coverage.json_report(outfile=str(details_report), pretty_print=True)
    reports["details"] = details_report
    reports["inventory"] = write_inventory(
        details_path=details_report,
        output_dir=output_dir,
    )
    for scope, includes in SCOPE_INCLUDES.items():
        report_path = output_dir / f"coverage-{scope}.xml"
        coverage.xml_report(
            outfile=str(report_path),
            include=list(includes),
        )
        reports[scope] = report_path
    return reports


def write_manifest(
    *,
    reports: Mapping[str, Path],
    data_file: Path,
    config_file: Path,
    output_dir: Path,
) -> Path:
    """Write traceability metadata for the generated coverage evidence."""
    manifest_path = output_dir / "coverage-manifest.json"
    payload = {
        "schema_version": 1,
        "commit": _git_commit(),
        "git_dirty": _git_is_dirty(),
        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        "coverage_data": str(data_file.resolve()),
        "coverage_config": str(config_file.resolve()),
        "coverage_config_sha256": _sha256(config_file),
        "branch_measurement": True,
        "reports": {
            scope: {
                "path": str(path.resolve()),
                "sha256": _sha256(path),
            }
            for scope, path in sorted(reports.items())
        },
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-file",
        type=Path,
        default=REPO_ROOT / ".coverage",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / ".coveragerc",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=REPO_ROOT / "governance" / "testing_quality_baseline.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="enforce the configured coverage ratchet after report generation",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate reports, write their manifest, and optionally enforce the ratchet."""
    args = parse_args(argv)
    reports = generate_reports(
        data_file=args.data_file,
        config_file=args.config,
        output_dir=args.output_dir,
    )
    manifest_path = write_manifest(
        reports=reports,
        data_file=args.data_file,
        config_file=args.config,
        output_dir=args.output_dir,
    )
    print(f"Coverage manifest: {manifest_path}")
    if not args.check:
        return 0
    ratchet_args = [
        "--baseline",
        str(args.baseline),
    ]
    for scope in SCOPE_INCLUDES:
        ratchet_args.extend(
            [
                "--scope-report",
                f"{scope}={reports[scope]}",
            ]
        )
    return check_coverage_ratchet(ratchet_args)


if __name__ == "__main__":
    raise SystemExit(main())
