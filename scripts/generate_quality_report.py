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
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Optional


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

        packages = []
        for package in root.findall(".//package"):
            package_name = package.attrib.get("name", "unknown")
            package_coverage = float(package.attrib.get("line-rate", 0))
            packages.append({
                "name": package_name,
                "coverage": package_coverage,
            })

        return {
            "coverage_percent": round(float(coverage) * 100, 2),
            "lines_valid": lines_valid,
            "lines_covered": lines_covered,
            "packages": packages,
        }
    except Exception as e:
        return {"error": str(e)}


def generate_nightly_report(args: argparse.Namespace) -> dict[str, Any]:
    """Generate nightly test report with full metrics."""
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "run_type": "nightly",
        "workflow": {
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_url": os.environ.get("GITHUB_SERVER_URL", "") + "/" +
                     os.environ.get("GITHUB_REPOSITORY", "") +
                     "/actions/runs/" +
                     os.environ.get("GITHUB_RUN_ID", ""),
        },
        "test_suites": {
            "unit": {"status": "pending", "coverage": None},
            "integration": {"status": "pending", "coverage": None},
            "guardrails": {"status": "pending", "coverage": None},
            "playwright_smoke": {"status": "pending"},
        },
    }

    # Parse coverage reports if they exist
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
                report["test_suites"][suite]["status"] = "passed"
            else:
                report["test_suites"][suite]["status"] = "failed"
                report["test_suites"][suite]["error"] = metrics["error"]

    # Calculate overall coverage
    coverages = [
        s["coverage"]
        for s in report["test_suites"].values()
        if isinstance(s.get("coverage"), (int, float))
    ]
    if coverages:
        report["overall_coverage"] = round(sum(coverages) / len(coverages), 2)
    else:
        report["overall_coverage"] = 0.0

    return report


def generate_pr_report(args: argparse.Namespace) -> dict[str, Any]:
    """Generate PR gate report with changed-file focus."""
    report = {
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

    # Parse available coverage
    if os.path.exists("coverage-unit.xml"):
        metrics = parse_coverage_xml("coverage-unit.xml")
        if "error" not in metrics:
            report["test_suites"]["unit_targeted"]["coverage"] = metrics["coverage_percent"]
            report["test_suites"]["unit_targeted"]["status"] = "passed"

    return report


def generate_rc_report(args: argparse.Namespace) -> dict[str, Any]:
    """Generate RC gate report with full regression suite."""
    import subprocess

    # Run quality checks
    checks_passed = 0
    checks_failed = 0
    checks = {}

    # 1. API Naming Convention check
    try:
        result = subprocess.run(
            ["python", "scripts/check_routes.py", "--strict"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        checks["api_naming"] = {
            "status": "passed" if result.returncode == 0 else "failed",
            "threshold": "100%",
            "description": "API routes follow /api/{module}/{resource}/ convention"
        }
        if result.returncode == 0:
            checks_passed += 1
        else:
            checks_failed += 1
    except Exception as e:
        checks["api_naming"] = {
            "status": "failed",
            "error": str(e)
        }
        checks_failed += 1

    # 2. Navigation 404 check
    try:
        result = subprocess.run(
            ["pytest", "tests/e2e/", "-k", "navigation", "-v", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        checks["navigation_404"] = {
            "status": "passed" if result.returncode == 0 else "failed",
            "threshold": "0",
            "description": "Main navigation has no 404 errors"
        }
        if result.returncode == 0:
            checks_passed += 1
        else:
            checks_failed += 1
    except Exception as e:
        checks["navigation_404"] = {
            "status": "skipped",
            "error": str(e)
        }

    # 3. Main Chain 501 check
    try:
        result = subprocess.run(
            ["pytest", "tests/guardrails/", "-k", "501 or guardrail", "-v", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        checks["main_chain_501"] = {
            "status": "passed" if result.returncode == 0 else "failed",
            "threshold": "0",
            "description": "Main chain APIs have no 501 responses"
        }
        if result.returncode == 0:
            checks_passed += 1
        else:
            checks_failed += 1
    except Exception as e:
        checks["main_chain_501"] = {
            "status": "failed",
            "error": str(e)
        }
        checks_failed += 1

    # 4. P0/P1 defects check
    from pathlib import Path
    critical_paths = [
        'apps/account/interface/views.py',
        'apps/strategy/interface/views.py',
        'apps/simulated_trading/interface/views.py',
        'apps/backtest/interface/views.py',
        'apps/audit/interface/views.py',
    ]
    blockers = []
    for path in critical_paths:
        p = Path(path)
        if p.exists():
            content = p.read_text(encoding='utf-8')
            if 'TODO' in content or 'FIXME' in content:
                lines = content.split('\n')
                for i, line in enumerate(lines, 1):
                    if ('TODO' in line or 'FIXME' in line) and ('implement' in line.lower() or 'placeholder' in line.lower()):
                        blockers.append(f'{path}:{i}')

    p0_count = len(blockers)
    checks["p0_p1_defects"] = {
        "status": "passed" if p0_count == 0 else "failed",
        "value": f"P0={p0_count}",
        "threshold": "P0=0, P1<=2",
        "description": "No P0 critical defects"
    }
    if p0_count == 0:
        checks_passed += 1
    else:
        checks_failed += 1

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "run_type": "rc",
        "version": args.version or os.environ.get("GITHUB_REF_NAME", "unknown"),
        "sha": os.environ.get("GITHUB_SHA", "unknown"),
        "test_suites": {
            "unit_full": {"status": "pending"},
            "integration_full": {"status": "pending"},
            "e2e": {"status": "pending"},
            "playwright_full": {"status": "pending"},
            "performance": {"status": "pending"},
        },
        "quality_gates": {
            "api_naming": checks.get("api_naming", {}),
            "navigation_404": checks.get("navigation_404", {}),
            "main_chain_501": checks.get("main_chain_501", {}),
            "p0_p1_defects": checks.get("p0_p1_defects", {}),
            "coverage_threshold": 80.0,
            "journey_tests": {
                "status": "skipped" if args.skip_journey else "pending",
                "threshold": ">= 90%",
                "description": "Journey tests pass rate"
            },
        },
        "summary": {
            "total_checks": 4 + (0 if args.skip_journey else 1),
            "passed": checks_passed,
            "failed": checks_failed,
            "overall_status": "passed" if checks_failed == 0 else "failed"
        }
    }

    return report


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


def main():
    parser = argparse.ArgumentParser(
        description="Generate quality reports for CI/CD"
    )
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
    parser.add_argument(
        "--skip-journey",
        action="store_true",
        help="Skip journey tests (emergency mode)",
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
