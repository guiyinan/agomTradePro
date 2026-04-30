#!/usr/bin/env python
"""
Unified local regression entrypoint for AgomTradePro.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_MODULE = "core.settings.development_sqlite"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010


def _extract_json_payload(raw_text: str) -> object:
    stripped = raw_text.strip()
    if not stripped:
        return []

    for opening, closing in (("{", "}"), ("[", "]")):
        start = stripped.find(opening)
        end = stripped.rfind(closing)
        if start != -1 and end != -1 and end > start:
            candidate = stripped[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    return json.loads(stripped)


@dataclass(frozen=True)
class Step:
    name: str
    runner: Callable[[], None]


class RegressionRunner:
    def __init__(self, reports_dir: Path, settings_module: str, host: str, port: int):
        self.reports_dir = reports_dir
        self.settings_module = settings_module
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.security_dir = reports_dir / "security"
        self.browser_dir = reports_dir / "browser"
        self.manifest_path = reports_dir / "manifest.json"
        self.results: list[dict[str, object]] = []

    def run_command(self, name: str, command: list[str]) -> None:
        print("")
        print("=" * 80)
        print(name)
        print("=" * 80)
        print(" ".join(command))
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        self.results.append(
            {
                "name": name,
                "command": command,
                "exit_code": completed.returncode,
            }
        )
        self._write_manifest()
        if completed.returncode != 0:
            raise RuntimeError(f"{name} failed with exit code {completed.returncode}")

    def _write_manifest(self) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "base_url": self.base_url,
            "settings_module": self.settings_module,
            "results": self.results,
        }
        self.manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def run_bandit(self) -> None:
        self.security_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = REPO_ROOT / "reports" / "security" / "bandit-baseline.json"
        report_path = self.security_dir / "bandit-report.json"
        command = [
            "bandit",
            "-r",
            "apps/",
            "core/",
            "shared/",
            "-f",
            "json",
            "-o",
            str(report_path),
            "--baseline",
            str(baseline_path),
        ]
        print("")
        print("=" * 80)
        print("Security: Bandit")
        print("=" * 80)
        print(" ".join(command))
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        self.results.append(
            {
                "name": "Security: Bandit",
                "command": command,
                "exit_code": completed.returncode,
            }
        )
        self._write_manifest()
        if not report_path.exists():
            raise RuntimeError("Bandit did not generate a JSON report.")
        data = json.loads(report_path.read_text(encoding="utf-8"))
        results = data.get("results", [])
        new_critical = [
            item
            for item in results
            if item.get("issue_severity") == "CRITICAL" and not item.get("is_baseline", False)
        ]
        new_high = [
            item
            for item in results
            if item.get("issue_severity") == "HIGH" and not item.get("is_baseline", False)
        ]
        if new_high:
            print(f"[warning] Bandit found {len(new_high)} new HIGH issues.")
        if new_critical:
            raise RuntimeError(f"Bandit found {len(new_critical)} new CRITICAL issues.")

    def run_safety(self) -> None:
        self.security_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.security_dir / "safety-report.json"
        command = [
            "safety",
            "check",
            "-r",
            "requirements-dev.txt",
            "--json",
        ]
        print("")
        print("=" * 80)
        print("Security: Safety")
        print("=" * 80)
        print(" ".join(command))
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        report_path.write_text(completed.stdout or completed.stderr, encoding="utf-8")
        self.results.append(
            {
                "name": "Security: Safety",
                "command": command,
                "exit_code": completed.returncode,
            }
        )
        self._write_manifest()
        data = _extract_json_payload(report_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            meta = data.get("report_meta", {})
            vulnerability_count = int(meta.get("vulnerabilities_found", 0))
        elif isinstance(data, list):
            vulnerability_count = len(data)
        else:
            vulnerability_count = 0
        if vulnerability_count > 0:
            raise RuntimeError(f"Safety found {vulnerability_count} known vulnerabilities.")

    def run_pip_audit(self) -> None:
        self.security_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.security_dir / "pip-audit-report.json"
        command = [
            "pip-audit",
            "-r",
            "requirements-dev.txt",
            "--format",
            "json",
            "--output",
            str(report_path),
        ]
        print("")
        print("=" * 80)
        print("Security: pip-audit")
        print("=" * 80)
        print(" ".join(command))
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        self.results.append(
            {
                "name": "Security: pip-audit",
                "command": command,
                "exit_code": completed.returncode,
            }
        )
        self._write_manifest()
        if not report_path.exists():
            raise RuntimeError("pip-audit did not generate a JSON report.")
        data = json.loads(report_path.read_text(encoding="utf-8"))
        dependencies = data.get("dependencies", []) if isinstance(data, dict) else []
        vulnerability_count = sum(len(dep.get("vulns", [])) for dep in dependencies)
        if vulnerability_count > 0:
            raise RuntimeError(f"pip-audit found {vulnerability_count} known vulnerabilities.")

    def run_browser_suite(self, suite_name: str, target: str, min_tests: int) -> None:
        self.browser_dir.mkdir(parents=True, exist_ok=True)
        junitxml = self.browser_dir / f"{suite_name}.xml"
        server_log = self.browser_dir / f"{suite_name}.server.log"
        pytest_log = self.browser_dir / f"{suite_name}.pytest.log"
        command = [
            sys.executable,
            "scripts/run_live_server_pytest.py",
            "--suite-name",
            suite_name,
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--base-url",
            self.base_url,
            "--settings-module",
            self.settings_module,
            "--health-timeout",
            "180",
            "--min-tests",
            str(min_tests),
            "--junitxml",
            str(junitxml),
            "--server-log",
            str(server_log),
            "--pytest-log",
            str(pytest_log),
            "--",
            target,
            "-q",
            "--browser",
            "chromium",
            "--screenshot=only-on-failure",
            "--video=retain-on-failure",
        ]
        self.run_command(f"Browser: {suite_name}", command)

    def app_test_targets(self) -> list[str]:
        return sorted(
            path.as_posix()
            for path in (REPO_ROOT / "apps").glob("*/tests")
            if path.is_dir()
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local full regression matrix.")
    parser.add_argument(
        "--stages",
        default="preflight,backend,browser,rc",
        help="Comma-separated stages to run: preflight, backend, browser, rc.",
    )
    parser.add_argument(
        "--reports-dir",
        help="Optional reports directory. Defaults to reports/full-regression/<timestamp>.",
    )
    parser.add_argument(
        "--settings-module",
        default=DEFAULT_SETTINGS_MODULE,
        help="DJANGO_SETTINGS_MODULE for managed browser suites.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host for managed browser suites.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port for managed browser suites.",
    )
    return parser.parse_args()


def _build_reports_dir(raw_value: str | None) -> Path:
    if raw_value:
        return (REPO_ROOT / raw_value).resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (REPO_ROOT / "reports" / "full-regression" / timestamp).resolve()


def main() -> int:
    args = _parse_args()
    reports_dir = _build_reports_dir(args.reports_dir)
    runner = RegressionRunner(reports_dir, args.settings_module, args.host, args.port)

    app_tests = runner.app_test_targets()
    steps_by_stage: dict[str, list[Step]] = {
        "preflight": [
            Step(
                "Consistency: route strict",
                lambda: runner.run_command(
                    "Consistency: route strict",
                    [sys.executable, "scripts/check_routes.py", "--strict"],
                ),
            ),
            Step(
                "Consistency: doc/route/sdk",
                lambda: runner.run_command(
                    "Consistency: doc/route/sdk",
                    [
                        sys.executable,
                        "scripts/check_doc_route_sdk_consistency.py",
                        "--baseline",
                        "reports/consistency/baseline.json",
                    ],
                ),
            ),
            Step(
                "Architecture: verify boundaries",
                lambda: runner.run_command(
                    "Architecture: verify boundaries",
                    [
                        sys.executable,
                        "scripts/verify_architecture.py",
                        "--rules-file",
                        "governance/architecture_rules.json",
                        "--format",
                        "text",
                    ],
                ),
            ),
            Step(
                "Architecture: audit report",
                lambda: runner.run_command(
                    "Architecture: audit report",
                    [
                        sys.executable,
                        "scripts/verify_architecture.py",
                        "--rules-file",
                        "governance/architecture_rules.json",
                        "--format",
                        "text",
                        "--include-audit",
                        "--write-report",
                        str(runner.reports_dir / "architecture-audit.json"),
                        "--write-ledger",
                        str(runner.reports_dir / "module-ledger.md"),
                    ],
                ),
            ),
            Step("Security: Bandit", runner.run_bandit),
            Step("Security: Safety", runner.run_safety),
            Step("Security: pip-audit", runner.run_pip_audit),
        ],
        "backend": [
            Step(
                "Pytest: guardrails",
                lambda: runner.run_command(
                    "Pytest: guardrails",
                    [sys.executable, "-m", "pytest", "tests/guardrails", "-q"],
                ),
            ),
            Step(
                "Pytest: unit",
                lambda: runner.run_command(
                    "Pytest: unit",
                    [sys.executable, "-m", "pytest", "tests/unit", "-q"],
                ),
            ),
            Step(
                "Pytest: api+migrations",
                lambda: runner.run_command(
                    "Pytest: api+migrations",
                    [sys.executable, "-m", "pytest", "tests/api", "tests/migrations", "-q"],
                ),
            ),
            Step(
                "Pytest: integration",
                lambda: runner.run_command(
                    "Pytest: integration",
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "tests/integration",
                        "-m",
                        "not live_required and not optional_runtime and not diagnostic",
                        "-q",
                    ],
                ),
            ),
            Step(
                "Pytest: app-local",
                lambda: runner.run_command(
                    "Pytest: app-local",
                    [sys.executable, "-m", "pytest", *app_tests, "-q"],
                ),
            ),
            Step(
                "Pytest: e2e",
                lambda: runner.run_command(
                    "Pytest: e2e",
                    [sys.executable, "-m", "pytest", "tests/e2e", "-q"],
                ),
            ),
        ],
        "browser": [
            Step(
                "Browser: smoke",
                lambda: runner.run_browser_suite(
                    "playwright-smoke",
                    "tests/playwright/tests/smoke",
                    min_tests=10,
                ),
            ),
            Step(
                "Browser: uat",
                lambda: runner.run_browser_suite(
                    "playwright-uat",
                    "tests/playwright/tests/uat",
                    min_tests=20,
                ),
            ),
        ],
        "rc": [
            Step(
                "RC: route strict",
                lambda: runner.run_command(
                    "RC: route strict",
                    [sys.executable, "scripts/check_routes.py", "--strict"],
                ),
            ),
            Step(
                "RC: navigation 404",
                lambda: runner.run_command(
                    "RC: navigation 404",
                    [sys.executable, "-m", "pytest", "tests/e2e", "-k", "navigation", "-v", "--tb=short"],
                ),
            ),
            Step(
                "RC: main chain 501",
                lambda: runner.run_command(
                    "RC: main chain 501",
                    [sys.executable, "-m", "pytest", "tests/guardrails", "-k", "501 or guardrail", "-v", "--tb=short"],
                ),
            ),
            Step(
                "RC: app-local tests",
                lambda: runner.run_command(
                    "RC: app-local tests",
                    [sys.executable, "-m", "pytest", *app_tests, "-v", "--tb=short"],
                ),
            ),
            Step(
                "RC: api+migrations",
                lambda: runner.run_command(
                    "RC: api+migrations",
                    [sys.executable, "-m", "pytest", "tests/api", "tests/migrations", "-v", "--tb=short"],
                ),
            ),
            Step(
                "RC: journey tests",
                lambda: runner.run_browser_suite(
                    "rc-journey-tests",
                    "tests/playwright/tests/uat",
                    min_tests=20,
                ),
            ),
            Step(
                "RC: logic guardrails",
                lambda: runner.run_command(
                    "RC: logic guardrails",
                    [sys.executable, "-m", "pytest", "tests/guardrails/test_logic_guardrails.py", "-v", "--tb=short"],
                ),
            ),
            Step(
                "RC: architecture guard",
                lambda: runner.run_command(
                    "RC: architecture guard",
                    [
                        sys.executable,
                        "scripts/verify_architecture.py",
                        "--rules-file",
                        "governance/architecture_rules.json",
                        "--format",
                        "text",
                    ],
                ),
            ),
        ],
    }

    requested_stages = [stage.strip() for stage in args.stages.split(",") if stage.strip()]
    unknown = [stage for stage in requested_stages if stage not in steps_by_stage]
    if unknown:
        print(f"Unknown stages: {', '.join(unknown)}", file=sys.stderr)
        return 2

    try:
        for stage in requested_stages:
            print("")
            print("#" * 80)
            print(f"Stage: {stage}")
            print("#" * 80)
            for step in steps_by_stage[stage]:
                step.runner()
    except Exception as exc:
        print("")
        print(f"[full-regression] Failed: {exc}", file=sys.stderr)
        print(f"[full-regression] Reports: {reports_dir}", file=sys.stderr)
        return 1

    print("")
    print(f"[full-regression] Completed successfully. Reports: {reports_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
