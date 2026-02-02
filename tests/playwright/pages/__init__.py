"""
Pages package for Playwright tests.
"""
from tests.playwright.pages.base_page import BasePage
from tests.playwright.pages.auth.login_page import LoginPage
from tests.playwright.pages.admin.admin_page import AdminPage
from tests.playwright.pages.dashboard.dashboard_page import DashboardPage
from tests.playwright.pages.macro.macro_page import MacroPage
from tests.playwright.pages.regime.regime_page import RegimePage
from tests.playwright.pages.signal.signal_page import SignalPage


__all__ = [
    "BasePage",
    "LoginPage",
    "AdminPage",
    "DashboardPage",
    "MacroPage",
    "RegimePage",
    "SignalPage",
]
