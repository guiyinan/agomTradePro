"""
Base page class for Playwright tests.
Provides common functionality for all page objects.
"""
from typing import List, Optional

from playwright.sync_api import Locator, Page, expect

from tests.playwright.config.selectors import admin, common
from tests.playwright.config.test_config import config
from tests.playwright.utils.screenshot_utils import ScreenshotUtils
from tests.playwright.utils.ux_auditor import UXAuditor


class BasePage:
    """Base class for all page objects."""

    def __init__(self, page: Page, base_url: str | None = None):
        """Initialize base page.

        Args:
            page: Playwright page object
            base_url: Base URL for the application (defaults to config)
        """
        self.page = page
        self.base_url = base_url or config.base_url
        self.screenshot = ScreenshotUtils()
        self.ux_auditor = UXAuditor(self.screenshot)

    # Navigation Methods

    def navigate(self, path: str) -> None:
        """Navigate to a path.

        Args:
            path: URL path to navigate to
        """
        full_url = f"{self.base_url}{path}"
        self.page.goto(full_url, wait_until="networkidle", timeout=config.navigation_timeout)

    def reload(self) -> None:
        """Reload the current page."""
        self.page.reload(wait_until="networkidle")

    def go_back(self) -> None:
        """Navigate back in browser history."""
        self.page.go_back(wait_until="networkidle")

    def go_forward(self) -> None:
        """Navigate forward in browser history."""
        self.page.go_forward(wait_until="networkidle")

    def get_current_url(self) -> str:
        """Get the current page URL.

        Returns:
            Current page URL
        """
        return self.page.url

    def get_path(self) -> str:
        """Get the current path without base URL.

        Returns:
            Current URL path
        """
        from urllib.parse import urlparse
        parsed = urlparse(self.page.url)
        return parsed.path

    # Wait Methods

    def wait_for_load_state(self, state: str = "networkidle") -> None:
        """Wait for a specific load state.

        Args:
            state: Load state to wait for (domcontentloaded, load, networkidle)
        """
        self.page.wait_for_load_state(state)

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> Locator:
        """Wait for a selector to be available.

        Args:
            selector: CSS selector to wait for
            timeout: Timeout in milliseconds

        Returns:
            Locator for the found element
        """
        timeout = timeout or config.default_timeout
        return self.page.wait_for_selector(selector, timeout=timeout)

    def wait_for_element_visible(self, selector: str, timeout: int | None = None) -> None:
        """Wait for an element to be visible.

        Args:
            selector: CSS selector for the element
            timeout: Timeout in milliseconds
        """
        timeout = timeout or config.default_timeout
        expect(self.page.locator(selector)).to_be_visible(timeout=timeout)

    # Screenshot Methods

    def take_screenshot(self, name: str, module: str = "general") -> str:
        """Take a screenshot of the current page.

        Args:
            name: Screenshot name
            module: Module name for organization

        Returns:
            Path to the saved screenshot
        """
        return self.screenshot.capture_baseline(self.page, name, module)

    def take_full_page_screenshot(self, name: str, module: str = "general") -> str:
        """Take a full page screenshot.

        Args:
            name: Screenshot name
            module: Module name for organization

        Returns:
            Path to the saved screenshot
        """
        return self.screenshot.capture_baseline(self.page, name, module, full_page=True)

    # Admin Detection Methods

    def is_admin_page(self) -> bool:
        """Check if current page is a Django Admin page.

        Returns:
            True if on an admin page
        """
        return "/admin/" in self.page.url

    def has_admin_branding(self) -> bool:
        """Check if page has Django Admin branding.

        Returns:
            True if Django branding detected
        """
        selectors = [
            admin.admin_branding,
            "text=Django administration",
            "#site-name:has-text('Django')",
        ]

        for selector in selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def has_admin_links(self) -> bool:
        """Check if page has links to Django Admin.

        Returns:
            True if admin links found
        """
        admin_links = self.page.locator('a[href*="/admin/"]')
        return admin_links.count() > 0

    def get_admin_links(self) -> list[str]:
        """Get all admin links on the page.

        Returns:
            List of admin link URLs
        """
        links = self.page.locator('a[href*="/admin/"]').all()
        return [link.get_attribute("href") or "" for link in links]

    # UX Audit Methods

    def audit_page(self, page_name: str) -> dict:
        """Perform a UX audit on the current page.

        Args:
            page_name: Name of the page for reporting

        Returns:
            Dictionary with audit results
        """
        return self.ux_auditor.audit_page(self.page, page_name)

    # Element Interaction Methods

    def click(self, selector: str) -> None:
        """Click an element.

        Args:
            selector: CSS selector for the element
        """
        self.page.click(selector)

    def fill(self, selector: str, value: str) -> None:
        """Fill an input field.

        Args:
            selector: CSS selector for the input
            value: Value to fill
        """
        self.page.fill(selector, value)

    def type_text(self, selector: str, text: str, delay: int = 50) -> None:
        """Type text into an input with delay.

        Args:
            selector: CSS selector for the input
            text: Text to type
            delay: Delay between keystrokes in ms
        """
        self.page.type(selector, text, delay=delay)

    def select_option(self, selector: str, value: str) -> None:
        """Select an option from a select element.

        Args:
            selector: CSS selector for the select
            value: Option value to select
        """
        self.page.select_option(selector, value)

    def check(self, selector: str) -> None:
        """Check a checkbox.

        Args:
            selector: CSS selector for the checkbox
        """
        self.page.check(selector)

    def uncheck(self, selector: str) -> None:
        """Uncheck a checkbox.

        Args:
            selector: CSS selector for the checkbox
        """
        self.page.uncheck(selector)

    def hover(self, selector: str) -> None:
        """Hover over an element.

        Args:
            selector: CSS selector for the element
        """
        self.page.hover(selector)

    # Modal Detection Methods

    def has_modal(self) -> bool:
        """Check if a modal is currently visible.

        Returns:
            True if a modal is visible
        """
        modal_selectors = [
            ".modal.show",
            ".modal[style*='display: block']",
            "[role='dialog']:visible",
        ]

        for selector in modal_selectors:
            try:
                locator = self.page.locator(selector)
                if locator.count() > 0 and locator.is_visible():
                    return True
            except Exception:
                continue
        return False

    def get_modal_title(self) -> str:
        """Get the title of the currently visible modal.

        Returns:
            Modal title text
        """
        title_selectors = [
            ".modal.show .modal-title",
            "[role='dialog'] .modal-title",
            "[role='dialog'] h5",
        ]

        for selector in title_selectors:
            try:
                locator = self.page.locator(selector)
                if locator.count() > 0 and locator.is_visible():
                    return locator.inner_text().strip()
            except Exception:
                continue
        return ""

    def close_modal(self) -> None:
        """Close the currently visible modal."""
        close_selectors = [
            ".modal.show .btn-close",
            ".modal.show button[aria-label='Close']",
            ".modal.show .close",
            "[role='dialog'] .btn-close",
        ]

        for selector in close_selectors:
            try:
                locator = self.page.locator(selector).first
                if locator.is_visible():
                    locator.click()
                    return
            except Exception:
                continue

    # Navigation Element Methods

    def has_breadcrumb(self) -> bool:
        """Check if page has breadcrumb navigation.

        Returns:
            True if breadcrumb found
        """
        return self.page.locator(common.nav_breadcrumb).count() > 0

    def has_home_link(self) -> bool:
        """Check if page has a home/dashboard link.

        Returns:
            True if home link found
        """
        home_selectors = [
            'a[href="/"]',
            'a[href="/dashboard/"]',
            'a:has-text("首页")',
            'a:has-text("Home")',
            'a:has-text("Dashboard")',
        ]

        for selector in home_selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def get_breadcrumb_text(self) -> str:
        """Get the breadcrumb text.

        Returns:
            Breadcrumb text
        """
        breadcrumb = self.page.locator(common.nav_breadcrumb)
        if breadcrumb.count() > 0:
            return breadcrumb.inner_text()
        return ""

    def get_page_title(self) -> str:
        """Get the page title.

        Returns:
            Page title text
        """
        title_selectors = [common.page_title, "h1", ".page-title", "title"]
        for selector in title_selectors:
            try:
                locator = self.page.locator(selector).first
                if locator.count() > 0:
                    return locator.inner_text().strip()
            except Exception:
                continue
        return ""

    # Link Detection Methods

    def get_all_links(self) -> list[dict]:
        """Get all links on the page.

        Returns:
            List of dictionaries with link info (text, href)
        """
        links = self.page.locator("a").all()
        result = []

        for link in links:
            try:
                href = link.get_attribute("href") or ""
                text = link.inner_text().strip()
                if href or text:
                    result.append({"text": text, "href": href})
            except Exception:
                continue

        return result

    def get_broken_links(self) -> list[dict]:
        """Check all links and return potentially broken ones.

        Returns:
            List of potentially broken links
        """
        links = self.get_all_links()
        broken = []

        for link in links:
            href = link.get("href", "")
            # Check for common broken link patterns
            if (
                href.startswith("javascript:") or
                href == "#" or
                "undefined" in href or
                href.startswith("mailto:") and "@" not in href
            ):
                broken.append(link)

        return broken

    # Table Methods

    def get_table_data(self, selector: str = "table") -> list[list[str]]:
        """Get data from a table.

        Args:
            selector: CSS selector for the table

        Returns:
            2D list of table cell text
        """
        table = self.page.locator(selector)
        if table.count() == 0:
            return []

        rows = table.locator("tr").all()
        data = []

        for row in rows:
            cells = row.locator("td, th").all()
            row_data = [cell.inner_text().strip() for cell in cells]
            data.append(row_data)

        return data

    def get_table_row_count(self, selector: str = "table") -> int:
        """Get the number of rows in a table.

        Args:
            selector: CSS selector for the table

        Returns:
            Number of rows (excluding header)
        """
        table = self.page.locator(selector)
        if table.count() == 0:
            return 0

        # Count data rows (excluding thead)
        rows = table.locator("tbody tr").all()
        if rows:
            return len(rows)

        # Fallback to all tr elements minus header
        all_rows = table.locator("tr").all()
        return max(0, len(all_rows) - 1)

    # Assertion Methods

    def assert_url_contains(self, text: str) -> None:
        """Assert that current URL contains text.

        Args:
            text: Text to check for in URL
        """
        expect(self.page).to_have_url(f"**/{text}**")

    def assert_url_equals(self, url: str) -> None:
        """Assert that current URL equals expected.

        Args:
            url: Expected URL
        """
        expect(self.page).to_have_url(url)

    def assert_element_visible(self, selector: str) -> None:
        """Assert that an element is visible.

        Args:
            selector: CSS selector for the element
        """
        expect(self.page.locator(selector)).to_be_visible()

    def assert_element_contains_text(self, selector: str, text: str) -> None:
        """Assert that an element contains text.

        Args:
            selector: CSS selector for the element
            text: Expected text content
        """
        expect(self.page.locator(selector)).to_contain_text(text)

    def assert_element_count(self, selector: str, count: int) -> None:
        """Assert that a selector matches exactly N elements.

        Args:
            selector: CSS selector
            count: Expected element count
        """
        expect(self.page.locator(selector)).to_have_count(count)

    def assert_not_admin_page(self) -> None:
        """Assert that current page is NOT a Django Admin page."""
        assert not self.is_admin_page(), f"Page is an Admin page: {self.page.url}"

    def assert_no_admin_branding(self) -> None:
        """Assert that page does not have Django Admin branding."""
        assert not self.has_admin_branding(), "Django Admin branding detected on page"
