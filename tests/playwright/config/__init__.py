"""Config package for Playwright tests."""
from tests.playwright.config.selectors import (
    AdminSelectors,
    AuthSelectors,
    CommonSelectors,
    DashboardSelectors,
    ModalSelectors,
    admin,
    auth,
    common,
    dashboard,
    modal,
)
from tests.playwright.config.test_config import TestConfig, config

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
