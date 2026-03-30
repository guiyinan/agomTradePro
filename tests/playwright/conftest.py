"""
Global fixtures for Playwright tests.
"""
from collections.abc import Generator
from pathlib import Path
from typing import Optional

import pytest
import requests
from playwright.sync_api import Browser, BrowserContext, Page

from tests.playwright.config.test_config import config
from tests.playwright.pages import AdminPage, DashboardPage, LoginPage
from tests.playwright.utils.screenshot_utils import ScreenshotUtils
from tests.playwright.utils.ux_auditor import UXAuditor


def pytest_addoption(parser):
    """Add custom pytest options."""
    # Note: --base-url, --headed, --slowmo are provided by pytest-playwright
    # We only add custom options
    parser.addoption(
        "--screenshot-on-failure",
        action="store_true",
        default=True,
        help="Take screenshot on test failure",
    )


@pytest.fixture(scope="session")
def base_url(base_url: str) -> str:
    """Get base URL from command line or config.
    Uses pytest-base-url's base_url fixture with fallback to config.
    """
    return base_url or config.base_url


@pytest.fixture(scope="session", autouse=True)
def apply_runtime_test_config(base_url: str) -> None:
    """Keep the global Playwright config aligned with the resolved runtime base URL."""
    runtime_admin_url = f"{base_url.rstrip('/')}/admin"
    object.__setattr__(config, "base_url", base_url.rstrip("/"))
    object.__setattr__(config, "admin_url", runtime_admin_url)


@pytest.fixture(scope="session", autouse=True)
def ensure_playwright_admin_user(django_db_setup, django_db_blocker) -> None:
    """Ensure Playwright login credentials exist in the app database."""
    with django_db_blocker.unblock():
        from django.contrib.auth import get_user_model
        from django.db import IntegrityError

        user_model = get_user_model()
        user = user_model.objects.filter(username=config.admin_username).first()

        if user is None:
            try:
                user = user_model.objects.create_user(
                    username=config.admin_username,
                    password=config.admin_password,
                    is_staff=True,
                    is_superuser=True,
                    is_active=True,
                )
            except IntegrityError:
                # Another setup path may have created the user after the existence check.
                user = user_model.objects.get(username=config.admin_username)
        else:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
        user.set_password(config.admin_password)
        user.save(update_fields=["password", "is_staff", "is_superuser", "is_active"])


@pytest.fixture(scope="session", autouse=True)
def require_live_server(base_url: str) -> None:
    """Skip Playwright suite when the target app server is not reachable."""
    try:
        response = requests.get(f"{base_url}/account/login/", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"Playwright tests require a live app server at {base_url}: {exc}")


@pytest.fixture(scope="session")
def slowmo(browser_type_launch_args: dict) -> int:
    """Get slowmo delay in milliseconds."""
    return browser_type_launch_args.get("slow_mo", 0)


@pytest.fixture(scope="function")
def page(browser: Browser, base_url: str) -> Generator[Page, None, None]:
    """Create a new page for each test."""
    context = browser.new_context(
        viewport={"width": config.viewport_width, "height": config.viewport_height},
        base_url=base_url,
    )
    page = context.new_page()

    # Set default timeout
    page.set_default_timeout(config.default_timeout)

    yield page

    # Cleanup
    context.close()


@pytest.fixture(scope="function")
def login_page(page: Page, base_url: str) -> LoginPage:
    """Create a LoginPage instance."""
    return LoginPage(page, base_url)


@pytest.fixture(scope="function")
def dashboard_page(page: Page, base_url: str) -> DashboardPage:
    """Create a DashboardPage instance."""
    return DashboardPage(page, base_url)


@pytest.fixture(scope="function")
def admin_page(page: Page, base_url: str) -> AdminPage:
    """Create an AdminPage instance."""
    return AdminPage(page, base_url)


@pytest.fixture(scope="function")
def screenshot_utils() -> ScreenshotUtils:
    """Create a ScreenshotUtils instance."""
    return ScreenshotUtils()


@pytest.fixture(scope="function")
def ux_auditor_instance() -> UXAuditor:
    """Create a UXAuditor instance for each test."""
    auditor = UXAuditor()
    yield auditor
    # Reset after test
    auditor.reset()


@pytest.fixture(scope="function")
def authenticated_page(page: Page, base_url: str) -> Generator[Page, None, None]:
    """Create an authenticated page for tests requiring login.

    Logs in as admin user before yielding the page.
    """
    login = LoginPage(page, base_url)

    # Navigate to login
    login.goto()

    # Perform login
    login.login_as_admin()

    # Wait for navigation after login
    page.wait_for_load_state("networkidle")

    yield page

    # Optional: Logout after test
    # logout_url = f"{base_url}/account/logout/"
    # page.goto(logout_url)


@pytest.fixture(scope="function")
def authenticated_dashboard(authenticated_page: Page, base_url: str) -> DashboardPage:
    """Create a DashboardPage instance with authenticated user."""
    return DashboardPage(authenticated_page, base_url)


@pytest.fixture(scope="function", autouse=True)
def screenshot_on_failure(request, page: Page):
    """Take screenshot on test failure."""
    yield

    if request.node.rep_call.failed and request.config.getoption("--screenshot-on-failure"):
        # Create screenshot directory if needed
        screenshot_dir = Path(config.screenshot_dir) / "errors"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        test_name = request.node.name.replace(" ", "_").replace("/", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"failure_{test_name}_{timestamp}.png"
        filepath = screenshot_dir / filename

        # Take screenshot
        page.screenshot(path=str(filepath), full_page=True)
        print(f"\nScreenshot saved to: {filepath}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Make test result available to fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(scope="session")
def test_data_path():
    """Get path to test data directory."""
    return Path(__file__).parent / "data"


# Clean up imports
from datetime import datetime
