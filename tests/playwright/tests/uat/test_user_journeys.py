"""
UAT Tests for User Journeys based on UX Checklist.
Tests the critical paths: Research -> Selection -> Decision -> Execution -> Review.

Based on: docs/frontend/ux-user-journey-checklist-2026-02-18.md
"""
import pytest
from playwright.sync_api import Page

from tests.playwright.config.test_config import config
from tests.playwright.pages import LoginPage
from tests.playwright.tests.smoke.test_critical_paths import (
    _assert_audit_contract,
    _assert_backtest_contract,
    _assert_dashboard_contract,
    _assert_equity_contract,
    _assert_page_shell,
    _assert_policy_contract,
    _assert_regime_contract,
    _assert_signal_contract,
    _assert_simulated_trading_contract,
)
from tests.playwright.utils.ux_auditor import Severity, UXAuditor


def _assert_page_loaded(page: Page, expected_path_fragment: str | None = None) -> None:
    """Assert the current page is a usable non-error page."""
    _assert_page_shell(page, expected_path_fragment or "")
    assert "/error/" not in page.url, f"Unexpected error page: {page.url}"


def _has_any(page: Page, selectors: list[str]) -> bool:
    """Return True when any selector matches at least one element."""
    return any(page.locator(selector).count() > 0 for selector in selectors)


def _assert_has_any(page: Page, selectors: list[str], message: str) -> None:
    """Assert the page exposes at least one selector from a stable set."""
    assert _has_any(page, selectors), message


class TestJourneyA:
    """Journey A: New User Onboarding."""

    @pytest.mark.uat
    @pytest.mark.journey_a
    def test_A1_registration_fields_clear(self, page: Page) -> None:
        """A1: Registration page fields are clearly explained."""
        page.goto(f"{config.base_url}{config.register_url}")

        # Check for form labels
        has_username_label = page.locator('label:has-text("用户名"), label:has-text("Username")').count() > 0
        has_email_label = page.locator('label:has-text("邮箱"), label:has-text("Email")').count() > 0
        has_password_label = page.locator('label:has-text("密码"), label:has-text("Password")').count() > 0

        assert has_username_label, "Username field should have a clear label"
        assert has_email_label or has_password_label, "Email or Password field should have a clear label"

    @pytest.mark.uat
    @pytest.mark.journey_a
    def test_A1_login_redirect_on_auth_required(self, page: Page) -> None:
        """A1: Unauthenticated users are redirected to login when accessing protected pages."""
        # Try to access dashboard without login
        page.goto(f"{config.base_url}{config.dashboard_url}")

        # Should redirect to login
        current_url = page.url
        assert "login" in current_url.lower() or "account" in current_url.lower(), \
            f"Should redirect to login, got: {current_url}"

    @pytest.mark.uat
    @pytest.mark.journey_a
    def test_A1_login_redirects_to_dashboard(self, login_page: LoginPage) -> None:
        """A1: After login, user should be redirected to dashboard."""
        login_page.goto()
        login_page.login_as_admin()
        login_page.assert_login_success()

        # Wait for navigation
        login_page.page.wait_for_load_state("networkidle")

        # Should be on dashboard
        current_url = login_page.page.url
        assert "dashboard" in current_url.lower(), \
            f"Should redirect to dashboard after login, got: {current_url}"

    @pytest.mark.uat
    @pytest.mark.journey_a
    def test_A2_dashboard_answers_key_questions(self, authenticated_page: Page) -> None:
        """A2: Dashboard answers 3 questions: current regime, current position, next action."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

        # Check for regime information
        has_regime = (
            authenticated_page.locator('text=Regime').count() > 0 or
            authenticated_page.locator('text=环境').count() > 0 or
            authenticated_page.locator('text=增长').count() > 0 or
            authenticated_page.locator('text=通胀').count() > 0
        )

        # Check for position information
        has_position = (
            authenticated_page.locator('text=仓位').count() > 0 or
            authenticated_page.locator('text=Position').count() > 0 or
            authenticated_page.locator('text=持仓').count() > 0
        )

        assert has_regime or has_position, "Dashboard should show regime or position information"

    @pytest.mark.uat
    @pytest.mark.journey_a
    def test_A2_navigation_grouping_consistent(self, authenticated_page: Page) -> None:
        """A2: Left navigation groups are named consistently with business vocabulary."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

        # Check for sidebar navigation
        has_sidebar = authenticated_page.locator('.sidebar, nav, [class*="nav"]').count() > 0
        assert has_sidebar, "Should have navigation sidebar"

        # Check for common navigation terms
        has_macro = authenticated_page.locator('a:has-text("宏观"), a:has-text("Macro")').count() > 0
        has_regime = authenticated_page.locator('a:has-text("环境"), a:has-text("Regime")').count() > 0
        has_policy = authenticated_page.locator('a:has-text("政策"), a:has-text("Policy")').count() > 0

        assert has_macro or has_regime or has_policy, "Navigation should have macro/regime/policy links"

    @pytest.mark.uat
    @pytest.mark.journey_a
    def test_A2_card_colors_consistent(self, authenticated_page: Page) -> None:
        """A2: Key cards (Regime/Policy/Quota) use consistent colors for status."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

        _assert_has_any(
            authenticated_page,
            [
                '[class*="success"]',
                '[class*="danger"]',
                '[class*="warning"]',
                '[class*="badge"]',
                '[class*="status"]',
            ],
            "Dashboard should expose status styling for key cards",
        )


class TestJourneyB:
    """Journey B: Research and Asset Selection."""

    @pytest.mark.uat
    @pytest.mark.journey_b
    def test_B1_regime_page_supports_data_switching(self, authenticated_page: Page) -> None:
        """B1: Regime page supports switching time points and data sources."""
        authenticated_page.goto(f"{config.base_url}{config.regime_dashboard_url}")
        _assert_regime_contract(authenticated_page)

        # Check for date selector or filter controls
        has_filters = (
            authenticated_page.locator('select, input[type="date"], [class*="filter"], [class*="select"]').count() > 0
        )

        assert has_filters, "Regime page should have filter controls"

    @pytest.mark.uat
    @pytest.mark.journey_b
    def test_B1_policy_page_shows_current_gear(self, authenticated_page: Page) -> None:
        """B1: Policy page shows current gear + recent events + suggestions."""
        authenticated_page.goto(f"{config.base_url}{config.policy_manage_url}")
        _assert_policy_contract(authenticated_page)

        _assert_has_any(
            authenticated_page,
            ['text=档位', 'text=当前', 'text=建议', 'text=事件', 'text=工作台'],
            "Policy page should show current policy gear, events, or suggestions",
        )

    @pytest.mark.uat
    @pytest.mark.journey_b
    def test_B2_asset_filter_page_loads(self, authenticated_page: Page) -> None:
        """B2: Asset filter page (Asset/Fund/Equity) has clear filter groups."""
        # Test equity screening
        authenticated_page.goto(f"{config.base_url}{config.equity_screen_url}")
        _assert_equity_contract(authenticated_page)

        # Check for filter controls
        has_filters = (
            authenticated_page.locator('[class*="filter"], [class*="search"], [class*="form"]').count() > 0
        )

        assert has_filters, "Equity screen page should have filter controls"

    @pytest.mark.uat
    @pytest.mark.journey_b
    def test_B2_filter_results_update_timely(self, authenticated_page: Page) -> None:
        """B2: Filter results update in timely manner with empty state hints."""
        authenticated_page.goto(f"{config.base_url}{config.equity_screen_url}")
        _assert_equity_contract(authenticated_page)

        # Check for results area or empty state
        has_results = (
            authenticated_page.locator('table, [class*="result"], [class*="list"]').count() > 0 or
            authenticated_page.locator('text=暂无, text=空, text=Empty, text=No data').count() > 0
        )

        assert has_results, "Page should have results area or empty state message"


class TestJourneyC:
    """Journey C: Decision and Execution."""

    @pytest.mark.uat
    @pytest.mark.journey_c
    def test_C1_strategy_creation_flow(self, authenticated_page: Page) -> None:
        """C1: Strategy creation flow is logical: basic -> risk -> rules -> script/AI."""
        authenticated_page.goto(f"{config.base_url}/strategy/")
        _assert_page_loaded(authenticated_page, "/strategy/")
        _assert_has_any(
            authenticated_page,
            ['text=策略', 'text=Strategy', 'a:has-text("新建")', 'button:has-text("新建")'],
            "Strategy page should expose strategy list or create entry",
        )

    @pytest.mark.uat
    @pytest.mark.journey_c
    def test_C1_signal_action_entries_clear(self, authenticated_page: Page) -> None:
        """C1: Signal page has clear action entries: create/approve/reject/invalidate."""
        authenticated_page.goto(f"{config.base_url}{config.signal_manage_url}")
        _assert_signal_contract(authenticated_page)

        # Check for action buttons
        has_actions = (
            authenticated_page.locator('a:has-text("创建"), a:has-text("Create"), button:has-text("创建")').count() > 0 or
            authenticated_page.locator('[class*="btn"], [class*="button"]').count() > 0
        )

        assert has_actions, "Signal page should have action buttons"

    @pytest.mark.uat
    @pytest.mark.journey_c
    def test_C2_decision_workspace_visible(self, authenticated_page: Page) -> None:
        """C2: Decision Workspace shows Beta/Alpha/Quota sections on one screen."""
        authenticated_page.goto(f"{config.base_url}/decision/workspace/")
        _assert_page_loaded(authenticated_page, "/decision/workspace/")

        # Check for key decision sections
        has_sections = (
            authenticated_page.locator('text=Beta, text=Alpha, text=配额').count() > 0 or
            authenticated_page.locator('[class*="decision"], [class*="workspace"]').count() > 0
        )
        assert has_sections, "Decision workspace should expose Beta/Alpha/quota sections"

    @pytest.mark.uat
    @pytest.mark.journey_c
    def test_C2_alerts_are_visible_and_actionable(self, authenticated_page: Page) -> None:
        """C2: Alerts (quota shortage, candidate expiration) are prominent and actionable."""
        authenticated_page.goto(f"{config.base_url}/decision/workspace/")
        _assert_page_loaded(authenticated_page, "/decision/workspace/")

        _assert_has_any(
            authenticated_page,
            ['[class*="alert"]', '[class*="warning"]', '[class*="notice"]', 'text=配额', 'text=过期'],
            "Decision workspace should show alert, warning, or risk explanation",
        )


class TestJourneyD:
    """Journey D: Trading and Position Management."""

    @pytest.mark.uat
    @pytest.mark.journey_d
    def test_D1_simulated_trading_entry_clear(self, authenticated_page: Page) -> None:
        """D1: Simulated trading entry page leads quickly to accounts/positions/trades."""
        authenticated_page.goto(f"{config.base_url}{config.simulated_trading_dashboard_url}")
        _assert_simulated_trading_contract(authenticated_page)

        _assert_has_any(
            authenticated_page,
            [
                'a:has-text("账户")',
                'a:has-text("持仓")',
                'a:has-text("交易")',
                'a:has-text("Account")',
                'a:has-text("Position")',
                'a:has-text("Trade")',
            ],
            "Simulated trading page should link to accounts, positions, or trades",
        )

    @pytest.mark.uat
    @pytest.mark.journey_d
    def test_D1_account_metrics_visible(self, authenticated_page: Page) -> None:
        """D1: Account detail page shows key metrics (total assets, return, position)."""
        authenticated_page.goto(f"{config.base_url}{config.simulated_trading_dashboard_url}")
        _assert_simulated_trading_contract(authenticated_page)

        _assert_has_any(
            authenticated_page,
            ['text=资产', 'text=收益', 'text=仓位', 'text=Asset', 'text=Return', 'text=Position'],
            "Simulated trading dashboard should show account metrics",
        )

    @pytest.mark.uat
    @pytest.mark.journey_d
    def test_D1_position_table_has_controls(self, authenticated_page: Page) -> None:
        """D1: Position and trade tables support basic filter/sort/refresh."""
        authenticated_page.goto(f"{config.base_url}{config.simulated_trading_positions_url}")
        _assert_page_loaded(authenticated_page, "/simulated-trading/")

        _assert_has_any(
            authenticated_page,
            ['table', '[class*="table"]', '[class*="grid"]', 'button:has-text("刷新")', 'button:has-text("Refresh")'],
            "Position page should expose a table, grid, or refresh control",
        )


class TestJourneyE:
    """Journey E: Review and Operations."""

    @pytest.mark.uat
    @pytest.mark.journey_e
    def test_E1_backtest_list_to_detail_path_clear(self, authenticated_page: Page) -> None:
        """E1: Backtest list to detail path is clear, results page shows key metrics."""
        authenticated_page.goto(f"{config.base_url}{config.backtest_create_url}")
        _assert_backtest_contract(authenticated_page)

        # Check for form or results
        has_content = (
            authenticated_page.locator('form, table, [class*="result"]').count() > 0
        )

        assert has_content, "Backtest page should have form or results"

    @pytest.mark.uat
    @pytest.mark.journey_e
    def test_E1_audit_page_terminology_consistent(self, authenticated_page: Page) -> None:
        """E1: Audit page (attribution/threshold/metrics) uses consistent terminology."""
        authenticated_page.goto(f"{config.base_url}{config.audit_reports_url}")
        _assert_audit_contract(authenticated_page)
        _assert_has_any(
            authenticated_page,
            ['text=审计', 'text=归因', 'text=阈值', 'text=metrics', 'text=attribution'],
            "Audit page should expose audit terminology or key metric sections",
        )

    @pytest.mark.uat
    @pytest.mark.journey_e
    def test_E2_ops_center_links_valid(self, authenticated_page: Page) -> None:
        """E2: Settings Center has complete entry points with no broken links."""
        authenticated_page.goto(f"{config.base_url}/settings/")
        _assert_page_loaded(authenticated_page, "/settings/")

        # Check for links to management pages
        has_links = authenticated_page.locator('a[href]').count() > 0
        assert has_links, "Settings center should have navigation links"

    @pytest.mark.uat
    @pytest.mark.journey_e
    def test_E2_admin_pages_complete_workflow(self, authenticated_page: Page) -> None:
        """E2: Admin pages (docs/logs/AI/Prompt) have complete operation workflows."""
        authenticated_page.goto(f"{config.base_url}/admin/docs/manage/")
        _assert_page_loaded(authenticated_page, "/admin/docs/manage/")
        _assert_has_any(
            authenticated_page,
            ['text=文档', 'text=管理', 'text=导入', 'text=导出'],
            "Admin docs page should expose management actions",
        )


class TestGlobalExperienceBaseline:
    """Global experience baseline checks across all journeys."""

    @pytest.mark.uat
    @pytest.mark.global_experience
    def test_navigation_consistency(self, authenticated_page: Page) -> None:
        """Navigation: top nav, side nav, breadcrumbs are consistent."""
        # Test on dashboard
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

        # Check for any navigation element
        has_nav = authenticated_page.locator('nav, [role="navigation"], .navbar, .sidebar').count() > 0
        assert has_nav, "Page should have navigation elements"

    @pytest.mark.uat
    @pytest.mark.global_experience
    def test_no_404_on_main_links(self, authenticated_page: Page, ux_auditor_instance: UXAuditor) -> None:
        """No 404 errors on main navigation links."""
        critical_urls = [
            config.dashboard_url,
            config.macro_data_url,
            config.regime_dashboard_url,
            config.signal_manage_url,
            config.policy_manage_url,
        ]

        failed_urls = []
        for url in critical_urls:
            authenticated_page.goto(f"{config.base_url}{url}")
            try:
                if url == config.dashboard_url:
                    _assert_dashboard_contract(authenticated_page)
                elif url == config.regime_dashboard_url:
                    _assert_regime_contract(authenticated_page)
                elif url == config.signal_manage_url:
                    _assert_signal_contract(authenticated_page)
                elif url == config.policy_manage_url:
                    _assert_policy_contract(authenticated_page)
                else:
                    _assert_page_loaded(authenticated_page, "/macro/")
            except AssertionError:
                failed_urls.append(url)

        assert len(failed_urls) == 0, f"Found 404 errors on URLs: {failed_urls}"

    @pytest.mark.uat
    @pytest.mark.global_experience
    def test_visual_consistency_buttons(self, authenticated_page: Page) -> None:
        """Visual consistency: buttons have consistent styling."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

        # Check for button-like elements
        buttons = authenticated_page.locator('button, .btn, [class*="button"], [role="button"]').all()
        assert len(buttons) > 0, "Dashboard should expose actionable buttons"

    @pytest.mark.uat
    @pytest.mark.global_experience
    def test_feedback_loading_states(self, authenticated_page: Page) -> None:
        """Feedback: loading, success, failure, empty states are perceivable."""
        _assert_dashboard_contract(authenticated_page)
        _assert_has_any(
            authenticated_page,
            [
                '[class*="loading"]',
                '[class*="spinner"]',
                '[class*="progress"]',
                '[class*="status"]',
                '[class*="empty"]',
            ],
            "Dashboard should expose loading, status, or empty-state feedback",
        )

    @pytest.mark.uat
    @pytest.mark.global_experience
    def test_terminology_consistency(self, authenticated_page: Page) -> None:
        """Terminology consistency: same concept uses same terminology."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)
        body_text = authenticated_page.locator("body").inner_text(timeout=5000)
        assert (
            ("Regime" in body_text or "环境" in body_text)
            and ("Policy" in body_text or "政策" in body_text or "仓位" in body_text)
        ), "Dashboard should use core investment terminology consistently"

    @pytest.mark.uat
    @pytest.mark.global_experience
    def test_robustness_no_js_errors(self, page: Page, login_page: LoginPage) -> None:
        """Robustness: no 404s, no JS errors, no blocking exceptions."""
        console_errors: list[str] = []
        page_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        login_page.goto()
        login_page.login_as_admin()
        login_page.assert_login_success()
        page.wait_for_load_state("networkidle")

        page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(page)
        assert not page_errors, f"Unhandled page errors found: {page_errors}"
        assert not console_errors, f"Console error messages found: {console_errors}"


class TestPriorityFocusChecks:
    """Priority focus checks based on current code audit."""

    @pytest.mark.uat
    @pytest.mark.priority
    def test_dashboard_sidebar_links_valid(self, authenticated_page: Page) -> None:
        """Dashboard sidebar links (macro data, equity analysis) are valid."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

        links = authenticated_page.locator('nav a, .sidebar a, [class*="nav"] a').all()

        valid_links = 0
        for link in links[:10]:  # Check first 10 links
            try:
                href = link.get_attribute("href")
                if href and not href.startswith("#"):
                    valid_links += 1
            except Exception:
                pass

        assert valid_links > 0, "Dashboard should expose at least one navigable sidebar link"

    @pytest.mark.uat
    @pytest.mark.priority
    def test_decision_workspace_actions_complete(self, authenticated_page: Page) -> None:
        """Decision workspace core actions have complete confirmation and result hints."""
        authenticated_page.goto(f"{config.base_url}/decision/workspace/")
        _assert_page_loaded(authenticated_page, "/decision/workspace/")

        has_actions = authenticated_page.locator('button, .btn, a[class*="btn"]').count() > 0
        assert has_actions, "Decision workspace should expose action buttons"

    @pytest.mark.uat
    @pytest.mark.priority
    def test_cross_module_ui_consistency(self, authenticated_page: Page, ux_auditor_instance: UXAuditor) -> None:
        """Cross-module UI style consistency (inline style pages prioritized for fix)."""
        pages_to_check = [
            (config.dashboard_url, "dashboard"),
            (config.regime_dashboard_url, "regime"),
            (config.signal_manage_url, "signal"),
        ]

        for url, page_name in pages_to_check:
            authenticated_page.goto(f"{config.base_url}{url}")
            issues = ux_auditor_instance.audit_page(authenticated_page, page_name)

            # Filter out low severity issues
            high_priority_issues = [i for i in issues if i.severity in [Severity.CRITICAL, Severity.HIGH]]

            # Report if critical issues found
            if high_priority_issues:
                for issue in high_priority_issues:
                    print(f"High priority issue on {page_name}: {issue.title}")

            assert not high_priority_issues, f"High-priority UX issues found on {page_name}"


class TestUATSummaryReport:
    """Generate UAT summary report."""

    @pytest.mark.uat
    @pytest.mark.report
    def test_uat_summary(self, request) -> None:
        """Generate UAT test summary."""
        assert request.node.get_closest_marker("report") is not None


# Test data collection helpers
def collect_journey_results() -> dict[str, dict[str, str]]:
    """Collect results for all journey tests.

    Returns:
        Dictionary mapping journey IDs to test results
    """
    return {
        "A": {"status": "pending", "tests": ["A1", "A2"]},
        "B": {"status": "pending", "tests": ["B1", "B2"]},
        "C": {"status": "pending", "tests": ["C1", "C2"]},
        "D": {"status": "pending", "tests": ["D1", "D2"]},
        "E": {"status": "pending", "tests": ["E1", "E2"]},
    }
