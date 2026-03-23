"""
Dashboard page object for main dashboard testing.
"""
from playwright.sync_api import Page, expect

from tests.playwright.config.selectors import common
from tests.playwright.config.test_config import config
from tests.playwright.pages.base_page import BasePage


class DashboardPage(BasePage):
    """Page object for the main dashboard."""

    def __init__(self, page: Page, base_url: str = None):
        """Initialize dashboard page.

        Args:
            page: Playwright page object
            base_url: Base URL for the application
        """
        super().__init__(page, base_url)
        self.url_path = config.dashboard_url

    # Navigation

    def goto(self) -> None:
        """Navigate to the dashboard."""
        self.navigate(self.url_path)

    # Module Navigation

    def go_to_macro_data(self) -> None:
        """Navigate to macro data page."""
        self.click('a[href*="/macro/"], a:has-text("宏观数据"), a:has-text("Macro")')

    def go_to_regime_dashboard(self) -> None:
        """Navigate to regime dashboard."""
        self.click('a[href*="/regime/"], a:has-text("象限"), a:has-text("Regime")')

    def go_to_signal_manage(self) -> None:
        """Navigate to signal management."""
        self.click('a[href*="/signal/"], a:has-text("信号"), a:has-text("Signal")')

    def go_to_equity_screen(self) -> None:
        """Navigate to equity screening."""
        self.click('a[href*="/equity/"], a:has-text("证券"), a:has-text("股票"), a:has-text("Equity")')

    def go_to_fund_dashboard(self) -> None:
        """Navigate to fund dashboard."""
        self.click('a[href*="/fund/"], a:has-text("基金"), a:has-text("Fund")')

    def go_to_backtest(self) -> None:
        """Navigate to backtest page."""
        self.click('a[href*="/backtest/"], a:has-text("回测"), a:has-text("Backtest")')

    def go_to_simulated_trading(self) -> None:
        """Navigate to simulated trading."""
        self.click('a[href*="/simulated-trading/"], a:has-text("模拟交易"), a:has-text("Trading")')

    def go_to_audit(self) -> None:
        """Navigate to audit page."""
        self.click('a[href*="/audit/"], a:has-text("审计"), a:has-text("Audit")')

    # Element Access

    def get_stat_cards(self):
        """Get all stat cards on dashboard."""
        return self.page.locator(".stat-card, .metric-card, .info-box").all()

    def get_charts(self):
        """Get all chart containers."""
        return self.page.locator(".chart, .graph, canvas").all()

    def get_menu_items(self):
        """Get all navigation menu items."""
        return self.page.locator(".nav-item, .menu-item").all()

    def get_recent_activity(self):
        """Get recent activity section."""
        return self.page.locator(".recent-activity, .activity-feed")

    # Assertions

    def assert_on_dashboard(self) -> None:
        """Assert that we are on the dashboard page."""
        expect(self.page).to_have_url(f"**{self.url_path}**")

    def assert_has_stat_cards(self) -> None:
        """Assert that dashboard has stat cards."""
        cards = self.get_stat_cards()
        assert len(cards) > 0, "No stat cards found on dashboard"

    def assert_has_charts(self) -> None:
        """Assert that dashboard has charts."""
        charts = self.get_charts()
        assert len(charts) > 0, "No charts found on dashboard"
