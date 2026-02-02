"""
Regime page object for regime quadrant testing.
"""
from playwright.sync_api import Page, expect

from tests.playwright.pages.base_page import BasePage
from tests.playwright.config.test_config import config


class RegimePage(BasePage):
    """Page object for regime pages."""

    def __init__(self, page: Page, base_url: str = None):
        """Initialize regime page.

        Args:
            page: Playwright page object
            base_url: Base URL for the application
        """
        super().__init__(page, base_url)
        self.dashboard_url = config.regime_dashboard_url
        self.state_url = config.regime_state_url
        self.history_url = config.regime_history_url

    # Navigation

    def goto_dashboard(self) -> None:
        """Navigate to regime dashboard."""
        self.navigate(self.dashboard_url)

    def goto_state(self) -> None:
        """Navigate to regime state page."""
        self.navigate(self.state_url)

    def goto_history(self) -> None:
        """Navigate to regime history page."""
        self.navigate(self.history_url)

    # Element Access

    def get_quadrant_chart(self):
        """Get the regime quadrant chart."""
        return self.page.locator(".regime-quadrant, .quadrant-chart, .quadrant").first

    def get_current_state(self):
        """Get current regime state display."""
        return self.page.locator(".regime-state, .current-state, .current-regime").first

    def get_history_table(self):
        """Get regime history table."""
        return self.page.locator(".regime-history, .history-table, table").first

    def get_regime_indicator(self):
        """Get regime indicator/graph."""
        return self.page.locator(".regime-indicator, .regime-graph, canvas").first

    # Actions

    def get_current_regime(self) -> str:
        """Get the current regime value.

        Returns:
            Current regime text (e.g., "Reflation", "Disinflation")
        """
        state = self.get_current_state()
        if state.count() > 0:
            return state.inner_text()
        return ""

    # Assertions

    def assert_on_dashboard(self) -> None:
        """Assert that we are on regime dashboard."""
        expect(self.page).to_have_url(f"**{self.dashboard_url}**")

    def assert_has_quadrant(self) -> None:
        """Assert that page has quadrant chart."""
        quadrant = self.get_quadrant_chart()
        expect(quadrant).to_be_visible()

    def assert_has_history(self) -> None:
        """Assert that page has regime history."""
        history = self.get_history_table()
        expect(history).to_be_visible()
