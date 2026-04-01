"""
Comprehensive Playwright UAT regression coverage for key user-facing surfaces.

This suite replaces the old root-level smoke script with collected pytest tests
that reuse the shared Playwright fixtures, markers, and failure screenshot flow.
"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
from urllib.parse import urljoin, urlparse

import pytest
from playwright.sync_api import Page, Response

from tests.playwright.config.test_config import config

PUBLIC_SURFACES = [
    pytest.param("/", None, id="home"),
    pytest.param(config.login_url, config.login_url, id="login"),
    pytest.param("/api/docs/", "/api/docs/", id="swagger"),
    pytest.param("/api/redoc/", "/api/redoc/", id="redoc"),
]

PROTECTED_ENTRYPOINTS = [
    pytest.param(config.dashboard_url, id="dashboard"),
    pytest.param(config.policy_manage_url, id="policy-workbench"),
    pytest.param("/decision/workspace/", id="decision-workspace"),
    pytest.param("/ops/", id="ops-center"),
]

AUTHENTICATED_SURFACES = [
    pytest.param(config.dashboard_url, "/dashboard/", id="dashboard"),
    pytest.param(config.macro_data_url, "/macro/", id="macro-data"),
    pytest.param(config.regime_dashboard_url, "/regime/", id="regime-dashboard"),
    pytest.param(config.signal_manage_url, "/signal/", id="signal-manage"),
    pytest.param(config.policy_manage_url, "/policy/workbench/", id="policy-workbench"),
    pytest.param(config.equity_screen_url, "/equity/", id="equity-screen"),
    pytest.param(config.fund_dashboard_url, "/fund/", id="fund-dashboard"),
    pytest.param(config.asset_analysis_screen_url, "/asset-analysis/", id="asset-analysis"),
    pytest.param(config.backtest_create_url, "/backtest/", id="backtest"),
    pytest.param(config.simulated_trading_dashboard_url, "/simulated-trading/", id="simulated-trading"),
    pytest.param(config.audit_reports_url, "/audit/", id="audit"),
    pytest.param(config.filter_manage_url, "/filter/", id="filter"),
    pytest.param(config.sector_analysis_url, "/sector/", id="sector"),
    pytest.param("/decision/workspace/", "/decision/workspace/", id="decision-workspace"),
    pytest.param("/ops/", "/ops/", id="ops-center"),
    pytest.param(config.admin_index, "/admin/", id="admin-index"),
]

NON_PAGE_LINK_PREFIXES = (
    "/api/",
    "/static/",
    "/media/",
    "/admin/logout/",
    "/account/logout/",
)


def _goto(page: Page, path: str) -> Response | None:
    """Navigate to a path using the shared runtime base URL with light retry on transient refusal."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return page.goto(
                f"{config.base_url}{path}",
                wait_until="networkidle",
                timeout=config.navigation_timeout,
            )
        except Exception as exc:
            last_error = exc
            if "ERR_CONNECTION_REFUSED" not in str(exc) or attempt == 2:
                raise
            page.wait_for_timeout(1000)
    if last_error:
        raise last_error
    return None


def _assert_http_success(response: Response | None, path: str) -> None:
    """Assert the final browser navigation resolves to a non-error HTTP response."""
    assert response is None or response.status < 400, f"{path} returned HTTP {response.status}"


def _assert_non_error_shell(page: Page, expected_path_fragment: str | None = None) -> None:
    """Assert the rendered page is not a 404/500 shell and has visible content."""
    page.wait_for_load_state("networkidle")
    body_text = page.locator("body").inner_text(timeout=5000)

    assert body_text.strip(), "Page body should not be empty"
    assert "/404/" not in page.url, f"Unexpected 404 page: {page.url}"
    assert "Page not found" not in body_text
    assert "Server Error (500)" not in body_text
    assert "Traceback" not in body_text

    if expected_path_fragment:
        assert expected_path_fragment in page.url, (
            f"Expected path fragment {expected_path_fragment!r}, got {page.url!r}"
        )


def _assert_login_redirect(page: Page, path: str) -> None:
    """Assert a protected route redirects unauthenticated users to a login page."""
    _goto(page, path)
    current_url = page.url.lower()
    assert "login" in current_url or "/account/" in current_url, (
        f"Expected auth redirect for {path}, got {page.url}"
    )
    _assert_non_error_shell(page, "/login/")


def _collect_internal_paths(page: Page, limit: int = 5) -> list[str]:
    """Collect a small, stable set of internal HTML page links from the current page."""
    hrefs = page.eval_on_selector_all(
        "a[href]",
        "elements => elements.map(element => element.getAttribute('href') || '')",
    )
    base_netloc = urlparse(config.base_url).netloc
    paths: list[str] = []

    for href in hrefs:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        parsed = urlparse(urljoin(config.base_url, href))
        if parsed.netloc and parsed.netloc != base_netloc:
            continue

        path = parsed.path or "/"
        if any(path.startswith(prefix) for prefix in NON_PAGE_LINK_PREFIXES):
            continue
        if path in paths:
            continue

        paths.append(path)
        if len(paths) >= limit:
            break

    return paths


def _assert_paths_are_navigable(page: Page, paths: list[str], allow_login_redirect: bool = False) -> None:
    """Assert each discovered path can be opened without landing on an error shell."""
    assert paths, "Expected at least one internal link to validate"

    for path in paths:
        response = _goto(page, path)
        _assert_http_success(response, path)
        if allow_login_redirect and "login" in page.url.lower():
            _assert_non_error_shell(page, "/login/")
            continue
        _assert_non_error_shell(page)


def _cleanup_signal(asset_code: str, django_db_blocker) -> None:
    """Delete a created signal by unique asset code."""
    def _delete() -> None:
        with django_db_blocker.unblock():
            from apps.signal.infrastructure.models import InvestmentSignalModel

            InvestmentSignalModel.objects.filter(asset_code=asset_code).delete()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_delete)
        future.result()


def _seed_signal(asset_code: str, django_db_blocker, *, status: str = "pending") -> None:
    """Create a deterministic signal owned by the Playwright admin user."""
    def _create() -> None:
        with django_db_blocker.unblock():
            from django.contrib.auth import get_user_model

            from apps.signal.infrastructure.models import InvestmentSignalModel

            user = get_user_model().objects.get(username=config.admin_username)
            InvestmentSignalModel.objects.create(
                user=user,
                asset_code=asset_code,
                asset_class="EQUITY",
                direction="LONG",
                logic_desc=f"Seeded Playwright signal {asset_code}",
                invalidation_logic="CN_PMI < 49",
                invalidation_description="CN_PMI < 49",
                invalidation_rules={
                    "conditions": [{"indicator": "CN_PMI", "condition": "lt", "threshold": 49}],
                    "logic": "AND",
                },
                target_regime="Recovery",
                status=status,
                rejection_reason="",
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_create)
        future.result()


def _cleanup_account(account_name: str, django_db_blocker) -> None:
    """Delete a created investment account by its unique test name."""
    def _delete() -> None:
        with django_db_blocker.unblock():
            from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

            SimulatedAccountModel.objects.filter(account_name=account_name).delete()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_delete)
        future.result()


def _seed_account(account_name: str, django_db_blocker, *, account_type: str = "simulated") -> int:
    """Create a deterministic investment account for the Playwright admin user."""
    def _create() -> int:
        with django_db_blocker.unblock():
            from django.contrib.auth import get_user_model

            from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

            user = get_user_model().objects.get(username=config.admin_username)
            account = SimulatedAccountModel.objects.create(
                user=user,
                account_name=account_name,
                account_type=account_type,
                initial_capital=Decimal("100000.00"),
                current_cash=Decimal("82000.00"),
                current_market_value=Decimal("18000.00"),
                total_value=Decimal("100000.00"),
                total_return=0.0,
                annual_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                total_trades=0,
                winning_trades=0,
                is_active=True,
                auto_trading_enabled=True,
                max_position_pct=20.0,
                max_total_position_pct=95.0,
                commission_rate=0.0003,
                slippage_rate=0.001,
            )
            return int(account.id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_create)
        return future.result()


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.global_experience
class TestComprehensiveSurfaceAvailability:
    """High-level user-visible surfaces remain reachable in the browser."""

    @pytest.mark.parametrize(("path", "expected_path_fragment"), PUBLIC_SURFACES)
    def test_public_surfaces_load(self, page: Page, path: str, expected_path_fragment: str | None) -> None:
        """Public entry surfaces should load without rendering an error shell."""
        response = _goto(page, path)
        _assert_http_success(response, path)
        _assert_non_error_shell(page, expected_path_fragment)

    @pytest.mark.parametrize("path", PROTECTED_ENTRYPOINTS)
    def test_protected_surfaces_redirect_to_login(self, page: Page, path: str) -> None:
        """Protected entry surfaces should send unauthenticated users to login."""
        _assert_login_redirect(page, path)

    @pytest.mark.parametrize(("path", "expected_path_fragment"), AUTHENTICATED_SURFACES)
    def test_authenticated_surfaces_load(
        self,
        authenticated_page: Page,
        path: str,
        expected_path_fragment: str,
    ) -> None:
        """Authenticated users should reach key work surfaces without 404/500 shells."""
        response = _goto(authenticated_page, path)
        _assert_http_success(response, path)
        _assert_non_error_shell(authenticated_page, expected_path_fragment)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.navigation
@pytest.mark.slow
class TestComprehensiveNavigationRegression:
    """Link-level regression checks derived from the old comprehensive smoke script."""

    def test_homepage_links_remain_navigable(self, page: Page) -> None:
        """A sample of homepage links should stay reachable for anonymous users."""
        response = _goto(page, "/")
        _assert_http_success(response, "/")
        _assert_non_error_shell(page)

        sampled_paths = _collect_internal_paths(page, limit=4)
        _assert_paths_are_navigable(page, sampled_paths, allow_login_redirect=True)

    def test_dashboard_links_remain_navigable(self, authenticated_page: Page) -> None:
        """The dashboard should expose internal links that navigate to usable pages."""
        response = _goto(authenticated_page, config.dashboard_url)
        _assert_http_success(response, config.dashboard_url)
        _assert_non_error_shell(authenticated_page, "/dashboard/")

        sampled_paths = _collect_internal_paths(authenticated_page, limit=5)
        _assert_paths_are_navigable(authenticated_page, sampled_paths)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.navigation
@pytest.mark.slow
class TestAdminNavigationRegression:
    """Admin navigation regression checks for the superuser Playwright session."""

    def test_admin_index_links_remain_navigable(self, authenticated_page: Page) -> None:
        """Admin index should expose reachable module links for the superuser test account."""
        response = _goto(authenticated_page, config.admin_index)
        _assert_http_success(response, config.admin_index)
        _assert_non_error_shell(authenticated_page, "/admin/")

        sampled_paths = _collect_internal_paths(authenticated_page, limit=5)
        _assert_paths_are_navigable(authenticated_page, sampled_paths)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.priority
class TestComprehensiveBusinessWorkflowShells:
    """Second-phase UAT checks for actionable workflows on core business pages."""

    def test_signal_page_exposes_creation_and_review_controls(self, authenticated_page: Page) -> None:
        """Signal management should expose AI assistance, creation fields, and review context."""
        response = _goto(authenticated_page, config.signal_manage_url)
        _assert_http_success(response, config.signal_manage_url)
        _assert_non_error_shell(authenticated_page, "/signal/")

        assert authenticated_page.locator("#aiInput").count() == 1
        assert authenticated_page.locator("button:has-text('AI 生成规则')").count() == 1
        assert authenticated_page.locator("#createForm").count() == 1
        assert authenticated_page.locator('input[name="asset_code"]').count() == 1
        assert authenticated_page.locator('select[name="asset_class"]').count() == 1
        assert authenticated_page.locator('input[name="logic_desc"]').count() == 1
        assert authenticated_page.locator('button[type="submit"]:has-text("创建信号")').count() == 1
        assert authenticated_page.locator(".stats-row .stat-card").count() >= 4
        assert (
            authenticated_page.locator(".signal-card").count() > 0
            or authenticated_page.locator(".empty-state").count() == 1
        ), "Signal page should show either existing signals or an empty state"

    def test_policy_workbench_exposes_filters_tabs_and_batch_actions(self, authenticated_page: Page) -> None:
        """Policy workbench should expose the core operator controls for triage."""
        response = _goto(authenticated_page, config.policy_manage_url)
        _assert_http_success(response, config.policy_manage_url)
        _assert_non_error_shell(authenticated_page, "/policy/workbench/")

        assert authenticated_page.locator(".overview-cards .overview-card").count() == 4
        assert authenticated_page.locator(".tab-nav .tab-btn").count() == 3
        assert authenticated_page.locator("#filter-event-type").count() == 1
        assert authenticated_page.locator("#filter-level").count() == 1
        assert authenticated_page.locator("#filter-gate-level").count() == 1
        assert authenticated_page.locator("#filter-start-date").count() == 1
        assert authenticated_page.locator("#filter-end-date").count() == 1
        assert authenticated_page.locator("#filter-search").count() == 1
        assert authenticated_page.locator("#events-tbody").count() == 1
        assert authenticated_page.locator('button:has-text("批量通过")').count() == 1
        assert authenticated_page.locator('button:has-text("批量拒绝")').count() == 1
        assert authenticated_page.locator(".quick-actions button").count() >= 2

    def test_backtest_page_supports_form_preparation_before_submission(self, authenticated_page: Page) -> None:
        """Backtest page should prefill dates and expose the core run configuration form."""
        response = _goto(authenticated_page, config.backtest_create_url)
        _assert_http_success(response, config.backtest_create_url)
        _assert_non_error_shell(authenticated_page, "/backtest/")

        authenticated_page.fill("#name", "Phase2 UAT Backtest")
        assert authenticated_page.input_value("#name") == "Phase2 UAT Backtest"

        start_date_before = authenticated_page.input_value("#start_date")
        end_date_before = authenticated_page.input_value("#end_date")
        assert start_date_before, "Backtest page should initialize a start date"
        assert end_date_before, "Backtest page should initialize an end date"

        authenticated_page.click('button:has-text("最近1年")')
        start_date_after = authenticated_page.input_value("#start_date")
        end_date_after = authenticated_page.input_value("#end_date")
        assert start_date_after, "Preset selection should keep a start date"
        assert end_date_after, "Preset selection should keep an end date"

        assert authenticated_page.input_value("#initial_capital") == "100000"
        assert authenticated_page.input_value("#transaction_cost_bps") == "10"
        assert authenticated_page.locator("#rebalance_frequency").count() == 1
        assert authenticated_page.locator("#use_pit_data").count() == 1
        assert authenticated_page.locator("#submit-btn").is_enabled()

    def test_simulated_accounts_page_supports_account_creation_shell(self, authenticated_page: Page) -> None:
        """Account management should expose creation modal controls and portfolio operations."""
        response = _goto(authenticated_page, config.simulated_trading_positions_url)
        _assert_http_success(response, config.simulated_trading_positions_url)
        _assert_non_error_shell(authenticated_page, "/simulated-trading/")

        assert authenticated_page.locator('button:has-text("创建新投资组合")').count() == 1
        authenticated_page.click('button:has-text("创建新投资组合")')
        assert authenticated_page.locator("#createModal").count() == 1
        assert authenticated_page.locator("#createModal").is_visible()

        assert authenticated_page.locator("#account_name").count() == 1
        assert authenticated_page.locator("#account_type").count() == 1
        assert authenticated_page.locator("#initial_capital").count() == 1

        authenticated_page.click("#createModal .quick-option-btn:nth-child(3)")
        assert authenticated_page.input_value("#initial_capital") == "500000"

        assert (
            authenticated_page.locator(".account-card").count() > 0
            or authenticated_page.locator('text=您还没有创建任何投资组合').count() == 1
        ), "Account page should show cards or a clear empty state"

    def test_decision_workspace_exposes_stepper_and_account_context(self, authenticated_page: Page) -> None:
        """Decision workspace should expose account context and the six-step funnel structure."""
        response = _goto(authenticated_page, "/decision/workspace/")
        _assert_http_success(response, "/decision/workspace/")
        _assert_non_error_shell(authenticated_page, "/decision/workspace/")

        assert authenticated_page.locator("#workspace-account-selector").count() == 1
        assert authenticated_page.locator(".workspace-kpi").count() == 6
        assert authenticated_page.locator("#workspace-position-list").count() == 1
        assert authenticated_page.locator(".step-button").count() == 6
        assert authenticated_page.locator("#step-1-container").count() == 1
        assert authenticated_page.locator("#step-6-container").count() == 1
        assert authenticated_page.locator("#funnel-loading-indicator").count() == 1

    def test_ops_center_search_filters_configuration_cards(self, authenticated_page: Page) -> None:
        """Ops center should allow narrowing and resetting configuration cards in the browser."""
        response = _goto(authenticated_page, "/ops/")
        _assert_http_success(response, "/ops/")
        _assert_non_error_shell(authenticated_page, "/ops/")

        search = authenticated_page.locator("#config-search")
        section_filter = authenticated_page.locator("#config-section-filter")
        status_filter = authenticated_page.locator("#config-status-filter")
        cards = authenticated_page.locator(".config-card")

        assert search.count() == 1
        assert section_filter.count() == 1
        assert status_filter.count() == 1
        assert cards.count() > 0, "Ops center should render configuration cards"

        search.fill("zzzz-no-match")
        authenticated_page.wait_for_timeout(150)
        assert authenticated_page.locator(".config-card:visible").count() == 0

        search.fill("")
        authenticated_page.wait_for_timeout(150)
        assert authenticated_page.locator(".config-card:visible").count() > 0

    def test_terminal_shell_updates_input_counter_and_mode_selector(self, authenticated_page: Page) -> None:
        """Terminal UI should expose input, mode selection, and reactive character counting."""
        response = _goto(authenticated_page, "/terminal/")
        _assert_http_success(response, "/terminal/")
        _assert_non_error_shell(authenticated_page, "/terminal/")

        terminal_input = authenticated_page.locator("#terminal-input")
        input_count = authenticated_page.locator("#terminal-input-count")
        mode_select = authenticated_page.locator("#terminal-mode-select")

        assert terminal_input.count() == 1
        assert authenticated_page.locator("#provider-select").count() == 1
        assert authenticated_page.locator("#model-select").count() == 1
        assert authenticated_page.locator(".quick-cmd-btn").count() >= 5

        terminal_input.fill("/help")
        authenticated_page.wait_for_timeout(100)
        assert input_count.inner_text().startswith("5/"), "Character counter should react to input"

        mode_select.select_option("readonly")
        assert mode_select.input_value() == "readonly"


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.priority
@pytest.mark.slow
class TestComprehensiveInteractiveFlows:
    """Third-phase UAT coverage with visible state changes from real interactions."""

    def test_signal_creation_round_trip_adds_a_card(self, authenticated_page: Page, django_db_blocker) -> None:
        """Creating a signal through the browser should reload and show the new asset code."""
        asset_code = f"UATSIG{uuid4().hex[:8].upper()}"

        try:
            response = _goto(authenticated_page, config.signal_manage_url)
            _assert_http_success(response, config.signal_manage_url)
            _assert_non_error_shell(authenticated_page, "/signal/")

            asset_class_value = authenticated_page.locator('select[name="asset_class"] option[value]').evaluate_all(
                """options => {
                    const valid = options
                        .map(option => option.value)
                        .filter(value => value && value.trim().length > 0);
                    return valid[0] || null;
                }"""
            )
            indicator_value = authenticated_page.locator('#indicatorSelect option[value]').evaluate_all(
                """options => {
                    const valid = options
                        .map(option => option.value)
                        .filter(value => value && value.trim().length > 0);
                    return valid[0] || null;
                }"""
            )

            if not asset_class_value or not indicator_value:
                pytest.skip("Signal form lacks selectable asset classes or indicators in current seed data")

            authenticated_page.fill('input[name="asset_code"]', asset_code)
            authenticated_page.select_option('select[name="asset_class"]', asset_class_value)
            authenticated_page.fill('input[name="logic_desc"]', f"Phase 3 UAT signal for {asset_code}")
            authenticated_page.select_option("#indicatorSelect", indicator_value)
            authenticated_page.fill("#thresholdInput", "1")
            authenticated_page.click('button:has-text("添加条件")')

            assert authenticated_page.locator("#conditionsList .condition-item").count() >= 1

            with authenticated_page.expect_navigation(wait_until="networkidle"):
                authenticated_page.click('button[type="submit"]:has-text("创建信号")')

            _assert_non_error_shell(authenticated_page, "/signal/")
            assert authenticated_page.locator(f"text={asset_code}").count() >= 1
        finally:
            _cleanup_signal(asset_code, django_db_blocker)

    def test_simulated_account_creation_round_trip_adds_a_card(
        self,
        authenticated_page: Page,
        django_db_blocker,
    ) -> None:
        """Creating an investment account from the modal should surface a new account card."""
        account_name = f"Phase3-UAT-{uuid4().hex[:8]}"

        try:
            response = _goto(authenticated_page, config.simulated_trading_positions_url)
            _assert_http_success(response, config.simulated_trading_positions_url)
            _assert_non_error_shell(authenticated_page, "/simulated-trading/")

            authenticated_page.click('button:has-text("创建新投资组合")')
            assert authenticated_page.locator("#createModal").is_visible()

            authenticated_page.fill("#account_name", account_name)
            authenticated_page.select_option("#account_type", "simulated")
            authenticated_page.click("#createModal .quick-option-btn:nth-child(2)")

            with authenticated_page.expect_navigation(wait_until="networkidle"):
                authenticated_page.click('#createModal button[type="submit"]:has-text("创建")')

            _assert_non_error_shell(authenticated_page, "/simulated-trading/")
            assert authenticated_page.locator(f"text={account_name}").count() >= 1
        finally:
            _cleanup_account(account_name, django_db_blocker)

    def test_backtest_form_blocks_invalid_date_range(self, authenticated_page: Page) -> None:
        """Submitting a reversed date range should raise the client-side validation alert."""
        response = _goto(authenticated_page, config.backtest_create_url)
        _assert_http_success(response, config.backtest_create_url)
        _assert_non_error_shell(authenticated_page, "/backtest/")

        authenticated_page.evaluate(
            """() => {
                window.__uatLastAlert = null;
                window.alert = (message) => {
                    window.__uatLastAlert = message;
                };
            }"""
        )
        authenticated_page.fill("#name", "Phase 3 Invalid Date Backtest")
        authenticated_page.fill("#start_date", "2025-01-10")
        authenticated_page.fill("#end_date", "2025-01-01")
        authenticated_page.click("#submit-btn")
        authenticated_page.wait_for_timeout(150)

        alert_message = authenticated_page.evaluate("window.__uatLastAlert")
        assert alert_message is not None
        assert "起始日期必须早于结束日期" in alert_message

    def test_terminal_status_command_renders_readiness_output(self, authenticated_page: Page) -> None:
        """Quick status command should append readiness output into the terminal transcript."""
        response = _goto(authenticated_page, "/terminal/")
        _assert_http_success(response, "/terminal/")
        _assert_non_error_shell(authenticated_page, "/terminal/")

        output = authenticated_page.locator("#terminal-output")
        initial_text = output.inner_text(timeout=5000)

        authenticated_page.click('.quick-cmd-btn[data-cmd="status"]')
        authenticated_page.locator("#terminal-output").locator("text=System Readiness").wait_for(timeout=15000)

        updated_text = output.inner_text(timeout=5000)
        assert "System Readiness" in updated_text
        assert updated_text != initial_text


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.priority
@pytest.mark.slow
class TestComprehensiveActionRegression:
    """Fourth-phase UAT checks for list actions and cross-page transitions."""

    def test_pending_signal_can_be_approved_from_the_card(self, authenticated_page: Page, django_db_blocker) -> None:
        """Approving a seeded pending signal should reload the page and update its status badge."""
        asset_code = f"UATAPP{uuid4().hex[:8].upper()}"
        _seed_signal(asset_code, django_db_blocker, status="pending")

        try:
            response = _goto(authenticated_page, config.signal_manage_url)
            _assert_http_success(response, config.signal_manage_url)
            _assert_non_error_shell(authenticated_page, "/signal/")

            card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")').first
            assert card.count() == 1

            with authenticated_page.expect_navigation(wait_until="networkidle"):
                card.locator(".action-btn.approve").click()

            updated_card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")').first
            assert updated_card.locator('text=已通过').count() >= 1
        finally:
            _cleanup_signal(asset_code, django_db_blocker)

    def test_pending_signal_can_be_rejected_from_the_card(self, authenticated_page: Page, django_db_blocker) -> None:
        """Rejecting a seeded pending signal should prompt for a reason and show rejected state."""
        asset_code = f"UATREJ{uuid4().hex[:8].upper()}"
        _seed_signal(asset_code, django_db_blocker, status="pending")

        try:
            response = _goto(authenticated_page, config.signal_manage_url)
            _assert_http_success(response, config.signal_manage_url)
            _assert_non_error_shell(authenticated_page, "/signal/")

            authenticated_page.evaluate(
                """() => {
                    window.uiPrompt = async () => 'Phase4 rejection reason';
                }"""
            )

            card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")').first
            assert card.count() == 1

            with authenticated_page.expect_navigation(wait_until="networkidle"):
                card.locator(".action-btn.reject").click()

            updated_card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")').first
            assert updated_card.locator('text=已拒绝').count() >= 1
        finally:
            _cleanup_signal(asset_code, django_db_blocker)

    def test_seeded_accounts_support_batch_delete_flow(self, authenticated_page: Page, django_db_blocker) -> None:
        """Selecting two seeded accounts should enable batch delete and remove both cards."""
        account_names = [f"UAT-Batch-{uuid4().hex[:6]}-A", f"UAT-Batch-{uuid4().hex[:6]}-B"]
        for name in account_names:
            _seed_account(name, django_db_blocker)

        try:
            response = _goto(authenticated_page, config.simulated_trading_positions_url)
            _assert_http_success(response, config.simulated_trading_positions_url)
            _assert_non_error_shell(authenticated_page, "/simulated-trading/")

            authenticated_page.evaluate(
                """() => {
                    window.uiConfirm = async () => true;
                }"""
            )

            for name in account_names:
                authenticated_page.locator(f'.account-select-input[data-account-name="{name}"]').check()

            assert "已选择 2 个" in authenticated_page.locator("#selectedAccountCount").inner_text()
            assert authenticated_page.locator("#bulkDeleteBtn").is_enabled()

            authenticated_page.click("#bulkDeleteBtn")
            authenticated_page.wait_for_timeout(1400)

            for name in account_names:
                assert authenticated_page.locator(f'text={name}').count() == 0
        finally:
            for name in account_names:
                _cleanup_account(name, django_db_blocker)

    def test_ops_center_frontend_card_link_opens_a_usable_page(self, authenticated_page: Page) -> None:
        """The ops center should expose at least one frontend entry link that opens cleanly."""
        response = _goto(authenticated_page, "/ops/")
        _assert_http_success(response, "/ops/")
        _assert_non_error_shell(authenticated_page, "/ops/")

        frontend_href = authenticated_page.evaluate(
            """() => {
                const link = document.querySelector('.config-card a.btn.btn-primary[href]');
                return link ? link.getAttribute('href') : null;
            }"""
        )
        if not frontend_href:
            pytest.skip("Ops center has no visible frontend entry card in current fixture data")

        target_path = urlparse(urljoin(config.base_url, frontend_href)).path
        response = _goto(authenticated_page, target_path)
        _assert_http_success(response, target_path)
        _assert_non_error_shell(authenticated_page)

    def test_decision_workspace_account_switch_refreshes_snapshot(self, authenticated_page: Page, django_db_blocker) -> None:
        """Switching to a seeded account should refresh account summary and status text."""
        account_name = f"UAT-Workspace-{uuid4().hex[:8]}"
        account_id = _seed_account(account_name, django_db_blocker)

        try:
            response = _goto(authenticated_page, "/decision/workspace/")
            _assert_http_success(response, "/decision/workspace/")
            _assert_non_error_shell(authenticated_page, "/decision/workspace/")

            selector = authenticated_page.locator("#workspace-account-selector")
            authenticated_page.wait_for_function(
                """accountId => {
                    const selector = document.querySelector('#workspace-account-selector');
                    return !!selector?.querySelector(`option[value="${accountId}"]`);
                }""",
                arg=str(account_id),
                timeout=15000,
            )
            selector.select_option(str(account_id))

            authenticated_page.wait_for_function(
                """expectedName => {
                    return Array.from(document.querySelectorAll('[data-workspace-account-name]'))
                        .some(node => (node.textContent || '').includes(expectedName));
                }""",
                arg=account_name,
                timeout=15000,
            )
            authenticated_page.wait_for_function(
                """() => {
                    const meta = document.querySelector('#workspace-account-meta');
                    const status = document.querySelector('#workspace-account-status');
                    return !!meta && !!status
                        && meta.textContent.includes('模拟账户')
                        && ['运行中', '已停用'].includes((status.textContent || '').trim());
                }""",
                timeout=15000,
            )
            assert "模拟账户" in authenticated_page.locator("#workspace-account-meta").inner_text()
            assert authenticated_page.locator("#workspace-account-status").inner_text() in {"运行中", "已停用"}
            assert "100,000" in authenticated_page.locator("#workspace-total-value").inner_text().replace(".00", "")
        finally:
            _cleanup_account(account_name, django_db_blocker)
