"""
Screenshot utility functions for Playwright tests.
Provides consistent screenshot capture and naming conventions.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from tests.playwright.config.test_config import config


class ScreenshotUtils:
    """Utility class for taking and managing screenshots."""

    def __init__(self, base_dir: str | None = None):
        """Initialize screenshot utilities.

        Args:
            base_dir: Base directory for screenshots. Defaults to config.screenshot_dir
        """
        self.base_dir = Path(base_dir or config.screenshot_dir)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create necessary screenshot directories."""
        directories = [
            self.base_dir / "baseline",
            self.base_dir / "ux_audit",
            self.base_dir / "flows",
            self.base_dir / "errors",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def capture_baseline(
        self,
        page: Page,
        name: str,
        module: str = "general",
        full_page: bool = True,
    ) -> str:
        """Capture a baseline screenshot of a page.

        Args:
            page: Playwright page object
            name: Screenshot name (without extension)
            module: Module name for organization
            full_page: Whether to capture full page or viewport only

        Returns:
            Path to the saved screenshot
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = self.base_dir / "baseline" / module / filename

        filepath.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(filepath), full_page=full_page)

        return str(filepath)

    def capture_ux_issue(
        self,
        page: Page,
        issue_id: str,
        state: str = "before",
        description: str | None = None,
    ) -> str:
        """Capture a screenshot for a UX issue.

        Args:
            page: Playwright page object
            issue_id: Unique issue identifier
            state: "before" or "after" fix
            description: Optional description to include in filename

        Returns:
            Path to the saved screenshot
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        desc_suffix = f"_{description}" if description else ""
        filename = f"{issue_id}_{state}{desc_suffix}_{timestamp}.png"
        filepath = self.base_dir / "ux_audit" / filename

        page.screenshot(path=str(filepath), full_page=True)

        return str(filepath)

    def capture_flow_step(
        self,
        page: Page,
        flow_name: str,
        step_number: int,
        step_description: str | None = None,
    ) -> str:
        """Capture a screenshot for a step in a user flow.

        Args:
            page: Playwright page object
            flow_name: Name of the user flow
            step_number: Step number in the flow
            step_description: Optional step description

        Returns:
            Path to the saved screenshot
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        desc_suffix = f"_{step_description}" if step_description else ""
        filename = f"{flow_name}_step_{step_number:02d}{desc_suffix}_{timestamp}.png"
        filepath = self.base_dir / "flows" / filename

        page.screenshot(path=str(filepath), full_page=True)

        return str(filepath)

    def capture_error(
        self,
        page: Page,
        test_name: str,
        error_message: str | None = None,
    ) -> str:
        """Capture a screenshot when an error occurs.

        Args:
            page: Playwright page object
            test_name: Name of the test that failed
            error_message: Optional error message

        Returns:
            Path to the saved screenshot
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_suffix = f"_{error_message[:50]}" if error_message else ""
        filename = f"error_{test_name}{error_suffix}_{timestamp}.png"
        filepath = self.base_dir / "errors" / filename

        page.screenshot(path=str(filepath), full_page=True)

        return str(filepath)

    def capture_all_links(
        self,
        page: Page,
        module: str,
        link_selector: str = "a",
    ) -> list[str]:
        """Capture screenshots of all links on a page.

        Args:
            page: Playwright page object
            module: Module name for organization
            link_selector: CSS selector for links

        Returns:
            List of paths to captured screenshots
        """
        screenshots = []
        links = page.locator(link_selector).all()

        for i, link in enumerate(links):
            try:
                # Get link text and href
                text = link.inner_text() or f"link_{i}"
                href = link.get_attribute("href") or "no_href"
                href_clean = href.replace("/", "_").replace(":", "_")[:50]

                # Hover over link and capture
                link.hover()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"link_{i:02d}_{href_clean}_{timestamp}.png"
                filepath = self.base_dir / "baseline" / module / filename

                page.screenshot(path=str(filepath), full_page=False)
                screenshots.append(str(filepath))

            except Exception:
                continue

        return screenshots

    def get_baseline_path(self, module: str = "") -> str:
        """Get the path to baseline screenshots.

        Args:
            module: Optional module name for subdirectory

        Returns:
            Path to baseline screenshot directory
        """
        if module:
            return str(self.base_dir / "baseline" / module)
        return str(self.base_dir / "baseline")

    def get_ux_audit_path(self) -> str:
        """Get the path to UX audit screenshots.

        Returns:
            Path to UX audit screenshot directory
        """
        return str(self.base_dir / "ux_audit")

    def get_flows_path(self) -> str:
        """Get the path to flow screenshots.

        Returns:
            Path to flow screenshot directory
        """
        return str(self.base_dir / "flows")


# Global screenshot utility instance
screenshot = ScreenshotUtils()
