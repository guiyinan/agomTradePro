#!/usr/bin/env python
"""Run the focused post-0.8.0 stabilization check bundles."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_LIMIT = 12000


@dataclass(frozen=True)
class SuiteDefinition:
    """Static description for one stabilization suite."""

    key: str
    priority: str
    description: str
    command: tuple[str, ...]
    timeout_seconds: int


SUITES: dict[str, SuiteDefinition] = {
    "readiness_monitor": SuiteDefinition(
        key="readiness_monitor",
        priority="P0",
        description="Strict readiness monitor and scheduler-runtime gate.",
        command=(
            sys.executable,
            "manage.py",
            "show_personal_readiness_status",
            "--json",
            "--strict-monitor",
            "--require-local-scheduler-runtime",
        ),
        timeout_seconds=180,
    ),
    "healthcheck": SuiteDefinition(
        key="healthcheck",
        priority="P0",
        description="System health, DB, queue, decision-data, and Alpha workspace checks.",
        command=(sys.executable, "manage.py", "healthcheck", "--json"),
        timeout_seconds=180,
    ),
    "alpha_ops": SuiteDefinition(
        key="alpha_ops",
        priority="P1",
        description="Alpha production-path regression bundle.",
        command=(sys.executable, "scripts/run_alpha_ops_regression.py"),
        timeout_seconds=900,
    ),
    "data_center": SuiteDefinition(
        key="data_center",
        priority="P1",
        description="Data Center decision-chain regression suite.",
        command=(sys.executable, "-m", "pytest", "tests/unit/data_center", "-q"),
        timeout_seconds=900,
    ),
    "risk_center": SuiteDefinition(
        key="risk_center",
        priority="P1",
        description="Risk Center, strategy, and simulated-trading guardrail coverage.",
        command=(
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/risk_center",
            "tests/integration/risk_center",
            "tests/integration/strategy/test_execution_orchestrator_idempotency.py",
            "tests/api/test_simulated_trading_api_edges.py",
            "-q",
        ),
        timeout_seconds=900,
    ),
    "tui_operator": SuiteDefinition(
        key="tui_operator",
        priority="P1",
        description="TUI workbench and operator black-box regression bundle.",
        command=(
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_tui_workbench.py",
            "tests/unit/test_tui_operator_services.py",
            "tests/unit/test_tui_operator_api.py",
            "tests/integration/agent_runtime/test_operator_pages.py",
            "-q",
        ),
        timeout_seconds=900,
    ),
    "governance": SuiteDefinition(
        key="governance",
        priority="P2",
        description="Governance baseline and large-file regression check.",
        command=(
            sys.executable,
            "scripts/check_governance_consistency.py",
            "--baseline",
            "governance/governance_baseline.json",
            "--format",
            "text",
        ),
        timeout_seconds=300,
    ),
}

DEFAULT_SUITES = tuple(SUITES.keys())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the post-0.8.0 stabilization check bundles and optionally write reports.",
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=sorted(SUITES),
        help="Run only the selected suite. Repeat to run multiple suites.",
    )
    parser.add_argument(
        "--list-suites",
        action="store_true",
        help="Print the available suite keys and exit.",
    )
    parser.add_argument(
        "--write-json",
        help="Write the JSON report to this path.",
    )
    parser.add_argument(
        "--write-md",
        help="Write the Markdown report to this path.",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Keep running later suites even after a failure.",
    )
    parser.add_argument(
        "--output-limit",
        type=int,
        default=DEFAULT_OUTPUT_LIMIT,
        help="Maximum stdout/stderr characters stored per suite in the report.",
    )
    return parser.parse_args()


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _shell_line(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _trim_output(text: str, limit: int) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean
    head = clean[: limit // 2].rstrip()
    tail = clean[-(limit // 2) :].lstrip()
    return f"{head}\n...\n{tail}"


def run_suite(definition: SuiteDefinition, *, output_limit: int) -> dict[str, Any]:
    started_at = _iso_now()
    command = tuple(definition.command)
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=definition.timeout_seconds,
            env=env,
            check=False,
        )
        status = "passed" if completed.returncode == 0 else "failed"
        return {
            "suite": definition.key,
            "priority": definition.priority,
            "description": definition.description,
            "command": list(command),
            "command_display": _shell_line(command),
            "status": status,
            "exit_code": int(completed.returncode),
            "timed_out": False,
            "started_at": started_at,
            "finished_at": _iso_now(),
            "stdout": _trim_output(completed.stdout or "", output_limit),
            "stderr": _trim_output(completed.stderr or "", output_limit),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "suite": definition.key,
            "priority": definition.priority,
            "description": definition.description,
            "command": list(command),
            "command_display": _shell_line(command),
            "status": "timeout",
            "exit_code": None,
            "timed_out": True,
            "started_at": started_at,
            "finished_at": _iso_now(),
            "stdout": _trim_output(exc.stdout or "", output_limit),
            "stderr": _trim_output(exc.stderr or "", output_limit),
        }


def build_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [result for result in results if result["status"] != "passed"]
    return {
        "generated_at": _iso_now(),
        "repo_root": str(REPO_ROOT),
        "suite_count": len(results),
        "failed_suite_count": len(failed),
        "status": "passed" if not failed else "failed",
        "results": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Post-0.8.0 Stabilization Check Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Repo root: `{report['repo_root']}`",
        f"- Overall status: `{report['status']}`",
        f"- Suite count: `{report['suite_count']}`",
        f"- Failed suite count: `{report['failed_suite_count']}`",
        "",
        "## Suite Summary",
        "",
    ]
    for result in report["results"]:
        lines.append(
            f"- `{result['priority']}` `{result['suite']}`: `{result['status']}`"
        )
    for result in report["results"]:
        lines.extend(
            [
                "",
                f"## {result['suite']}",
                "",
                f"- Priority: `{result['priority']}`",
                f"- Status: `{result['status']}`",
                f"- Command: `{result['command_display']}`",
                f"- Started at: `{result['started_at']}`",
                f"- Finished at: `{result['finished_at']}`",
            ]
        )
        if result["stdout"]:
            lines.extend(["", "### Stdout", "", "```text", result["stdout"], "```"])
        if result["stderr"]:
            lines.extend(["", "### Stderr", "", "```text", result["stderr"], "```"])
    return "\n".join(lines) + "\n"


def write_text(path_value: str, content: str) -> None:
    path = Path(path_value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def emit_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")


def main() -> int:
    args = parse_args()
    if args.list_suites:
        for definition in SUITES.values():
            print(f"{definition.key}: {definition.priority} - {definition.description}")
        return 0

    suite_keys = tuple(args.suite or DEFAULT_SUITES)
    results: list[dict[str, Any]] = []
    for suite_key in suite_keys:
        result = run_suite(SUITES[suite_key], output_limit=args.output_limit)
        results.append(result)
        if result["status"] != "passed" and not args.continue_on_failure:
            break

    report = build_report(results)

    if args.write_json:
        write_text(args.write_json, json.dumps(report, ensure_ascii=False, indent=2))
    if args.write_md:
        write_text(args.write_md, render_markdown(report))

    emit_json(report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
