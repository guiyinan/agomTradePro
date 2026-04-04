"""
UAT Runner - Execute UAT tests and generate acceptance report.

Usage:
    python tests/uat/run_uat.py
    python tests/uat/run_uat.py --generate-report
    python tests/uat/run_uat.py --journeys=A,B,C
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


class UATRunner:
    """Execute UAT tests and generate reports."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.reports_dir = base_dir / "tests" / "uat" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.test_results: dict[str, Any] = {
            "journeys": {},
            "navigation": {},
            "api": {},
            "defects": [],
            "started_at": None,
            "finished_at": None,
        }

    def _run_pytest_suite(
        self,
        suite_name: str,
        test_targets: list[str],
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run pytest with built-in JUnit XML output for reliable parsing."""
        xml_path = self.reports_dir / f"{suite_name}.xml"
        stdout_path = self.reports_dir / f"{suite_name}.stdout.log"
        stderr_path = self.reports_dir / f"{suite_name}.stderr.log"

        cmd = ["pytest", *test_targets, "-v", f"--junitxml={xml_path}"]
        if extra_args:
            cmd.extend(extra_args)

        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=self.base_dir,
            capture_output=True,
            text=True,
        )

        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")

        return {
            "suite": suite_name,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "xml_path": str(xml_path),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }

    def run_playwright_tests(self, journeys: list[str] | None = None) -> dict[str, Any]:
        """Run Playwright UAT tests."""
        extra_args: list[str] = []
        if journeys:
            marker_expr = " or ".join(f"journey_{journey.lower()}" for journey in journeys)
            extra_args.extend(["-m", marker_expr])

        return self._run_pytest_suite(
            suite_name="playwright_uat",
            test_targets=["tests/playwright/tests/uat/test_user_journeys.py"],
            extra_args=extra_args,
        )

    def run_api_compliance_tests(self) -> dict[str, Any]:
        """Run API compliance and route baseline tests."""
        return self._run_pytest_suite(
            suite_name="uat_api_contracts",
            test_targets=[
                "tests/uat/test_api_naming_compliance.py",
                "tests/uat/test_route_baseline_consistency.py",
            ],
            extra_args=["--tb=short"],
        )

    def check_navigation_links(self) -> dict[str, Any]:
        """Check authenticated navigation links for missing pages or broken redirects."""
        sys.path.insert(0, str(self.base_dir))

        try:
            import os

            import django
            from django.contrib.auth import get_user_model
            from django.test import Client

            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")
            django.setup()

            client = Client()
            user_model = get_user_model()
            user = user_model.objects.create_user(
                username="uat_nav_user",
                password="uat_nav_pass_123",
                email="uat-nav@example.com",
            )
            client.force_login(user)

            urls_to_check = {
                "/dashboard/": {200},
                "/macro/data/": {200},
                "/regime/dashboard/": {200},
                "/signal/manage/": {200},
                "/policy/workbench/": {301, 302},
                "/equity/screen/": {200},
                "/fund/dashboard/": {200},
                "/asset-analysis/screen/": {200},
                "/backtest/create/": {200},
                "/simulated-trading/dashboard/": {200},
                "/audit/reports/": {200},
                "/settings/": {200},
            }

            broken_links: list[dict[str, Any]] = []
            for url, expected_statuses in urls_to_check.items():
                try:
                    response = client.get(url)
                except Exception as exc:  # pragma: no cover - defensive reporting
                    broken_links.append({"url": url, "error": str(exc)})
                    continue

                if response.status_code not in expected_statuses:
                    broken_links.append(
                        {
                            "url": url,
                            "status": response.status_code,
                            "expected": sorted(expected_statuses),
                        }
                    )
                    continue

                if response.status_code in {301, 302} and not response.headers.get("Location"):
                    broken_links.append(
                        {
                            "url": url,
                            "status": response.status_code,
                            "error": "redirect missing Location header",
                        }
                    )

            return {
                "total": len(urls_to_check),
                "broken": broken_links,
                "broken_count": len(broken_links),
            }
        except Exception as exc:  # pragma: no cover - defensive reporting
            return {
                "error": str(exc),
                "broken": [],
                "broken_count": -1,
            }

    def _load_testcases(self, xml_path: str) -> list[dict[str, str]]:
        """Parse JUnit XML into flat testcase records."""
        path = Path(xml_path)
        if not path.exists():
            return []

        root = ET.parse(path).getroot()
        testcases: list[dict[str, str]] = []
        for testcase in root.iter("testcase"):
            status = "passed"
            detail = ""
            if testcase.find("failure") is not None:
                status = "failed"
                detail = testcase.find("failure").attrib.get("message", "").strip()
            elif testcase.find("error") is not None:
                status = "error"
                detail = testcase.find("error").attrib.get("message", "").strip()
            elif testcase.find("skipped") is not None:
                status = "skipped"
                detail = testcase.find("skipped").attrib.get("message", "").strip()

            testcases.append(
                {
                    "classname": testcase.attrib.get("classname", ""),
                    "name": testcase.attrib.get("name", ""),
                    "status": status,
                    "detail": detail,
                }
            )
        return testcases

    def _parse_journey_results(self, results: dict[str, Any]) -> dict[str, Any]:
        """Parse Playwright UAT results from JUnit XML."""
        testcases = self._load_testcases(results["xml_path"])
        journeys: dict[str, dict[str, Any]] = {
            key: {"tests": [], "passed": 0, "total": 0}
            for key in ["A", "B", "C", "D", "E"]
        }

        for testcase in testcases:
            journey_key = self._extract_journey_key(testcase)
            if journey_key is None:
                continue

            journeys[journey_key]["tests"].append(testcase)
            journeys[journey_key]["total"] += 1
            if testcase["status"] == "passed":
                journeys[journey_key]["passed"] += 1

        total = sum(item["total"] for item in journeys.values())
        passed = sum(item["passed"] for item in journeys.values())
        return {
            "exit_code": results["exit_code"],
            "xml_path": results["xml_path"],
            "stdout_path": results["stdout_path"],
            "stderr_path": results["stderr_path"],
            "total": total,
            "passed": passed,
            "journeys": journeys,
        }

    def _parse_api_results(self, results: dict[str, Any]) -> dict[str, Any]:
        """Parse API compliance results from JUnit XML."""
        testcases = self._load_testcases(results["xml_path"])
        total = len(testcases)
        compliant = sum(1 for testcase in testcases if testcase["status"] == "passed")
        violations = [
            testcase
            for testcase in testcases
            if testcase["status"] in {"failed", "error"}
        ]
        skipped = sum(1 for testcase in testcases if testcase["status"] == "skipped")
        coverage = round((compliant / total) * 100, 1) if total else 0.0

        return {
            "exit_code": results["exit_code"],
            "xml_path": results["xml_path"],
            "stdout_path": results["stdout_path"],
            "stderr_path": results["stderr_path"],
            "total": total,
            "compliant": compliant,
            "skipped": skipped,
            "coverage": coverage,
            "violations": violations,
        }

    def _extract_journey_key(self, testcase: dict[str, str]) -> str | None:
        """Map junit testcase to journey A-E."""
        classname = testcase["classname"]
        name = testcase["name"]

        class_match = re.search(r"TestJourney([A-E])", classname)
        if class_match:
            return class_match.group(1)

        name_match = re.search(r"test_([A-E])\d", name)
        if name_match:
            return name_match.group(1)

        return None

    def _collect_defects(self) -> list[dict[str, str]]:
        """Collect failed testcase summaries from parsed results."""
        defects: list[dict[str, str]] = []

        journey_results = self.test_results.get("journeys", {}).get("journeys", {})
        for journey_name, payload in journey_results.items():
            for testcase in payload.get("tests", []):
                if testcase["status"] in {"failed", "error"}:
                    defects.append(
                        {
                            "suite": f"journey_{journey_name}",
                            "test": testcase["name"],
                            "detail": testcase["detail"] or "journey test failed",
                        }
                    )

        for testcase in self.test_results.get("api", {}).get("violations", []):
            defects.append(
                {
                    "suite": "api_contracts",
                    "test": testcase["name"],
                    "detail": testcase["detail"] or "api contract test failed",
                }
            )

        for broken in self.test_results.get("navigation", {}).get("broken", []):
            defects.append(
                {
                    "suite": "navigation",
                    "test": broken.get("url", "unknown"),
                    "detail": broken.get("error") or f"unexpected status {broken.get('status')}",
                }
            )

        return defects

    def _safe_replace(self, template: str, replacements: dict[str, str]) -> str:
        for key, value in replacements.items():
            template = template.replace(f"{{{key}}}", value)

        return re.sub(r"\{[A-Z0-9_]+\}", "-", template)

    def generate_acceptance_report(self) -> str:
        """Generate UAT acceptance report."""
        template_path = self.base_dir / "tests" / "uat" / "uat_acceptance_report_template.md"
        template = template_path.read_text(encoding="utf-8")

        journey_summary = self.test_results.get("journeys", {}).get("journeys", {})
        total_tests = sum(item.get("total", 0) for item in journey_summary.values())
        passed_tests = sum(item.get("passed", 0) for item in journey_summary.values())
        pass_rate = (passed_tests / total_tests * 100) if total_tests else 0.0
        api_coverage = self.test_results.get("api", {}).get("coverage", 0.0)
        broken_count = self.test_results.get("navigation", {}).get("broken_count", "N/A")
        defects = self.test_results.get("defects", [])
        all_pass = (
            self.test_results.get("journeys", {}).get("exit_code", 1) == 0
            and self.test_results.get("api", {}).get("exit_code", 1) == 0
            and broken_count == 0
        )

        started_at = self.test_results.get("started_at")
        finished_at = self.test_results.get("finished_at")
        duration = "-"
        if started_at and finished_at:
            duration = str(finished_at - started_at).split(".")[0]

        replacements = {
            "DATE": datetime.now().strftime("%Y-%m-%d"),
            "PASS_RATE": f"{pass_rate:.1f}",
            "404_COUNT": str(broken_count),
            "DEFECT_COUNT": str(len(defects)),
            "API_COVERAGE": f"{api_coverage:.1f}",
            "STATUS": "PASS" if all_pass else "FAIL",
            "CONCLUSION": "验收通过" if all_pass else "验收不通过，请修复问题后重新测试",
            "A_PASS": str(journey_summary.get("A", {}).get("passed", 0)),
            "A_TOTAL": str(journey_summary.get("A", {}).get("total", 0)),
            "B_PASS": str(journey_summary.get("B", {}).get("passed", 0)),
            "B_TOTAL": str(journey_summary.get("B", {}).get("total", 0)),
            "C_PASS": str(journey_summary.get("C", {}).get("passed", 0)),
            "C_TOTAL": str(journey_summary.get("C", {}).get("total", 0)),
            "D_PASS": str(journey_summary.get("D", {}).get("passed", 0)),
            "D_TOTAL": str(journey_summary.get("D", {}).get("total", 0)),
            "E_PASS": str(journey_summary.get("E", {}).get("passed", 0)),
            "E_TOTAL": str(journey_summary.get("E", {}).get("total", 0)),
            "404_LIST": ", ".join(
                broken.get("url", "unknown")
                for broken in self.test_results.get("navigation", {}).get("broken", [])
            ) or "无",
            "START_TIME": started_at.strftime("%Y-%m-%d %H:%M:%S") if started_at else "-",
            "END_TIME": finished_at.strftime("%Y-%m-%d %H:%M:%S") if finished_at else "-",
            "DURATION": duration,
            "TOTAL_CASES": str(total_tests),
            "ENV": "local development",
            "BROWSER": "chromium",
            "RESOLUTION": "1280x900",
            "TEST_DATA": "pytest fixtures + local sqlite",
            "NOTES": "-",
            "ISSUE": "-",
            "OVERALL": "-",
            "SCORE": "-",
            "ID": defects[0]["suite"] if defects else "-",
            "TITLE": defects[0]["test"] if defects else "-",
            "LOCATION": defects[0]["detail"] if defects else "-",
            "SCREENSHOT": "-",
            "ISSUE_TITLE": defects[0]["test"] if defects else "-",
            "P0_ITEM_1": defects[0]["detail"] if defects else "-",
            "P0_ITEM_2": defects[1]["detail"] if len(defects) > 1 else "-",
            "P1_ITEM_1": "-",
            "P1_ITEM_2": "-",
            "P2_ITEM_1": "-",
            "P2_ITEM_2": "-",
            "QA_NAME": "-",
            "PO_NAME": "-",
            "TECH_LEAD": "-",
            "SIGN": "-",
        }

        report = self._safe_replace(template, replacements)
        report_path = self.reports_dir / f"uat_acceptance_report_{datetime.now().strftime('%Y%m%d')}.md"
        report_path.write_text(report, encoding="utf-8")
        return str(report_path)

    def run_full_uat(self, journeys: list[str] | None = None) -> dict[str, Any]:
        """Run full UAT suite."""
        self.test_results["started_at"] = datetime.now()
        print("=" * 60)
        print("AgomTradePro UAT Execution")
        print("=" * 60)
        print()

        print("[1/4] Running User Journey Tests...")
        journey_results = self.run_playwright_tests(journeys)
        print(f"  Exit code: {journey_results['exit_code']}")
        self.test_results["journeys"] = self._parse_journey_results(journey_results)

        print("\n[2/4] Running API Compliance Tests...")
        api_results = self.run_api_compliance_tests()
        print(f"  Exit code: {api_results['exit_code']}")
        self.test_results["api"] = self._parse_api_results(api_results)

        print("\n[3/4] Checking Navigation Links...")
        nav_results = self.check_navigation_links()
        print(f"  Broken links: {nav_results.get('broken_count', 0)}")
        self.test_results["navigation"] = nav_results

        self.test_results["defects"] = self._collect_defects()
        self.test_results["finished_at"] = datetime.now()

        print("\n[4/4] Generating Acceptance Report...")
        report_path = self.generate_acceptance_report()
        print(f"  Report saved to: {report_path}")

        print()
        print("=" * 60)
        print("UAT Execution Summary")
        print("=" * 60)
        print(
            f"Journey tests: {'PASS' if self.test_results['journeys']['exit_code'] == 0 else 'FAIL'}"
        )
        print(f"API compliance: {'PASS' if self.test_results['api']['exit_code'] == 0 else 'FAIL'}")
        print(f"Navigation: {'PASS' if nav_results.get('broken_count', 0) == 0 else 'FAIL'}")
        print(f"Defects: {len(self.test_results['defects'])}")
        print(f"Report: {report_path}")
        print("=" * 60)
        return self.test_results


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run UAT tests for AgomTradePro")
    parser.add_argument(
        "--journeys",
        type=str,
        help="Comma-separated list of journey IDs (A,B,C,D,E)",
    )
    parser.add_argument(
        "--generate-report",
        action="store_true",
        help="Generate report only (skip tests)",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Project base directory",
    )

    args = parser.parse_args()
    runner = UATRunner(args.base_dir)

    if args.generate_report:
        report_path = runner.generate_acceptance_report()
        print(f"Report generated: {report_path}")
        return 0

    journeys = None
    if args.journeys:
        journeys = [journey.strip().upper() for journey in args.journeys.split(",")]

    results = runner.run_full_uat(journeys)
    all_pass = (
        results.get("journeys", {}).get("exit_code", 1) == 0
        and results.get("api", {}).get("exit_code", 1) == 0
        and results.get("navigation", {}).get("broken_count", -1) == 0
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
