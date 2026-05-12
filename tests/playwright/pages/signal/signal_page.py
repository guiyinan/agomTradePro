"""
Signal page object for investment signal testing.
"""

from playwright.sync_api import Page, expect

from tests.playwright.config.selectors import common
from tests.playwright.config.test_config import config
from tests.playwright.pages.base_page import BasePage


class SignalPage(BasePage):
    """Page object for signal management pages."""

    def __init__(self, page: Page, base_url: str = None):
        """Initialize signal page.

        Args:
            page: Playwright page object
            base_url: Base URL for the application
        """
        super().__init__(page, base_url)
        self.manage_url = config.signal_manage_url
        self.create_url = config.signal_create_url
        self.list_url = config.signal_list_url

    # Navigation

    def goto_manage(self) -> None:
        """Navigate to signal management page."""
        self.navigate(self.manage_url)

    def goto_create(self) -> None:
        """Navigate to create signal page."""
        self.navigate(self.create_url)

    def goto_list(self) -> None:
        """Navigate to signal list page."""
        self.navigate(self.list_url)

    # Element Access

    def get_signal_list(self):
        """Get signal list/table."""
        return self.page.locator(".signal-list, .signals-table, table").first

    def get_signal_cards(self):
        """Get all signal cards."""
        return self.page.locator(".signal-card, .investment-signal").all()

    def get_filter_form(self):
        """Get signal filter form."""
        return self.page.locator(".signal-filter, .filter-form").first

    def get_add_button(self):
        """Get add/create signal button."""
        return self.page.locator(common.btn_add).first

    def get_edit_buttons(self):
        """Get all edit buttons."""
        return self.page.locator(common.btn_edit).all()

    def get_delete_buttons(self):
        """Get all delete buttons."""
        return self.page.locator(common.btn_delete).all()

    # Actions

    def click_add_signal(self) -> None:
        """Click add signal button and check for modal."""
        btn = self.get_add_button()
        btn.click()

    def click_edit_signal(self, index: int = 0) -> None:
        """Click edit signal button.

        Args:
            index: Index of edit button to click
        """
        buttons = self.get_edit_buttons()
        if index < len(buttons):
            buttons[index].click()

    def get_signals(self) -> list[dict]:
        """Get all signals from the list.

        Returns:
            List of signal data
        """
        signals = []
        table = self.get_signal_list()

        if table.count() > 0:
            rows = table.locator("tr").all()
            for row in rows:
                cells = row.locator("td, th").all()
                data = [cell.inner_text().strip() for cell in cells]
                if data:
                    signals.append({"cells": data})

        return signals

    # Modal Detection

    def has_add_modal(self) -> bool:
        """Check if add signal opens a modal.

        Returns:
            True if modal appears after clicking add
        """
        return self.has_modal()

    def has_edit_modal(self) -> bool:
        """Check if edit signal opens a modal.

        Returns:
            True if modal appears after clicking edit
        """
        return self.has_modal()

    def has_delete_confirmation(self) -> bool:
        """Check if delete has confirmation.

        Returns:
            True if delete has confirmation dialog
        """
        delete_btns = self.get_delete_buttons()
        if delete_btns:
            btn = delete_btns[0]
            has_confirm = (
                btn.get_attribute("data-confirm") or
                (btn.get_attribute("onclick") and "confirm" in btn.get_attribute("onclick"))
            )
            return bool(has_confirm)
        return False

    # Assertions

    def assert_on_manage_page(self) -> None:
        """Assert that we are on signal management page."""
        expect(self.page).to_have_url(f"**{self.manage_url}**")

    def assert_has_signals(self) -> None:
        """Assert that page has signals listed."""
        list_el = self.get_signal_list()
        cards = self.get_signal_cards()
        assert list_el.count() > 0 or len(cards) > 0, "No signals found on page"

    def assert_add_uses_modal(self) -> None:
        """Assert that add operation uses a modal."""
        self.click_add_signal()
        assert self.has_add_modal(), "Add signal did not open a modal"
        self.close_modal()

    def assert_delete_has_confirmation(self) -> None:
        """Assert that delete has confirmation dialog."""
        assert self.has_delete_confirmation(), "Delete operation lacks confirmation"
