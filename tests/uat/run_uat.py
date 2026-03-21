"""
UAT Runner - Execute all UAT tests and generate acceptance report.

Usage:
    python tests/uat/run_uat.py
    python tests/uat/run_uat.py --generate-report
    python tests/uat/run_uat.py -- journeys=A,B,C
"""
import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json


class UATRunner:
    """Execute UAT tests and generate reports."""

    def __init__(self, base_dir: Path):
        """Initialize UAT runner.

        Args:
            base_dir: Project base directory
        """
        self.base_dir = base_dir
        self.reports_dir = base_dir / "tests" / "uat" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.test_results = {
            "journeys": {},
            "visual": {},
            "navigation": {},
            "api": {},
            "defects": [],
        }

    def run_playwright_tests(self, journeys: Optional[List[str]] = None) -> Dict:
        """Run Playwright UAT tests.

        Args:
            journeys: List of journey IDs to run (A, B, C, D, E). None for all.

        Returns:
            Test results dictionary
        """
        cmd = ["pytest", "tests/playwright/tests/uat/test_user_journeys.py", "-v"]

        # Add journey filters if specified
        if journeys:
            journey_marks = []
            for j in journeys:
                journey_marks.append(f"-m")
                journey_marks.append(f"journey_{j.lower()}")
            cmd.extend(journey_marks)

        # Add output options
        cmd.extend([
            "--html", str(self.reports_dir / "playwright_uat.html"),
            "--self-contained-html",
            "-o", "log_cli=true",
        ])

        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=self.base_dir,
            capture_output=True,
            text=True
        )

        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def run_api_compliance_tests(self) -> Dict:
        """Run API naming compliance tests.

        Returns:
            Test results dictionary
        """
        cmd = [
            "pytest", "tests/uat/test_api_naming_compliance.py",
            "-v",
            "--tb=short",
        ]

        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=self.base_dir,
            capture_output=True,
            text=True
        )

        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def check_navigation_links(self) -> Dict:
        """Check navigation links for 404 errors.

        Returns:
            Check results with broken links
        """
        # Import URL configuration
        sys.path.insert(0, str(self.base_dir))

        try:
            from django.urls import get_resolver
            from django.test import Client

            # Initialize Django
            import django
            from django.conf import settings

            if not settings.configured:
                # Minimal config for testing
                import os
                os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
                django.setup()

            client = Client()
            resolver = get_resolver()

            # Collect all URL patterns
            urls_to_check = [
                "/dashboard/",
                "/macro/data/",
                "/regime/dashboard/",
                "/signal/manage/",
                "/policy/manage/",
                "/equity/screen/",
                "/fund/dashboard/",
                "/asset-analysis/screen/",
                "/backtest/create/",
                "/simulated-trading/dashboard/",
                "/audit/reports/",
                "/ops/",
            ]

            broken_links = []
            for url in urls_to_check:
                try:
                    response = client.get(url)
                    if response.status_code == 404:
                        broken_links.append({
                            "url": url,
                            "status": 404,
                        })
                except Exception as e:
                    broken_links.append({
                        "url": url,
                        "error": str(e),
                    })

            return {
                "total": len(urls_to_check),
                "broken": broken_links,
                "broken_count": len(broken_links),
            }

        except Exception as e:
            return {
                "error": str(e),
                "broken": [],
                "broken_count": -1,
            }

    def generate_acceptance_report(self) -> str:
        """Generate UAT acceptance report.

        Returns:
            Path to generated report
        """
        # Read template
        template_path = self.base_dir / "tests" / "uat" / "uat_acceptance_report_template.md"
        template = template_path.read_text(encoding="utf-8")

        # Fill in template variables
        report_date = datetime.now().strftime("%Y-%m-%d")

        # Calculate metrics
        total_tests = sum(len(j.get("tests", [])) for j in self.test_results["journeys"].values())
        passed_tests = sum(len([t for t in j.get("tests", []) if t.get("status") == "pass"])
                          for j in self.test_results["journeys"].values())
        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        # Fill placeholders
        report = template.replace("{DATE}", report_date)
        report = report.replace("{PASS_RATE}", f"{pass_rate:.1f}")
        report = report.replace("{404_COUNT}", str(self.test_results.get("navigation", {}).get("broken_count", "N/A")))
        report = report.replace("{DEFECT_COUNT}", str(len(self.test_results.get("defects", []))))
        report = report.replace("{API_COVERAGE}", "100")  # To be calculated

        # Determine overall status
        all_pass = (
            pass_rate >= 90 and
            self.test_results.get("navigation", {}).get("broken_count", 0) == 0 and
            len(self.test_results.get("defects", [])) <= 2
        )
        report = report.replace("{STATUS}", "PASS" if all_pass else "FAIL")
        report = report.replace("{CONCLUSION}",
            "验收通过" if all_pass else "验收不通过，请修复问题后重新测试")

        # Write report
        report_path = self.reports_dir / f"uat_acceptance_report_{report_date.replace('-', '')}.md"
        report_path.write_text(report, encoding="utf-8")

        return str(report_path)

    def run_full_uat(self, journeys: Optional[List[str]] = None) -> Dict:
        """Run full UAT suite.

        Args:
            journeys: List of journey IDs to run. None for all.

        Returns:
            Complete UAT results
        """
        print("=" * 60)
        print("AgomTradePro UAT Execution")
        print("=" * 60)
        print()

        # 1. Run Playwright journey tests
        print("[1/4] Running User Journey Tests...")
        journey_results = self.run_playwright_tests(journeys)
        print(f"  Exit code: {journey_results['exit_code']}")
        self.test_results["journeys"] = self._parse_journey_results(journey_results)

        # 2. Run API compliance tests
        print("\n[2/4] Running API Compliance Tests...")
        api_results = self.run_api_compliance_tests()
        print(f"  Exit code: {api_results['exit_code']}")
        self.test_results["api"] = self._parse_api_results(api_results)

        # 3. Check navigation links
        print("\n[3/4] Checking Navigation Links...")
        nav_results = self.check_navigation_links()
        print(f"  Broken links: {nav_results.get('broken_count', 0)}")
        self.test_results["navigation"] = nav_results

        # 4. Generate report
        print("\n[4/4] Generating Acceptance Report...")
        report_path = self.generate_acceptance_report()
        print(f"  Report saved to: {report_path}")

        # Summary
        print()
        print("=" * 60)
        print("UAT Execution Summary")
        print("=" * 60)
        print(f"Journey tests: {'PASS' if journey_results['exit_code'] == 0 else 'FAIL'}")
        print(f"API compliance: {'PASS' if api_results['exit_code'] == 0 else 'FAIL'}")
        print(f"Navigation: {'PASS' if nav_results.get('broken_count', 0) == 0 else 'FAIL'}")
        print(f"Report: {report_path}")
        print("=" * 60)

        return self.test_results

    def _parse_journey_results(self, results: Dict) -> Dict:
        """Parse journey test results from pytest output.

        Args:
            results: Raw test execution results

        Returns:
            Parsed journey results
        """
        # Parse stdout for test results
        # This is a simplified version - in production, use pytest JSON output
        return {
            "A": {"tests": [], "passed": 0, "total": 4},
            "B": {"tests": [], "passed": 0, "total": 4},
            "C": {"tests": [], "passed": 0, "total": 4},
            "D": {"tests": [], "passed": 0, "total": 3},
            "E": {"tests": [], "passed": 0, "total": 3},
        }

    def _parse_api_results(self, results: Dict) -> Dict:
        """Parse API compliance test results.

        Args:
            results: Raw test execution results

        Returns:
            Parsed API results
        """
        return {
            "total": 0,
            "compliant": 0,
            "violations": [],
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run UAT tests for AgomTradePro")
    parser.add_argument(
        "--journeys",
        type=str,
        help="Comma-separated list of journey IDs (A,B,C,D,E)"
    )
    parser.add_argument(
        "--generate-report",
        action="store_true",
        help="Generate report only (skip tests)"
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Project base directory"
    )

    args = parser.parse_args()

    runner = UATRunner(args.base_dir)

    if args.generate_report:
        report_path = runner.generate_acceptance_report()
        print(f"Report generated: {report_path}")
        return 0

    journeys = None
    if args.journeys:
        journeys = [j.strip().upper() for j in args.journeys.split(",")]

    results = runner.run_full_uat(journeys)

    # Exit with appropriate code
    all_pass = (
        results.get("journeys", {}).get("exit_code", -1) == 0 and
        results.get("api", {}).get("exit_code", -1) == 0 and
        results.get("navigation", {}).get("broken_count", -1) == 0
    )

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
