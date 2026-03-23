"""Capture README screenshots for key product surfaces."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


BASE_URL = os.environ.get("AGOM_BASE_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("AGOM_USERNAME", "admin")
PASSWORD = os.environ.get("AGOM_PASSWORD", "Aa123456")
OUTPUT_DIR = Path("docs/images/readme")


def login(page: Page) -> None:
    page.goto(f"{BASE_URL}/account/login/", wait_until="networkidle")
    page.locator('input[name="username"]').fill(USERNAME)
    page.locator('input[name="password"]').fill(PASSWORD)
    with page.expect_navigation(wait_until="networkidle"):
        page.locator('button[type="submit"]').click()


def login_if_needed(page: Page) -> None:
    if "/account/login/" in page.url:
        login(page)


def capture_setup_wizard(page: Page) -> None:
    page.goto(f"{BASE_URL}/setup/", wait_until="networkidle")
    auth_password = page.locator('input[name="password"]')
    if auth_password.count():
        auth_password.fill(PASSWORD)
        with page.expect_navigation(wait_until="networkidle"):
            page.locator('button[type="submit"]').click()

    page.set_viewport_size({"width": 1520, "height": 1180})
    page.screenshot(path=str(OUTPUT_DIR / "setup_wizard.png"), full_page=False)


def capture_terminal(page: Page) -> None:
    page.goto(f"{BASE_URL}/terminal/", wait_until="networkidle")
    login_if_needed(page)
    page.goto(f"{BASE_URL}/terminal/", wait_until="networkidle")

    terminal_input = page.locator("#terminal-input")
    terminal_input.click()
    terminal_input.fill("/status")
    terminal_input.press("Enter")
    page.wait_for_timeout(1500)
    terminal_input.fill("/regime")
    terminal_input.press("Enter")
    page.wait_for_timeout(1500)

    page.set_viewport_size({"width": 1680, "height": 1100})
    page.screenshot(path=str(OUTPUT_DIR / "terminal_cli.png"), full_page=False)


def capture_mcp_tools(page: Page) -> None:
    page.goto(f"{BASE_URL}/ops/mcp-tools/", wait_until="networkidle")
    login_if_needed(page)
    page.goto(f"{BASE_URL}/ops/mcp-tools/", wait_until="networkidle")
    page.set_viewport_size({"width": 1680, "height": 1180})
    page.screenshot(path=str(OUTPUT_DIR / "mcp_tools.png"), full_page=False)


def capture_dashboard(page: Page) -> None:
    page.goto(f"{BASE_URL}/dashboard/", wait_until="networkidle")
    login_if_needed(page)
    page.goto(f"{BASE_URL}/dashboard/", wait_until="networkidle")
    page.set_viewport_size({"width": 1680, "height": 1400})
    page.screenshot(path=str(OUTPUT_DIR / "dashboard_logged_in.png"), full_page=False)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1100})

        try:
            capture_setup_wizard(page)
            capture_dashboard(page)
            capture_terminal(page)
            capture_mcp_tools(page)
            print(f"Saved screenshots to {OUTPUT_DIR.resolve()}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
