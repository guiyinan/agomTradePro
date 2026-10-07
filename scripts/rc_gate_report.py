#!/usr/bin/env python
"""Summarize same-run GitHub job results without implying production acceptance."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict


@dataclass(frozen=True)
class Gate:
    """Required RC job and the limited evidence it provides."""

    key: str
    workflow: str
    evidence_kind: str
    proves: str


REQUIRED_GATES = (
    Gate(
        "architecture",
        "architecture-layer-guard.yml",
        "static",
        "Registered structural rules and dependency budgets pass.",
    ),
    Gate(
        "consistency",
        "consistency-check.yml",
        "static_contract",
        "Registered inventories, contracts and projections agree.",
    ),
    Gate(
        "security",
        "security-scan.yml",
        "security_scan",
        "Configured scanners pass their severity and exception policies.",
    ),
    Gate(
        "fast",
        "ci-fast-feedback.yml",
        "static_and_targeted_tests",
        "Selected changes pass daily quality and targeted test gates.",
    ),
    Gate(
        "regression",
        "nightly-tests.yml",
        "regression_and_isolated_postgresql",
        "Nightly suites, coverage ratchets and isolated database checks pass.",
    ),
    Gate(
        "publication",
        "ci-publication-postgres.yml",
        "isolated_postgresql",
        "Registered PostgreSQL concurrency and publication contracts pass.",
    ),
    Gate("journey", "", "browser_tests", "Required user journeys pass against the CI test server."),
)


class GateResult(TypedDict):
    status: str
    evidence_kind: str
    proves: str
    required: bool


class Summary(TypedDict):
    total_checks: int
    passed: int
    failed: int
    cancelled: int
    skipped: int
    missing: int
    overall_status: str


class Report(TypedDict):
    run_type: str
    timestamp: str
    version: str
    sha: str
    candidate_identity_valid: bool
    checks: dict[str, GateResult]
    summary: Summary
    production_acceptance: str
    deployment_authorized: bool
    defect_inventory: str
    limitation: str


def build_report(results: object, *, sha: str, version: str) -> Report:
    """Fail closed on missing, skipped, cancelled or malformed required job results."""

    checks: dict[str, GateResult] = {}
    statuses = {
        "success": "passed",
        "failure": "failed",
        "cancelled": "cancelled",
        "skipped": "skipped",
    }
    for gate in REQUIRED_GATES:
        entry = results.get(gate.key) if isinstance(results, dict) else None
        result = entry.get("result") if isinstance(entry, dict) else None
        status = statuses.get(result, "missing") if isinstance(result, str) else "missing"
        checks[gate.key] = {
            "status": status,
            "evidence_kind": gate.evidence_kind,
            "proves": gate.proves,
            "required": True,
        }
    counts = {
        status: sum(item["status"] == status for item in checks.values())
        for status in (*statuses.values(), "missing")
    }
    candidate_identity_valid = re.fullmatch(r"[0-9a-f]{40}", sha) is not None
    return {
        "run_type": "rc",
        "timestamp": datetime.now(UTC).isoformat(),
        "version": version,
        "sha": sha,
        "candidate_identity_valid": candidate_identity_valid,
        "checks": checks,
        "summary": {
            "total_checks": len(REQUIRED_GATES),
            "passed": counts["passed"],
            "failed": counts["failed"],
            "cancelled": counts["cancelled"],
            "skipped": counts["skipped"],
            "missing": counts["missing"],
            "overall_status": (
                "passed"
                if candidate_identity_valid and counts["passed"] == len(REQUIRED_GATES)
                else "blocked"
            ),
        },
        "production_acceptance": "unverified",
        "deployment_authorized": False,
        "defect_inventory": "unverified",
        "limitation": "CI evidence covers only the configured checks and test environments. It does not establish zero defects, production readiness, or deployment approval.",
    }


def report_from_environment(*, version: str | None = None) -> Report:
    """Read Actions needs results passed through an environment variable, never shell code."""

    try:
        results: object = json.loads(os.environ.get("CI_JOB_RESULTS", "{}"))
    except json.JSONDecodeError:
        results = None
    return build_report(
        results,
        sha=os.environ.get("GITHUB_SHA", "unknown"),
        version=version if version is not None else os.environ.get("GITHUB_REF_NAME", "unknown"),
    )


def main() -> int:
    """Always retain the report and return nonzero unless every required job passed."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/quality/rc-gate-report.json"))
    args = parser.parse_args()
    report = report_from_environment()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["RC repository verification: " + report["summary"]["overall_status"], ""]
    lines.extend(
        f"- {key}: {value['status']} ({value['evidence_kind']})"
        for key, value in report["checks"].items()
    )
    lines.extend(
        [
            "",
            report["limitation"],
            "Production acceptance: unverified. Deployment authorized: false.",
        ]
    )
    summary = "\n".join(lines) + "\n"
    print(summary)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as stream:
            stream.write(summary)
    return 0 if report["summary"]["overall_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
