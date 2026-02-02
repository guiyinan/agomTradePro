"""Config package for Playwright tests."""
from tests.playwright.config.test_config import config, TestConfig
from tests.playwright.config.selectors import (
    common,
    auth,
    dashboard,
    admin,
    modal,
    CommonSelectors,
    AuthSelectors,
    DashboardSelectors,
    AdminSelectors,
    ModalSelectors,
)

__all__ = [
    "config",
    "TestConfig",
    "common",
    "auth",
    "dashboard",
    "admin",
    "modal",
    "CommonSelectors",
    "AuthSelectors",
    "DashboardSelectors",
    "AdminSelectors",
    "ModalSelectors",
]
