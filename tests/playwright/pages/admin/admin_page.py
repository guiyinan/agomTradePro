"""
Admin page object for detecting Django Admin exposure.
"""
from typing import List, Optional
from playwright.sync_api import Page, expect

from tests.playwright.pages.base_page import BasePage
from tests.playwright.config.test_config import config
from tests.playwright.config.selectors import admin as admin_sel, common


class AdminPage(BasePage):
    """Page object for detecting and analyzing Django Admin pages."""

    def __init__(self, page: Page, base_url: str = None):
        """Initialize admin page detector.

        Args:
            page: Playwright page object
            base_url: Base URL for the application
        """
        super().__init__(page, base_url)

    # Detection Methods

    def is_django_admin_page(self) -> bool:
        """Check if current page is a Django Admin page.

        Returns:
            True if this is a Django Admin page
        """
        # Check URL
        if "/admin/" in self.page.url:
            return True

        # Check for Django Admin specific elements
        admin_indicators = [
            common.admin_branding,
            common.admin_logo,
            "text=Django administration",
            "#site-name:has-text('Django')",
            ".breadcrumbs",
            "#user-tools",
        ]

        for indicator in admin_indicators:
            try:
                if self.page.locator(indicator).count() > 0:
                    return True
            except Exception:
                continue

        return False

    def is_django_admin_login(self) -> bool:
        """Check if current page is Django Admin login.

        Returns:
            True if this is Django Admin login page
        """
        if "/admin/login/" in self.page.url:
            return True

        login_indicators = [
            "#login-form",
            ".errornote",
            "text=Please login",
            "text=Django administration",
        ]

        for indicator in login_indicators:
            try:
                if self.page.locator(indicator).count() > 0:
                    return True
            except Exception:
                continue

        return False

    # Module Detection

    def get_admin_modules(self) -> List[dict]:
        """Get all Django Admin app modules on index page.

        Returns:
            List of module info (name, link)
        """
        modules = []
        module_elements = self.page.locator(admin_sel.admin_module).all()

        for i, module in enumerate(module_elements):
            try:
                name = module.inner_text() or f"Module {i}"
                link = module.locator("a").first
                href = link.get_attribute("href") if link.count() > 0 else ""
                modules.append({"name": name, "href": href})
            except Exception:
                continue

        return modules

    def get_admin_models(self, app_name: Optional[str] = None) -> List[dict]:
        """Get all Django Admin models on app page.

        Args:
            app_name: Optional app name to filter by

        Returns:
            List of model info (name, link, add_link, change_link)
        """
        models = []
        model_elements = self.page.locator(admin_sel.admin_model).all()

        for model in model_elements:
            try:
                name_el = model.locator("caption").first
                if name_el.count() == 0:
                    continue

                name = name_el.inner_text()
                if app_name and app_name not in name:
                    continue

                # Get change link
                change_link_el = model.locator("a.changelink").first
                change_link = change_link_el.get_attribute("href") if change_link_el.count() > 0 else ""

                # Get add link
                add_link_el = model.locator("a.addlink").first
                add_link = add_link_el.get_attribute("href") if add_link_el.count() > 0 else ""

                models.append({
                    "name": name,
                    "change_link": change_link,
                    "add_link": add_link,
                })
            except Exception:
                continue

        return models

    # Change List Detection

    def is_change_list_page(self) -> bool:
        """Check if current page is a Django Admin changelist page.

        Returns:
            True if changelist page
        """
        changelist_indicators = [
            admin_sel.changelist_table,
            "#changelist",
            ".changelist-page",
        ]

        for indicator in changelist_indicators:
            try:
                if self.page.locator(indicator).count() > 0:
                    return True
            except Exception:
                continue

        return False

    def get_changelist_items(self) -> List[dict]:
        """Get items from changelist table.

        Returns:
            List of row data
        """
        table = self.page.locator(admin_sel.changelist_table)
        if table.count() == 0:
            return []

        rows = table.locator("tr").all()
        items = []

        for row in rows:
            try:
                cells = row.locator("td, th").all()
                row_data = [cell.inner_text().strip() for cell in cells]
                if row_data:
                    items.append({"cells": row_data})
            except Exception:
                continue

        return items

    # Change Form Detection

    def is_change_form_page(self) -> bool:
        """Check if current page is a Django Admin change form page.

        Returns:
            True if change form page
        """
        form_indicators = [
            admin_sel.change_form,
            ".submit-row",
            "input[name='_save']",
        ]

        for indicator in form_indicators:
            try:
                if self.page.locator(indicator).count() > 0:
                    return True
            except Exception:
                continue

        return False

    def get_form_fields(self) -> List[dict]:
        """Get all form fields on change form page.

        Returns:
            List of field info (label, input_type, name)
        """
        fields = []
        form_rows = self.page.locator(".form-row, .aligned tr").all()

        for row in form_rows:
            try:
                label_el = row.locator("label").first
                input_el = row.locator("input, select, textarea").first

                if label_el.count() > 0 and input_el.count() > 0:
                    label = label_el.inner_text().strip()
                    input_type = input_el.get_attribute("type") or input_el.evaluate("el => el.tagName")
                    name = input_el.get_attribute("name") or ""

                    fields.append({
                        "label": label,
                        "input_type": input_type,
                        "name": name,
                    })
            except Exception:
                continue

        return fields

    # Analysis Methods

    def analyze_admin_exposure(self) -> dict:
        """Analyze the current page for Admin exposure.

        Returns:
            Dictionary with exposure analysis
        """
        return {
            "is_admin_page": self.is_django_admin_page(),
            "is_admin_login": self.is_django_admin_login(),
            "is_change_list": self.is_change_list_page(),
            "is_change_form": self.is_change_form_page(),
            "url": self.page.url,
            "has_admin_branding": self.has_admin_branding(),
            "admin_modules": self.get_admin_modules() if self.is_django_admin_page() else [],
            "admin_links": self.get_admin_links(),
        }

    def get_required_actions_for_custom_ui(self) -> List[str]:
        """Get list of actions that need custom UI implementation.

        Returns:
            List of required action descriptions
        """
        required = []

        if self.is_django_admin_page():
            if self.is_change_list_page():
                required.append("Create custom list view with filtering and pagination")
            if self.is_change_form_page():
                required.append("Create custom form with modal or dedicated page")
            if self.is_django_admin_login():
                required.append("Ensure custom authentication is used instead of Admin login")

            modules = self.get_admin_modules()
            for module in modules:
                required.append(f"Create custom UI for {module['name']} module")

        return required

    # Assertions

    def assert_not_admin_page(self) -> None:
        """Assert that current page is NOT a Django Admin page."""
        assert not self.is_django_admin_page(), (
            f"Page is a Django Admin page: {self.page.url}\n"
            "Users should not see Django Admin interface."
        )

    def assert_no_admin_links(self) -> None:
        """Assert that page has no links to Django Admin."""
        admin_links = self.get_admin_links()
        assert len(admin_links) == 0, (
            f"Found {len(admin_links)} admin link(s) on page: {admin_links}\n"
            "Admin links should not be exposed to regular users."
        )
