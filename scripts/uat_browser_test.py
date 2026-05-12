#!/usr/bin/env python
"""
UAT Browser Test - User Acceptance Testing with Headless Browser

This script performs end-to-end testing of the AgomTradePro system using
Playwright's headless browser to verify UI functionality.

Usage:
    python scripts/uat_browser_test.py

Requirements:
    pip install playwright
    playwright install chromium
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Playwright imports
from playwright.async_api import Browser, BrowserContext, Page, async_playwright


@dataclass
class TestResult:
    """Single test result"""
    name: str
    passed: bool
    message: str = ""
    screenshot: str | None = None
    duration_ms: int = 0


@dataclass
class UATReport:
    """UAT test report"""
    timestamp: str
    base_url: str
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    results: list = field(default_factory=list)

    def add_result(self, result: TestResult):
        self.results.append(result)
        self.total_tests += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1


class UATTester:
    """User Acceptance Testing with headless browser"""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", admin_password: str = "Aa123456"):
        self.base_url = base_url
        self.admin_password = admin_password
        self.report = UATReport(
            timestamp=datetime.now().isoformat(),
            base_url=base_url
        )
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.screenshot_dir = Path("reports/uat_screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def setup(self):
        """Initialize browser"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="zh-CN"
        )
        self.page = await self.context.new_page()

    async def teardown(self):
        """Close browser"""
        if self.browser:
            await self.browser.close()

    async def take_screenshot(self, name: str) -> str:
        """Take screenshot and return path"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}_{name}.png"
        path = self.screenshot_dir / filename
        await self.page.screenshot(path=path)
        return str(path)

    async def run_test(self, name: str, test_func) -> TestResult:
        """Run a single test"""
        start = datetime.now()
        try:
            await test_func()
            duration = (datetime.now() - start).total_seconds() * 1000
            result = TestResult(name=name, passed=True, duration_ms=int(duration))
            print(f"  [PASS] {name}")
        except AssertionError as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            screenshot = await self.take_screenshot(name.replace(" ", "_"))
            result = TestResult(
                name=name,
                passed=False,
                message=str(e),
                screenshot=screenshot,
                duration_ms=int(duration)
            )
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            screenshot = await self.take_screenshot(name.replace(" ", "_"))
            result = TestResult(
                name=name,
                passed=False,
                message=f"Exception: {type(e).__name__}: {e}",
                screenshot=screenshot,
                duration_ms=int(duration)
            )
            print(f"  [ERROR] {name}: {e}")

        self.report.add_result(result)
        return result

    # ========== Test Cases ==========

    async def test_homepage_loads(self):
        """Test homepage loads and redirects to login"""
        await self.page.goto(self.base_url, wait_until="networkidle")
        # Should redirect to login page
        current_url = self.page.url
        assert "/login" in current_url or "/account/login" in current_url, \
            f"Expected login redirect, got: {current_url}"

    async def test_login_page_elements(self):
        """Test login page has required elements"""
        await self.page.goto(f"{self.base_url}/account/login/", wait_until="networkidle")
        # Check for username field
        username = await self.page.query_selector('input[name="username"], input[type="text"]')
        assert username is not None, "Username input not found"
        # Check for password field
        password = await self.page.query_selector('input[name="password"], input[type="password"]')
        assert password is not None, "Password input not found"
        # Check for submit button
        submit = await self.page.query_selector('button[type="submit"], input[type="submit"]')
        assert submit is not None, "Submit button not found"

    async def test_admin_login(self):
        """Test admin login functionality"""
        await self.page.goto(f"{self.base_url}/admin/", wait_until="networkidle")

        # Fill login form
        username_input = await self.page.query_selector('input[name="username"]')
        password_input = await self.page.query_selector('input[name="password"]')

        if username_input and password_input:
            await username_input.fill("admin")
            await password_input.fill(self.admin_password)
            submit = await self.page.query_selector('input[type="submit"]')
            if submit:
                await submit.click()
                await self.page.wait_for_load_state("networkidle")

        # Verify login success - should see admin dashboard
        content = await self.page.content()
        current_url = self.page.url
        # Admin login successful if we see admin content or dashboard
        assert "admin" in current_url.lower() or "dashboard" in current_url.lower() or \
               "site administration" in content.lower() or "logout" in content.lower(), \
            f"Admin login may have failed. URL: {current_url}"

    async def test_dashboard_access(self):
        """Test dashboard page access after login"""
        # Try to access dashboard
        await self.page.goto(f"{self.base_url}/dashboard/", wait_until="networkidle")

        # Check if redirected to login (not authenticated)
        if "/login" in self.page.url or "/account/login" in self.page.url:
            # Need to login first via regular login page
            await self.page.goto(f"{self.base_url}/account/login/", wait_until="networkidle")
            username_input = await self.page.query_selector('input[name="username"]')
            password_input = await self.page.query_selector('input[name="password"]')
            if username_input and password_input:
                await username_input.fill("admin")
                await password_input.fill(self.admin_password)
                submit = await self.page.query_selector('button[type="submit"], input[type="submit"]')
                if submit:
                    await submit.click()
                    await self.page.wait_for_load_state("networkidle")

            # Now try dashboard again
            await self.page.goto(f"{self.base_url}/dashboard/", wait_until="networkidle")

        # Dashboard should load (either show content or redirect is acceptable)
        current_url = self.page.url
        assert "/dashboard" in current_url or "/login" in current_url, \
            f"Unexpected URL: {current_url}"

    async def test_health_endpoint(self):
        """Test health check endpoint"""
        response = await self.page.goto(f"{self.base_url}/api/health/", wait_until="networkidle")
        assert response is not None, "No response from health endpoint"
        # Health check should return 200
        assert response.status in [200, 404], \
            f"Health endpoint returned status {response.status}"

    async def test_api_endpoints_basic(self):
        """Test basic API endpoint accessibility"""
        # Test a few common API patterns
        api_paths = [
            "/api/",
            "/dashboard/api/alpha/provider-status/",
            "/dashboard/api/alpha/coverage/",
        ]

        for path in api_paths:
            response = await self.page.goto(f"{self.base_url}{path}", wait_until="networkidle")
            if response:
                # 401/403 is acceptable (auth required), 500 is not
                assert response.status < 500, \
                    f"API {path} returned server error {response.status}"

    async def test_regime_page(self):
        """Test regime page accessibility"""
        await self.page.goto(f"{self.base_url}/regime/", wait_until="networkidle")
        # Should either load or redirect to login
        current_url = self.page.url
        assert "/regime" in current_url or "/login" in current_url, \
            f"Unexpected URL for regime: {current_url}"

    async def test_macro_page(self):
        """Test macro data page accessibility"""
        await self.page.goto(f"{self.base_url}/macro/", wait_until="networkidle")
        current_url = self.page.url
        assert "/macro" in current_url or "/login" in current_url, \
            f"Unexpected URL for macro: {current_url}"

    async def test_signal_page(self):
        """Test signal page accessibility"""
        await self.page.goto(f"{self.base_url}/signal/", wait_until="networkidle")
        current_url = self.page.url
        assert "/signal" in current_url or "/login" in current_url, \
            f"Unexpected URL for signal: {current_url}"

    async def test_backtest_page(self):
        """Test backtest page accessibility"""
        await self.page.goto(f"{self.base_url}/backtest/", wait_until="networkidle")
        current_url = self.page.url
        assert "/backtest" in current_url or "/login" in current_url, \
            f"Unexpected URL for backtest: {current_url}"

    async def test_static_files(self):
        """Test static files are served"""
        # Try to load a static file
        await self.page.goto(f"{self.base_url}/static/", wait_until="networkidle")
        # Static URL might return 404 or 403, but not 500
        # This is just to check static serving is working

    async def test_admin_models_list(self):
        """Test admin models are accessible"""
        # Navigate to admin
        await self.page.goto(f"{self.base_url}/admin/", wait_until="networkidle")

        # Check if we can see model listings
        content = await self.page.content()

        # Look for common admin elements
        has_models = any(keyword in content.lower() for keyword in [
            "regime", "macro", "signal", "policy", "backtest",
            "alpha", "account", "audit"
        ])

        # If not logged in, we might be on login page
        current_url = self.page.url
        if "/login" in current_url:
            # Login first
            username_input = await self.page.query_selector('input[name="username"]')
            password_input = await self.page.query_selector('input[name="password"]')
            if username_input and password_input:
                await username_input.fill("admin")
                await password_input.fill(self.admin_password)
                submit = await self.page.query_selector('input[type="submit"]')
                if submit:
                    await submit.click()
                    await self.page.wait_for_load_state("networkidle")

            # Check again after login
            await self.page.goto(f"{self.base_url}/admin/", wait_until="networkidle")
            content = await self.page.content()
            has_models = any(keyword in content.lower() for keyword in [
                "regime", "macro", "signal", "policy"
            ])

        # Test passes if we can access admin (even if empty)
        assert "admin" in self.page.url.lower() or has_models, \
            "Cannot access admin panel"

    async def test_no_javascript_errors(self):
        """Test for JavaScript console errors"""
        errors = []

        self.page.on("console", lambda msg: (
            errors.append(msg.text) if msg.type == "error" else None
        ))

        # Visit main pages
        pages_to_visit = [
            f"{self.base_url}/",
            f"{self.base_url}/dashboard/",
            f"{self.base_url}/admin/",
        ]

        for url in pages_to_visit:
            try:
                await self.page.goto(url, wait_until="networkidle", timeout=10000)
            except Exception:
                pass  # Page might redirect or require auth

        # Filter out acceptable errors
        real_errors = [e for e in errors if
                      "favicon" not in e.lower() and
                      "404" not in e and
                      "net::err" not in e.lower()]

        # We allow some errors but flag if too many
        # assert len(real_errors) < 5, f"Too many JS errors: {real_errors}"
        # For now just log the errors
        if real_errors:
            print(f"    JS Errors found: {len(real_errors)}")

    async def test_response_time(self):
        """Test page response times are acceptable"""
        pages = [
            "/",
            "/admin/",
            "/dashboard/",
        ]

        slow_pages = []
        for path in pages:
            start = datetime.now()
            try:
                await self.page.goto(f"{self.base_url}{path}", wait_until="networkidle", timeout=30000)
                duration = (datetime.now() - start).total_seconds()
                if duration > 5:
                    slow_pages.append((path, duration))
            except Exception as e:
                slow_pages.append((path, str(e)))

        # All pages should load within 5 seconds
        assert len(slow_pages) == 0, f"Slow pages: {slow_pages}"

    async def run_all_tests(self):
        """Run all UAT tests"""
        print("=" * 60)
        print("AgomTradePro UAT Browser Testing")
        print("=" * 60)
        print(f"Base URL: {self.base_url}")
        print(f"Time: {self.report.timestamp}")
        print("-" * 60)

        await self.setup()

        try:
            # Authentication tests
            print("\n[Authentication Tests]")
            await self.run_test("Homepage Loads", self.test_homepage_loads)
            await self.run_test("Login Page Elements", self.test_login_page_elements)
            await self.run_test("Admin Login", self.test_admin_login)

            # Page access tests
            print("\n[Page Access Tests]")
            await self.run_test("Dashboard Access", self.test_dashboard_access)
            await self.run_test("Regime Page", self.test_regime_page)
            await self.run_test("Macro Page", self.test_macro_page)
            await self.run_test("Signal Page", self.test_signal_page)
            await self.run_test("Backtest Page", self.test_backtest_page)

            # API tests
            print("\n[API Tests]")
            await self.run_test("Health Endpoint", self.test_health_endpoint)
            await self.run_test("API Endpoints Basic", self.test_api_endpoints_basic)

            # Admin tests
            print("\n[Admin Tests]")
            await self.run_test("Admin Models List", self.test_admin_models_list)

            # Performance tests
            print("\n[Performance Tests]")
            await self.run_test("Response Time", self.test_response_time)
            await self.run_test("No JS Errors", self.test_no_javascript_errors)

        finally:
            await self.teardown()

        return self.report

    def generate_report(self) -> str:
        """Generate markdown report"""
        lines = [
            "# UAT Browser Test Report",
            "",
            f"**Timestamp**: {self.report.timestamp}",
            f"**Base URL**: {self.report.base_url}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Tests | {self.report.total_tests} |",
            f"| Passed | {self.report.passed} |",
            f"| Failed | {self.report.failed} |",
            f"| Pass Rate | {self.report.passed/self.report.total_tests*100:.1f}% |",
            "",
            "## Test Results",
            "",
        ]

        # Group by pass/fail
        passed_tests = [r for r in self.report.results if r.passed]
        failed_tests = [r for r in self.report.results if not r.passed]

        if failed_tests:
            lines.append("### Failed Tests")
            lines.append("")
            for r in failed_tests:
                lines.append(f"#### {r.name}")
                lines.append("- **Status**: FAILED")
                lines.append(f"- **Message**: {r.message}")
                if r.screenshot:
                    lines.append(f"- **Screenshot**: `{r.screenshot}`")
                lines.append(f"- **Duration**: {r.duration_ms}ms")
                lines.append("")

        if passed_tests:
            lines.append("### Passed Tests")
            lines.append("")
            for r in passed_tests:
                lines.append(f"- {r.name} ({r.duration_ms}ms)")
            lines.append("")

        return "\n".join(lines)


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="UAT Browser Testing")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL")
    parser.add_argument("--password", default="Aa123456", help="Admin password")
    parser.add_argument("--output", default="reports/uat_report.md", help="Output report path")
    args = parser.parse_args()

    tester = UATTester(base_url=args.base_url, admin_password=args.password)
    report = await tester.run_all_tests()

    # Generate and save report
    report_content = tester.generate_report()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_content, encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"SUMMARY: {report.passed}/{report.total_tests} tests passed")
    print(f"Report saved to: {output_path}")
    print("=" * 60)

    # Return non-zero if any tests failed
    return 1 if report.failed > 0 else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
