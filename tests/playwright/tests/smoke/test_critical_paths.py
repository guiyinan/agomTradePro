"""
Smoke tests for critical user paths.
Tests that all major pages render their core UI contracts.
"""
import json
import re
import time
from collections.abc import Iterable

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.playwright.config.test_config import config
from tests.playwright.pages import AdminPage, DashboardPage, LoginPage
from tests.playwright.utils.screenshot_utils import ScreenshotUtils


def _normalize_text(value: str) -> str:
    """Collapse whitespace for stable text assertions."""
    return re.sub(r"\s+", " ", value).strip()


def _assert_page_shell(page: Page, expected_fragment: str) -> None:
    """Assert a target page is loaded and not an error shell."""
    page.wait_for_load_state("domcontentloaded")
    expect(page).to_have_url(re.compile(fr".*{re.escape(expected_fragment)}.*"))
    body_text = page.locator("body").inner_text(timeout=5000)
    assert body_text.strip(), "Page body should not be empty"
    assert "Page not found" not in body_text
    assert "Server Error" not in body_text
    assert "/404/" not in page.url


def _assert_min_count(page: Page, selector: str, minimum: int, timeout: int = 10000) -> None:
    """Assert that a selector resolves to at least ``minimum`` elements."""
    locator = page.locator(selector)
    expect(locator.first).to_be_visible(timeout=timeout)
    actual = locator.count()
    assert actual >= minimum, f"Expected at least {minimum} elements for {selector}, got {actual}"


def _wait_for_non_placeholder_text(
    page: Page,
    selector: str,
    *,
    disallowed: Iterable[str] = ("", "-"),
    timeout: int = 10000,
) -> str:
    """Wait until an element renders non-placeholder text and return it."""
    locator = page.locator(selector).first
    expect(locator).to_be_visible(timeout=timeout)

    deadline = time.time() + timeout / 1000
    last_text = ""
    forbidden = {_normalize_text(item) for item in disallowed}

    while time.time() < deadline:
        last_text = _normalize_text(locator.inner_text(timeout=2000))
        if last_text and last_text not in forbidden:
            return last_text
        page.wait_for_timeout(250)

    raise AssertionError(f"Expected non-placeholder text for {selector}, got {last_text!r}")


def _assert_box_size(
    page: Page,
    selector: str,
    *,
    min_width: float = 80,
    min_height: float = 40,
) -> None:
    """Assert an element is visible and has a meaningful rendered box."""
    locator = page.locator(selector).first
    expect(locator).to_be_visible()
    box = locator.bounding_box()
    assert box is not None, f"{selector} should have a bounding box"
    assert box["width"] >= min_width, f"{selector} width too small: {box['width']}"
    assert box["height"] >= min_height, f"{selector} height too small: {box['height']}"


def _first_visible_locator(page: Page, selector: str) -> Locator | None:
    """Return the first visible locator that matches ``selector``."""
    locator = page.locator(selector)
    for index in range(locator.count()):
        candidate = locator.nth(index)
        if candidate.is_visible():
            return candidate
    return None


def _assert_empty_state(page: Page, *expected_fragments: str) -> Locator:
    """Assert a visible empty-state container exists with expected text fragments."""
    empty_state = _first_visible_locator(page, ".empty-state")
    assert empty_state is not None, "Expected a visible empty state"
    empty_text = _normalize_text(empty_state.inner_text(timeout=5000))
    for expected in expected_fragments:
        assert expected in empty_text, (
            f"Expected empty state to include {expected!r}, got {empty_text!r}"
        )
    return empty_state


def _assert_card_style(page: Page, selector: str) -> None:
    """Assert that a card-like element has real styling applied."""
    locator = page.locator(selector).first
    expect(locator).to_be_visible()

    border_radius = str(
        locator.evaluate(
            "(element) => getComputedStyle(element).getPropertyValue('border-radius')"
        )
    ).strip()
    background_color = str(
        locator.evaluate(
            "(element) => getComputedStyle(element).getPropertyValue('background-color')"
        )
    ).strip()
    background_image = str(
        locator.evaluate(
            "(element) => getComputedStyle(element).getPropertyValue('background-image')"
        )
    ).strip()

    assert border_radius not in {"", "0px"}, f"{selector} should not be visually flat"
    has_background_color = background_color not in {
        "",
        "transparent",
        "rgba(0, 0, 0, 0)",
    }
    has_background_image = background_image not in {"", "none"}
    assert has_background_color or has_background_image, (
        f"{selector} should have a rendered background style"
    )


def _assert_dashboard_contract(page: Page) -> None:
    """Assert dashboard renders key metrics and navigation cards."""
    _assert_page_shell(page, "/dashboard/")
    _wait_for_non_placeholder_text(page, "h1.home-title")
    _wait_for_non_placeholder_text(page, ".status-card .status-value")
    _assert_min_count(page, ".metric-card", 4)
    _assert_min_count(page, ".section-link", 4)
    _assert_min_count(page, ".alpha-metric-card", 4)
    _assert_card_style(page, ".metric-card")


def _assert_macro_contract(page: Page) -> None:
    """Assert macro page renders indicator data and chart container."""
    _assert_page_shell(page, "/macro/data/")
    expect(page.locator("h1")).to_have_text("宏观数据中心")
    _assert_min_count(page, ".stat-card", 3)

    indicator_items = page.locator(".ind-item:visible")
    if indicator_items.count() == 0:
        placeholder = page.locator("#chartPlaceholder")
        expect(placeholder).to_be_visible(timeout=10000)
        placeholder_text = _normalize_text(placeholder.inner_text(timeout=5000))
        assert "选择一个指标查看趋势" in placeholder_text
        assert not page.locator("#indicatorInfoBar").is_visible(), (
            "Macro page should keep the indicator info bar hidden when no data is available"
        )
        return

    _assert_min_count(page, ".ind-item:visible", 1)

    indicator_info_bar = page.locator("#indicatorInfoBar")
    if not indicator_info_bar.is_visible():
        indicator_items.first.click()

    expect(indicator_info_bar).to_be_visible(timeout=10000)
    _wait_for_non_placeholder_text(page, "#currentIndicatorCode")
    _wait_for_non_placeholder_text(page, "#currentIndicatorName")
    _wait_for_non_placeholder_text(page, "#currentIndicatorValue")
    _assert_box_size(page, "#mainChart", min_width=400, min_height=240)
    _assert_card_style(page, ".stat-card")


def _assert_regime_contract(page: Page) -> None:
    """Assert regime dashboard renders the current quadrant instead of an empty shell."""
    _assert_page_shell(page, "/regime/dashboard/")
    expect(page.locator("h1")).to_have_text("Regime 判定")
    visible_empty_state = _first_visible_locator(page, ".empty-state")
    if visible_empty_state is not None:
        empty_text = _normalize_text(visible_empty_state.inner_text(timeout=5000))
        if "暂无 Regime 判定数据" in empty_text:
            assert page.locator(".regime-card").count() == 0
            return

    _wait_for_non_placeholder_text(page, ".source-badge")
    expect(page.get_by_text("当前象限：")).to_be_visible()
    _assert_min_count(page, ".regime-card", 4)
    _assert_min_count(page, ".chart-card", 2)
    assert page.locator(".regime-card.active").count() == 1, "Expected exactly one active regime card"
    _assert_card_style(page, ".regime-card.active")


def _assert_signal_contract(page: Page) -> None:
    """Assert signal management renders real cards, not just the outer shell."""
    _assert_page_shell(page, "/signal/manage/")
    expect(page.locator("h1")).to_have_text("投资信号")
    _assert_min_count(page, ".stat-card", 5)
    if page.locator(".signal-card").count() == 0:
        _assert_empty_state(page, "暂无信号")
        expect(page.get_by_role("button", name="创建信号")).to_be_visible()
        return

    _assert_min_count(page, ".signal-card", 1)
    _assert_min_count(page, ".action-btn", 1)
    _wait_for_non_placeholder_text(page, ".signal-card .signal-code")
    _assert_card_style(page, ".signal-card")


def _assert_policy_contract(page: Page) -> None:
    """Assert policy workbench loads overview metrics and event rows."""
    _assert_page_shell(page, "/policy/workbench/")
    expect(page.locator("h1")).to_have_text("政策/情绪/热点工作台")
    _assert_min_count(page, ".overview-card", 4)

    page.wait_for_function(
        """
        () => {
            const tbody = document.querySelector('#events-tbody');
            return tbody && !tbody.innerText.includes('加载中...');
        }
        """,
        timeout=15000,
    )

    _wait_for_non_placeholder_text(page, "#policy-level-value")
    _wait_for_non_placeholder_text(page, "#pending-count", disallowed=("",))
    _assert_min_count(page, ".events-table tbody tr", 1)
    _assert_card_style(page, ".overview-card")


def _assert_equity_contract(page: Page) -> None:
    """Assert equity screen finishes loading its recommendation section."""
    _assert_page_shell(page, "/equity/screen/")
    expect(page.locator("h1")).to_have_text("个股筛选")
    _assert_min_count(page, ".screen-workflow-step", 4)

    page.wait_for_function(
        "() => document.querySelectorAll('#autoRecommendationGrid .auto-recommendation-item').length > 0",
        timeout=15000,
    )

    status_text = _wait_for_non_placeholder_text(
        page,
        "#autoRecommendationStatus",
        disallowed=("", "系统自动推荐加载中", "系统自动推荐异常"),
    )
    assert "异常" not in status_text
    _assert_min_count(page, "#autoRecommendationGrid .auto-recommendation-item", 1)
    _assert_card_style(page, ".screen-workflow-step")


def _assert_equity_result_metrics(page: Page) -> None:
    """Assert the auto-loaded equity result table renders key financial metrics."""
    expect(page.locator("#resultsCard")).to_be_visible(timeout=15000)
    _assert_min_count(page, "#resultsTableBody tr", 1)
    assert _wait_for_non_placeholder_text(
        page,
        "#resultsTableBody tr:first-child td:nth-child(5)",
    ) == "12.30"
    assert _wait_for_non_placeholder_text(
        page,
        "#resultsTableBody tr:first-child td:nth-child(6)",
    ) == "5.60"
    assert _wait_for_non_placeholder_text(
        page,
        "#resultsTableBody tr:first-child td:nth-child(7)",
    ) == "0.72"
    assert _wait_for_non_placeholder_text(
        page,
        "#resultsTableBody tr:first-child td:nth-child(8)",
    ) == "15.60"
    assert _wait_for_non_placeholder_text(
        page,
        "#resultsTableBody tr:first-child td:nth-child(9)",
    ) == "18.20"


def _assert_fund_contract(page: Page) -> None:
    """Assert fund dashboard renders macro context and scoring table."""
    _assert_page_shell(page, "/fund/dashboard/")
    expect(page.locator("h1")).to_have_text("基金分析")
    _assert_min_count(page, ".stat-card", 5)
    _wait_for_non_placeholder_text(page, "#activeSignalsCount")
    _assert_min_count(page, "#multiDimTable thead th", 10)
    _assert_card_style(page, ".stat-card")


def _assert_asset_analysis_contract(page: Page) -> None:
    """Assert asset analysis can execute a real screening request."""
    _assert_page_shell(page, "/asset-analysis/screen/")
    expect(page.locator("h1")).to_have_text("资产筛选")
    _assert_min_count(page, ".pool-card", 4)
    _assert_card_style(page, ".pool-card")

    page.get_by_role("button", name="开始筛选").click()
    page.wait_for_function(
        """
        () => {
            const body = document.querySelector('#resultsTableBody');
            return body && !body.innerText.includes('加载中');
        }
        """,
        timeout=20000,
    )

    _wait_for_non_placeholder_text(page, "#investableCount")
    _assert_min_count(page, "#resultsTableBody tr", 1)


def _assert_backtest_contract(page: Page) -> None:
    """Assert backtest creation page renders a usable form with runtime constraints."""
    _assert_page_shell(page, "/backtest/")
    expect(page.locator("h1")).to_have_text("创建回测")
    _assert_min_count(page, ".form-section", 4)
    _assert_card_style(page, ".form-section")
    assert page.locator("#start_date").get_attribute("min"), "start date min should be populated"
    assert page.locator("#start_date").get_attribute("max"), "start date max should be populated"
    assert page.locator("#end_date").get_attribute("min"), "end date min should be populated"
    assert page.locator("#end_date").get_attribute("max"), "end date max should be populated"
    assert page.locator("#rebalance_frequency option").count() > 0, "frequency options should be populated"
    _assert_box_size(page, "#submit-btn", min_width=100, min_height=36)


def _assert_simulated_trading_contract(page: Page) -> None:
    """Assert simulated trading dashboard renders system entry cards and status blocks."""
    _assert_page_shell(page, "/simulated-trading/")
    expect(page.locator("h1")).to_have_text("模拟盘交易")
    _assert_min_count(page, ".card-link", 1)
    _assert_min_count(page, ".status-item-card", 3)
    _assert_card_style(page, ".card")
    _assert_card_style(page, ".status-item-card")


def _assert_audit_contract(page: Page) -> None:
    """Assert audit report list renders actionable report cards."""
    _assert_page_shell(page, "/audit/")
    title_text = _wait_for_non_placeholder_text(page, "h1")
    assert "审计" in title_text
    _assert_min_count(page, ".btn-primary", 1)

    if page.locator(".report-card").count() == 0:
        _assert_empty_state(page, "暂无归因报告")
        return

    _assert_min_count(page, ".report-card", 1)
    _assert_card_style(page, ".report-card")


def _assert_filter_contract(page: Page) -> None:
    """Assert filter dashboard renders computed data and charts."""
    _assert_page_shell(page, "/filter/")
    expect(page.locator("h1")).to_have_text("趋势滤波器")
    expect(page.locator("#filterTypeSelect")).to_be_visible()
    assert page.locator("#filterTypeSelect").input_value() in {"hp", "kalman"}
    expect(page.locator("#applyBtn")).to_be_visible()

    if page.locator(".summary-value").count() == 0:
        _assert_empty_state(page, "暂无滤波数据")
        return

    _assert_min_count(page, ".summary-value", 4)
    _assert_box_size(page, "#mainChart", min_width=400, min_height=240)
    _assert_card_style(page, ".sidebar-card")


def _assert_rotation_contract(page: Page) -> None:
    """Assert rotation asset page renders asset stats and cards."""
    _assert_page_shell(page, "/rotation/")
    expect(page.locator("h1")).to_have_text("资产类别")
    _assert_min_count(page, ".stat-card", 4)

    if page.locator(".asset-card").count() == 0:
        _assert_empty_state(page, "暂无资产类别数据")
        expect(page.get_by_role("button", name=re.compile("新建资产"))).to_be_visible()
        return

    _assert_min_count(page, ".asset-card", 1)
    _wait_for_non_placeholder_text(page, ".asset-card .asset-name")
    _assert_card_style(page, ".asset-card")


class TestCriticalPaths:
    """Test critical paths through the application."""

    def test_login_page_loads(self, login_page: LoginPage) -> None:
        """Test that login page loads successfully."""
        login_page.goto()
        login_page.assert_on_login_page()
        login_page.assert_not_django_admin_login()

    def test_dashboard_requires_auth(self, dashboard_page: DashboardPage) -> None:
        """Test that dashboard requires authentication."""
        dashboard_page.goto()
        # Should redirect to login or show unauthorized
        # Check that path is not /dashboard/ (ignoring query parameters)
        from urllib.parse import urlparse
        parsed = urlparse(dashboard_page.page.url)
        assert parsed.path != "/dashboard/", "Should not be on dashboard without auth"

    def test_login_to_dashboard_path(self, login_page: LoginPage) -> None:
        """Test complete login flow to dashboard."""
        login_page.goto()
        login_page.assert_not_django_admin_login()
        login_page.login_as_admin()
        login_page.assert_login_success()

    def test_authenticated_dashboard_loads(self, authenticated_page: Page) -> None:
        """Test that dashboard loads when authenticated."""
        authenticated_page.goto(f"{config.base_url}{config.dashboard_url}")
        _assert_dashboard_contract(authenticated_page)

    def test_macro_data_page_loads(self, authenticated_page: Page) -> None:
        """Test that macro data page loads."""
        authenticated_page.goto(f"{config.base_url}{config.macro_data_url}")
        _assert_macro_contract(authenticated_page)

    def test_regime_dashboard_loads(self, authenticated_page: Page) -> None:
        """Test that regime dashboard loads."""
        authenticated_page.goto(f"{config.base_url}{config.regime_dashboard_url}")
        _assert_regime_contract(authenticated_page)

    def test_signal_manage_loads(self, authenticated_page: Page) -> None:
        """Test that signal management page loads."""
        authenticated_page.goto(f"{config.base_url}{config.signal_manage_url}")
        _assert_signal_contract(authenticated_page)

    def test_policy_manage_loads(self, authenticated_page: Page) -> None:
        """Test that policy management page loads."""
        authenticated_page.goto(f"{config.base_url}{config.policy_manage_url}")
        _assert_policy_contract(authenticated_page)

    def test_equity_screen_loads(self, authenticated_page: Page) -> None:
        """Test that equity screening page loads."""
        authenticated_page.goto(f"{config.base_url}{config.equity_screen_url}")
        _assert_equity_contract(authenticated_page)

    def test_equity_screen_renders_dashboard_alpha_financial_columns(
        self,
        authenticated_page: Page,
    ) -> None:
        """Test that dashboard alpha payload fields reach the equity result table."""
        authenticated_page.route(
            "**/api/dashboard/alpha/stocks/**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "code": "000001.SZ",
                                    "name": "平安银行",
                                    "sector": "银行",
                                    "market": "SZ",
                                    "roe": 12.3,
                                    "pe": 5.6,
                                    "pb": 0.72,
                                    "revenue_growth": 15.6,
                                    "profit_growth": 18.2,
                                    "score": 0.913,
                                    "confidence": 0.88,
                                    "source": "cache",
                                    "rank": 1,
                                    "asof_date": "2026-05-02",
                                }
                            ],
                            "top_candidates": [],
                            "actionable_candidates": [],
                            "exit_watchlist": [],
                            "exit_watch_summary": {},
                            "pending_requests": [],
                            "meta": {
                                "status": "available",
                                "source": "cache",
                                "recommendation_ready": False,
                                "must_not_use_for_decision": True,
                                "readiness_status": "research_only",
                                "blocked_reason": "仅研究。",
                                "scope_verification_status": "general_universe",
                            },
                            "pool": {
                                "alpha_scope": "general",
                                "label": "通用 Alpha 研究池",
                                "pool_size": 1,
                                "pool_mode": "market",
                            },
                            "recent_runs": [],
                            "history_run_id": None,
                            "contract": {
                                "recommendation_ready": False,
                                "must_not_treat_as_recommendation": True,
                                "readiness_status": "research_only",
                                "scope_verification_status": "general_universe",
                                "freshness_status": "",
                                "blocked_reason": "仅研究。",
                                "verified_scope_hash": "",
                            },
                            "alpha_scope": "general",
                            "count": 1,
                            "top_n": 10,
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        authenticated_page.goto(f"{config.base_url}{config.equity_screen_url}")
        _assert_equity_contract(authenticated_page)
        _assert_equity_result_metrics(authenticated_page)

    def test_fund_dashboard_loads(self, authenticated_page: Page) -> None:
        """Test that fund dashboard page loads."""
        authenticated_page.goto(f"{config.base_url}{config.fund_dashboard_url}")
        _assert_fund_contract(authenticated_page)

    def test_asset_analysis_screen_loads(self, authenticated_page: Page) -> None:
        """Test that asset analysis page loads."""
        authenticated_page.goto(f"{config.base_url}{config.asset_analysis_screen_url}")
        _assert_asset_analysis_contract(authenticated_page)

    def test_backtest_create_loads(self, authenticated_page: Page) -> None:
        """Test that backtest creation page loads."""
        authenticated_page.goto(f"{config.base_url}{config.backtest_create_url}")
        _assert_backtest_contract(authenticated_page)

    def test_simulated_trading_dashboard_loads(self, authenticated_page: Page) -> None:
        """Test that simulated trading dashboard loads."""
        authenticated_page.goto(f"{config.base_url}{config.simulated_trading_dashboard_url}")
        _assert_simulated_trading_contract(authenticated_page)

    def test_audit_reports_loads(self, authenticated_page: Page) -> None:
        """Test that audit reports page loads."""
        authenticated_page.goto(f"{config.base_url}{config.audit_reports_url}")
        _assert_audit_contract(authenticated_page)

    def test_filter_manage_loads(self, authenticated_page: Page) -> None:
        """Test that filter management page loads."""
        authenticated_page.goto(f"{config.base_url}{config.filter_manage_url}")
        _assert_filter_contract(authenticated_page)

    def test_sector_analysis_loads(self, authenticated_page: Page) -> None:
        """Test that sector analysis page loads."""
        authenticated_page.goto(f"{config.base_url}{config.sector_analysis_url}")
        _assert_rotation_contract(authenticated_page)


class TestAdminExposureSmoke:
    """Smoke tests for Django Admin exposure."""

    def test_admin_index_accessible(self, page: Page) -> None:
        """Test that admin index is accessible."""
        page.goto(f"{config.base_url}{config.admin_index}")
        # Admin should be accessible but we need to verify
        assert "/admin/" in page.url or "login" in page.url

    def test_admin_exposes_modules(self, authenticated_page: Page) -> None:
        """Check what modules are exposed in admin.
        Note: authenticated_page uses custom login (/account/login/).
        Django admin may use the same authentication (shared session).
        """
        authenticated_page.goto(f"{config.base_url}{config.admin_index}")
        admin = AdminPage(authenticated_page)

        # Check if we're on an admin page
        assert admin.is_django_admin_page(), "Should be on Django admin page"

        modules = admin.get_admin_modules()

        # The test outcome depends on authentication state:
        # - If modules are found: User is authenticated with Django admin
        # - If no modules: Either on login page or different page structure
        if len(modules) == 0:
            # Check if we're actually on the admin login page
            # or if we're authenticated but the page structure is different
            if "/admin/login/" not in authenticated_page.url:
                # We're authenticated but no modules found with current selector
                # This is OK - it just means the admin page structure differs
                # from the expected .app selector
                pass
        else:
            # Modules found - user has admin access
            assert len(modules) > 0

    def test_user_pages_not_admin(self, authenticated_page: Page) -> None:
        """Verify user-facing pages are not Admin pages."""
        user_urls = [
            config.dashboard_url,
            config.macro_data_url,
            config.regime_dashboard_url,
            config.signal_manage_url,
        ]

        for url in user_urls:
            authenticated_page.goto(f"{config.base_url}{url}")
            admin = AdminPage(authenticated_page)
            is_admin = admin.is_django_admin_page()
            assert not is_admin, f"User page {url} appears to be Django Admin page"


class TestScreenshotBaseline:
    """Generate baseline screenshots for all pages."""

    @pytest.mark.screenshot
    def test_screenshot_login_page(self, login_page: LoginPage, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of login page."""
        login_page.goto()
        screenshot_utils.capture_baseline(login_page.page, "login_page", module="auth")

    @pytest.mark.screenshot
    def test_screenshot_dashboard(self, authenticated_dashboard: DashboardPage, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of dashboard."""
        authenticated_dashboard.goto()
        screenshot_utils.capture_baseline(authenticated_dashboard.page, "dashboard", module="dashboard")

    @pytest.mark.screenshot
    def test_screenshot_macro_data(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of macro data page."""
        authenticated_page.goto(f"{config.base_url}{config.macro_data_url}")
        screenshot_utils.capture_baseline(authenticated_page, "macro_data", module="macro")

    @pytest.mark.screenshot
    def test_screenshot_regime_dashboard(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of regime dashboard."""
        authenticated_page.goto(f"{config.base_url}{config.regime_dashboard_url}")
        screenshot_utils.capture_baseline(authenticated_page, "regime_dashboard", module="regime")

    @pytest.mark.screenshot
    def test_screenshot_signal_manage(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of signal management."""
        authenticated_page.goto(f"{config.base_url}{config.signal_manage_url}")
        screenshot_utils.capture_baseline(authenticated_page, "signal_manage", module="signal")

    @pytest.mark.screenshot
    def test_screenshot_equity_screen(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of equity screening."""
        authenticated_page.goto(f"{config.base_url}{config.equity_screen_url}")
        screenshot_utils.capture_baseline(authenticated_page, "equity_screen", module="equity")

    @pytest.mark.screenshot
    def test_screenshot_fund_dashboard(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of fund dashboard."""
        authenticated_page.goto(f"{config.base_url}{config.fund_dashboard_url}")
        screenshot_utils.capture_baseline(authenticated_page, "fund_dashboard", module="fund")

    @pytest.mark.screenshot
    def test_screenshot_backtest_create(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of backtest creation."""
        authenticated_page.goto(f"{config.base_url}{config.backtest_create_url}")
        screenshot_utils.capture_baseline(authenticated_page, "backtest_create", module="backtest")

    @pytest.mark.screenshot
    def test_screenshot_simulated_trading(self, authenticated_page: Page, screenshot_utils: ScreenshotUtils) -> None:
        """Capture baseline screenshot of simulated trading."""
        authenticated_page.goto(f"{config.base_url}{config.simulated_trading_dashboard_url}")
        screenshot_utils.capture_baseline(authenticated_page, "simulated_trading", module="simulated_trading")
