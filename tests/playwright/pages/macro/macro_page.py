"""
Macro data page object for macro data testing.
"""
from playwright.sync_api import Page, expect

from tests.playwright.config.test_config import config
from tests.playwright.pages.base_page import BasePage


class MacroPage(BasePage):
    """Page object for macro data pages."""

    def __init__(self, page: Page, base_url: str = None):
        """Initialize macro page.

        Args:
            page: Playwright page object
            base_url: Base URL for the application
        """
        super().__init__(page, base_url)
        self.data_url = config.macro_data_url
        self.indicator_url = config.macro_indicator_url

    # Navigation

    def goto_data(self) -> None:
        """Navigate to macro data page."""
        self.navigate(self.data_url)

    def goto_indicator(self, indicator_code: str = "") -> None:
        """Navigate to specific indicator page.

        Args:
            indicator_code: Optional indicator code
        """
        path = f"{self.indicator_url}{indicator_code}" if indicator_code else self.indicator_url
        self.navigate(path)

    # Element Access

    def get_indicator_list(self):
        """Get indicator list/table."""
        return self.page.locator(".indicator-list, .data-list, table").first

    def get_indicator_chart(self):
        """Get indicator chart container."""
        return self.page.locator(".indicator-chart, .data-chart, .chart").first

    def get_date_range_picker(self):
        """Get date range picker element."""
        return self.page.locator(".date-range, input[type='date']").first

    def get_filter_form(self):
        """Get filter form element."""
        return self.page.locator(".filter-form, .filters").first

    # Actions

    def select_indicator(self, indicator_name: str) -> None:
        """Select an indicator from the list.

        Args:
            indicator_name: Name of the indicator to select
        """
        self.click(f"a:has-text('{indicator_name}'), tr:has-text('{indicator_name}')")

    def filter_by_date(self, start_date: str, end_date: str) -> None:
        """Filter data by date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        """
        date_inputs = self.page.locator("input[type='date']").all()
        if len(date_inputs) >= 2:
            date_inputs[0].fill(start_date)
            date_inputs[1].fill(end_date)

    # Assertions

    def assert_on_data_page(self) -> None:
        """Assert that we are on the macro data page."""
        expect(self.page).to_have_url(f"**{self.data_url}**")

    def assert_has_indicators(self) -> None:
        """Assert that page has indicator data."""
        indicator_list = self.get_indicator_list()
        expect(indicator_list).to_be_visible()

    def assert_not_admin_page(self) -> None:
        """Assert that this is not an Admin page."""
        super().assert_not_admin_page()
