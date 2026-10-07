#!/usr/bin/env python
"""
Quality Report Generator for AgomTradePro CI/CD

Generates quality metrics reports from test runs and coverage data.
Usage:
    python scripts/generate_quality_report.py --type nightly|pr|rc
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTING_BASELINE_PATH = REPO_ROOT / "governance" / "testing_quality_baseline.json"


def parse_coverage_xml(xml_path: str) -> dict[str, Any]:
    """Parse pytest-cov XML report and extract metrics."""
    if not os.path.exists(xml_path):
        return {"error": f"File not found: {xml_path}"}

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        coverage = root.attrib.get("line-rate", "0")
        lines_valid = int(root.attrib.get("lines-valid", 0))
        lines_covered = int(root.attrib.get("lines-covered", 0))
        branches_valid = int(root.attrib.get("branches-valid", 0))
        branches_covered = int(root.attrib.get("branches-covered", 0))

        packages = []
        for package in root.findall(".//package"):
            package_name = package.attrib.get("name", "unknown")
            package_coverage = float(package.attrib.get("line-rate", 0))
            packages.append(
                {
                    "name": package_name,
                    "coverage": package_coverage,
                }
            )

        return {
            "coverage_percent": round(float(coverage) * 100, 2),
            "lines_valid": lines_valid,
            "lines_covered": lines_covered,
            "branch_coverage_percent": (
                round(branches_covered * 100 / branches_valid, 2) if branches_valid else None
            ),
            "branches_valid": branches_valid,
            "branches_covered": branches_covered,
            "packages": packages,
        }
    except Exception as e:
        return {"error": str(e)}


def load_repository_coverage_minimum(
    baseline_path: Path = TESTING_BASELINE_PATH,
) -> float:
    """Load the repository threshold from the single testing baseline."""
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    return float(payload["coverage"]["repository_minimum"])


def read_step_outcomes() -> dict[str, str]:
    """Read actual Actions outcomes; absent evidence remains unverified."""
    try:
        payload: object = json.loads(os.environ.get("CI_STEP_RESULTS", "{}"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    outcomes: dict[str, str] = {}
    statuses = {
        "success": "passed",
        "failure": "failed",
        "cancelled": "cancelled",
        "skipped": "skipped",
    }
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, dict):
            outcome = value.get("outcome")
            outcomes[key] = (
                statuses.get(outcome, "unverified") if isinstance(outcome, str) else "unverified"
            )
    return outcomes


def generate_nightly_report(args: argparse.Namespace) -> dict[str, Any]:
    """Generate nightly test report with full metrics."""
    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "run_type": "nightly",
        "workflow": {
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_url": os.environ.get("GITHUB_SERVER_URL", "")
            + "/"
            + os.environ.get("GITHUB_REPOSITORY", "")
            + "/actions/runs/"
            + os.environ.get("GITHUB_RUN_ID", ""),
        },
        "test_suites": {
            "unit": {"status": "pending", "coverage": None},
            "integration": {"status": "pending", "coverage": None},
            "guardrails": {"status": "pending", "coverage": None},
            "playwright_smoke": {"status": "pending"},
        },
        "coverage_scopes": {},
    }

    outcomes = read_step_outcomes()
    for suite in (
        "unit",
        "component",
        "api_migrations",
        "critical_sqlite",
        "integration",
        "app_local",
        "sdk",
        "mcp",
        "e2e",
        "guardrails",
        "playwright_smoke",
        "frontend",
        "current_data",
        "celery",
    ):
        report["test_suites"][suite] = {"status": outcomes.get(suite, "unverified")}
    report["coverage_gate"] = outcomes.get("coverage_gate", "unverified")
    report["full_lint_observation"] = {
        "status": outcomes.get("full_lint", "unverified"),
        "blocking": False,
    }
    report["production_acceptance"] = "unverified"
    report["deployment_authorized"] = False
    report["sha"] = os.environ.get("GITHUB_SHA", "unknown")

    # Coverage measures executed lines; it cannot prove test success.
    coverage_files = {
        "unit": "coverage-unit.xml",
        "integration": "coverage-integration.xml",
        "guardrails": "coverage-guardrail.xml",
    }

    for suite, filename in coverage_files.items():
        if os.path.exists(filename):
            metrics = parse_coverage_xml(filename)
            if "error" not in metrics:
                report["test_suites"][suite]["coverage"] = metrics["coverage_percent"]
                report["test_suites"][suite]["coverage_status"] = "available"
            else:
                report["test_suites"][suite]["coverage_status"] = "invalid"
                report["test_suites"][suite]["error"] = metrics["error"]

    scope_files = {
        "apps": "reports/quality/coverage-apps.xml",
        "core": "reports/quality/coverage-core.xml",
        "shared": "reports/quality/coverage-shared.xml",
        "sdk": "reports/quality/coverage-sdk.xml",
    }
    for scope, filename in scope_files.items():
        metrics = parse_coverage_xml(filename)
        report["coverage_scopes"][scope] = metrics

    apps_metrics = report["coverage_scopes"]["apps"]
    report["overall_coverage"] = (
        apps_metrics["coverage_percent"] if "error" not in apps_metrics else 0.0
    )
    report["coverage_threshold"] = load_repository_coverage_minimum()

    return report


def generate_pr_report(args: argparse.Namespace) -> dict[str, Any]:
    """Generate PR gate report with changed-file focus."""
    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "run_type": "pr",
        "pr": {
            "number": os.environ.get("GITHUB_REF_NAME", "unknown"),
            "head_sha": os.environ.get("GITHUB_SHA", "unknown"),
        },
        "test_suites": {
            "unit_targeted": {"status": "pending"},
            "integration_core": {"status": "pending"},
            "guardrails": {"status": "pending"},
        },
    }

    outcomes = read_step_outcomes()
    for suite in report["test_suites"]:
        report["test_suites"][suite]["status"] = outcomes.get(suite, "unverified")
    report["production_acceptance"] = "unverified"
    report["deployment_authorized"] = False

    # Parse available coverage
    if os.path.exists("coverage-unit.xml"):
        metrics = parse_coverage_xml("coverage-unit.xml")
        if "error" not in metrics:
            report["test_suites"]["unit_targeted"]["coverage"] = metrics["coverage_percent"]
            report["test_suites"]["unit_targeted"]["coverage_status"] = "available"

    return report


def generate_rc_report(args: argparse.Namespace) -> dict[str, Any]:
    """Project same-run job evidence using the canonical fail-closed RC reporter."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from rc_gate_report import report_from_environment

    return dict(report_from_environment(version=args.version))


def save_report(report: dict[str, Any], output_dir: str) -> str:
    """Save report to JSON file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    run_type = report["run_type"]
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{run_type}_report_{timestamp}.json"
    filepath = output_path / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return str(filepath)


def main() -> int:
    """Write a quality report; an incomplete RC report must return failure."""

    parser = argparse.ArgumentParser(description="Generate quality reports for CI/CD")
    parser.add_argument(
        "--type",
        choices=["nightly", "pr", "rc"],
        default="nightly",
        help="Type of report to generate",
    )
    parser.add_argument(
        "--output",
        default="reports/quality",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--version",
        help="Version string (for RC reports)",
    )

    args = parser.parse_args()

    # Generate report based on type
    generators = {
        "nightly": generate_nightly_report,
        "pr": generate_pr_report,
        "rc": generate_rc_report,
    }

    report = generators[args.type](args)

    # Save report
    filepath = save_report(report, args.output)

    # Print summary
    print(f"Quality report generated: {filepath}")
    print(f"Type: {report['run_type']}")
    print(f"Timestamp: {report['timestamp']}")

    if "overall_coverage" in report:
        print(f"Overall coverage: {report['overall_coverage']}%")

    if args.type == "rc" and report["summary"]["overall_status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
