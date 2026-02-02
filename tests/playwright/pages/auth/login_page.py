"""
Login page object for authentication testing.
"""
import re
from playwright.sync_api import Page, expect

from tests.playwright.pages.base_page import BasePage
from tests.playwright.config.test_config import config
from tests.playwright.config.selectors import auth


class LoginPage(BasePage):
    """Page object for the login page."""

    def __init__(self, page: Page, base_url: str = None):
        """Initialize login page.

        Args:
            page: Playwright page object
            base_url: Base URL for the application
        """
        super().__init__(page, base_url)
        self.url_path = config.login_url

    # Navigation

    def goto(self) -> None:
        """Navigate to the login page."""
        self.navigate(self.url_path)

    # Element Access

    def get_username_input(self):
        """Get the username input element."""
        return self.page.locator(auth.username_input).first

    def get_password_input(self):
        """Get the password input element."""
        return self.page.locator(auth.password_input).first

    def get_login_button(self):
        """Get the login button element."""
        return self.page.locator(auth.login_btn).first

    def get_remember_me_checkbox(self):
        """Get the remember me checkbox element."""
        return self.page.locator(auth.remember_me).first

    def get_register_link(self):
        """Get the register page link."""
        return self.page.locator('a:has-text("注册"), a:has-text("Register"), a[href*="register"]').first

    def get_forgot_password_link(self):
        """Get the forgot password link."""
        return self.page.locator('a:has-text("忘记密码"), a:has-text("Forgot")').first

    # Actions

    def login(self, username: str, password: str, remember_me: bool = False) -> None:
        """Perform login action.

        Args:
            username: Username or email
            password: Password
            remember_me: Whether to check remember me checkbox
        """
        self.fill(auth.username_input, username)
        self.fill(auth.password_input, password)

        if remember_me:
            self.check(auth.remember_me)

        self.click(auth.login_btn)

    def login_as_admin(self) -> None:
        """Login as admin user."""
        self.login(config.admin_username, config.admin_password)

    def go_to_register(self) -> None:
        """Navigate to the registration page."""
        self.get_register_link().click()

    # Assertions

    def assert_on_login_page(self) -> None:
        """Assert that we are on the login page."""
        expect(self.page).to_have_url(re.compile(r".*/account/login/.*"))

    def assert_login_success(self) -> None:
        """Assert that login was successful."""
        # Should redirect away from login page
        expect(self.page).not_to_have_url(re.compile(r".*/account/login/.*"))

    def assert_login_failed(self) -> None:
        """Assert that login failed."""
        # Should still be on login page
        expect(self.page).to_have_url(re.compile(r".*/account/login/.*"))

    def assert_has_error_message(self) -> None:
        """Assert that an error message is displayed."""
        error_selectors = [
            ".alert-danger",
            ".error",
            ".alert-error",
            ".invalid-feedback",
            "text=用户名或密码错误",
            "text=Invalid",
            "text=错误",
        ]
        found = False
        for selector in error_selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    found = True
                    break
            except Exception:
                continue
        assert found, "No error message found on login page"

    def assert_no_admin_exposure(self) -> None:
        """Assert that login page doesn't expose admin links."""
        admin_links = self.page.locator('a[href*="/admin/"]')
        assert admin_links.count() == 0, "Admin links found on login page"

    def assert_not_django_admin_login(self) -> None:
        """Assert this is not the Django Admin login page."""
        django_admin_selectors = [
            "#site-name:has-text('Django')",
            "text=Django administration",
            ".errornote",
        ]
        for selector in django_admin_selectors:
            try:
                assert self.page.locator(selector).count() == 0, "Django Admin elements detected"
            except Exception:
                continue
