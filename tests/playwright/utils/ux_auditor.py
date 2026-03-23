"""
UX Auditor - Automated UX issue detection for Playwright tests.
Identifies common UX problems like Admin exposure, missing modals, etc.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import Page

from tests.playwright.config.selectors import admin, common, modal
from tests.playwright.utils.screenshot_utils import ScreenshotUtils


class Severity(Enum):
    """UX issue severity levels."""
    CRITICAL = "critical"  # Blocks user, needs immediate fix
    HIGH = "high"  # Major UX problem
    MEDIUM = "medium"  # Moderate UX problem
    LOW = "low"  # Minor improvement opportunity


@dataclass
class UXIssue:
    """Represents a UX issue found during testing."""
    issue_id: str
    category: str  # e.g., "navigation", "admin", "modal", "form"
    severity: Severity
    title: str
    description: str
    url: str
    evidence: str  # What was observed
    screenshot_path: str | None = None
    recommendation: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class UXAuditor:
    """Automated UX issue detector."""

    def __init__(self, screenshot_utils: ScreenshotUtils | None = None):
        """Initialize UX auditor.

        Args:
            screenshot_utils: Screenshot utility instance
        """
        self.screenshot = screenshot_utils or ScreenshotUtils()
        self.issues: list[UXIssue] = []

    def reset(self) -> None:
        """Clear all recorded issues."""
        self.issues = []

    def audit_page(self, page: Page, page_name: str) -> list[UXIssue]:
        """Perform a comprehensive UX audit on a page.

        Args:
            page: Playwright page object
            page_name: Name/identifier of the page

        Returns:
            List of UX issues found
        """
        url = page.url
        page_issues = []

        # Check for Admin exposure
        admin_issues = self._check_admin_exposure(page, url, page_name)
        page_issues.extend(admin_issues)

        # Check for navigation elements
        nav_issues = self._check_navigation(page, url, page_name)
        page_issues.extend(nav_issues)

        # Check for CRUD modal patterns
        modal_issues = self._check_crud_modals(page, url, page_name)
        page_issues.extend(modal_issues)

        # Check for loading indicators
        loading_issues = self._check_loading_indicators(page, url, page_name)
        page_issues.extend(loading_issues)

        # Check for form validation
        form_issues = self._check_form_validation(page, url, page_name)
        page_issues.extend(form_issues)

        # Check for responsive design
        responsive_issues = self._check_responsive_design(page, url, page_name)
        page_issues.extend(responsive_issues)

        self.issues.extend(page_issues)
        return page_issues

    def _check_admin_exposure(self, page: Page, url: str, page_name: str) -> list[UXIssue]:
        """Check for Django Admin exposure.

        Args:
            page: Playwright page object
            url: Current page URL
            page_name: Name of the page

        Returns:
            List of admin-related UX issues
        """
        issues = []

        # Check if URL contains /admin/
        if "/admin/" in url:
            screenshot_path = self.screenshot.capture_ux_issue(
                page,
                f"admin_url_{page_name}",
                description="admin_url_detected"
            )
            issues.append(UXIssue(
                issue_id=f"ADMIN_URL_{page_name.upper()}",
                category="admin",
                severity=Severity.HIGH,
                title="User directed to Django Admin interface",
                description="The page URL contains /admin/, indicating users are being directed to the Django Admin interface instead of a custom UI.",
                url=url,
                evidence=f"URL: {url}",
                screenshot_path=screenshot_path,
                recommendation="Create a custom user interface for this functionality instead of using Django Admin."
            ))

        # Check for Django branding elements
        has_django_branding = False
        branding_selectors = [
            admin.admin_branding,
            "text=Django administration",
            "text=Site administration",
            "#site-name:has-text('Django')",
        ]

        for selector in branding_selectors:
            try:
                if page.locator(selector).count() > 0:
                    has_django_branding = True
                    break
            except Exception:
                continue

        if has_django_branding:
            screenshot_path = self.screenshot.capture_ux_issue(
                page,
                f"admin_branding_{page_name}",
                description="django_branding_visible"
            )
            issues.append(UXIssue(
                issue_id=f"ADMIN_BRANDING_{page_name.upper()}",
                category="admin",
                severity=Severity.HIGH,
                title="Django Admin branding visible to users",
                description="Django administration branding is visible on the page, indicating users are seeing the Admin interface.",
                url=url,
                evidence="Django branding elements detected in DOM",
                screenshot_path=screenshot_path,
                recommendation="Replace Django Admin templates with custom branded templates."
            ))

        # Check for exposed Admin links
        admin_links = page.locator('a[href*="/admin/"]').all()
        if admin_links and "/admin/" not in url:
            screenshot_path = self.screenshot.capture_ux_issue(
                page,
                f"admin_link_{page_name}",
                description="admin_link_exposed"
            )
            link_count = len(admin_links)
            issues.append(UXIssue(
                issue_id=f"ADMIN_LINK_{page_name.upper()}",
                category="admin",
                severity=Severity.MEDIUM,
                title=f"Django Admin links exposed to users ({link_count} found)",
                description=f"Found {link_count} link(s) pointing to /admin/ on a non-admin page.",
                url=url,
                evidence=f"{link_count} links with href containing '/admin/'",
                screenshot_path=screenshot_path,
                recommendation="Remove Admin links or ensure they are only accessible to admin users."
            ))

        return issues

    def _check_navigation(self, page: Page, url: str, page_name: str) -> list[UXIssue]:
        """Check for navigation issues.

        Args:
            page: Playwright page object
            url: Current page URL
            page_name: Name of the page

        Returns:
            List of navigation-related UX issues
        """
        issues = []

        # Check for breadcrumb navigation
        has_breadcrumb = page.locator(common.nav_breadcrumb).count() > 0

        if not has_breadcrumb and url != f"{self._get_base_url(url)}/":
            issues.append(UXIssue(
                issue_id=f"NO_BREADCRUMB_{page_name.upper()}",
                category="navigation",
                severity=Severity.MEDIUM,
                title="Missing breadcrumb navigation",
                description="Page does not have breadcrumb navigation, making it difficult for users to understand their location in the site hierarchy.",
                url=url,
                evidence=f"No breadcrumb element found on page: {page_name}",
                recommendation="Add breadcrumb navigation to show user's current location."
            ))

        # Check for home link in navigation
        has_home_link = False
        home_selectors = [
            'a[href="/"]',
            'a[href="/dashboard/"]',
            'a:has-text("首页")',
            'a:has-text("Home")',
            'a:has-text("Dashboard")',
        ]

        for selector in home_selectors:
            try:
                if page.locator(selector).count() > 0:
                    has_home_link = True
                    break
            except Exception:
                continue

        if not has_home_link:
            issues.append(UXIssue(
                issue_id=f"NO_HOME_LINK_{page_name.upper()}",
                category="navigation",
                severity=Severity.HIGH,
                title="No way to return to home/dashboard",
                description="Page does not have a visible link to return to the home page or dashboard.",
                url=url,
                evidence="No home/dashboard link found in navigation",
                recommendation="Add a prominent home/dashboard link in the navigation."
            ))

        return issues

    def _check_crud_modals(self, page: Page, url: str, page_name: str) -> list[UXIssue]:
        """Check if CRUD operations use modals instead of page navigation.

        Args:
            page: Playwright page object
            url: Current page URL
            page_name: Name of the page

        Returns:
            List of modal-related UX issues
        """
        issues = []

        # Look for add/create/edit buttons
        crud_buttons = page.locator(common.btn_add).all()
        crud_buttons.extend(page.locator(common.btn_edit).all())

        if not crud_buttons:
            return issues

        # Check if clicking triggers a modal or navigation
        for i, button in enumerate(crud_buttons[:3]):  # Check first 3 buttons max
            try:
                button_text = button.inner_text() or f"button_{i}"

                # Check if button has data-toggle or data-target attributes (Bootstrap modal)
                has_modal_attr = (
                    button.get_attribute("data-toggle") == "modal" or
                    button.get_attribute("data-bs-toggle") == "modal" or
                    button.get_attribute("data-target") or
                    button.get_attribute("data-bs-target")
                )

                # Check if href navigates away
                href = button.get_attribute("href") or button.get_attribute("data-url") or ""
                navigates_away = href and not href.startswith("#")

                if navigates_away and not has_modal_attr:
                    issues.append(UXIssue(
                        issue_id=f"NO_MODAL_{page_name.upper()}_{i}",
                        category="modal",
                        severity=Severity.MEDIUM,
                        title="CRUD button navigates to new page instead of using modal",
                        description=f"The '{button_text}' button navigates to a new page ({href}) instead of opening a modal dialog.",
                        url=url,
                        evidence=f"Button href: {href}",
                        recommendation="Consider using a modal dialog for CRUD operations to maintain context and improve UX.",
                    ))
            except Exception:
                continue

        # Check for delete confirmation
        delete_buttons = page.locator(common.btn_delete).all()
        if delete_buttons:
            for i, btn in enumerate(delete_buttons[:3]):
                try:
                    has_confirm = (
                        btn.get_attribute("data-confirm") or
                        btn.get_attribute("onclick") and "confirm" in btn.get_attribute("onclick") or
                        btn.get_attribute("data-bs-toggle")
                    )

                    if not has_confirm:
                        issues.append(UXIssue(
                            issue_id=f"NO_DELETE_CONFIRM_{page_name.upper()}_{i}",
                            category="modal",
                            severity=Severity.MEDIUM,
                            title="Delete operation lacks confirmation dialog",
                            description="Delete button does not have a confirmation dialog, risking accidental deletions.",
                            url=url,
                            evidence="Delete button found without confirmation attribute",
                            recommendation="Add a confirmation dialog for delete operations.",
                        ))
                except Exception:
                    continue

        return issues

    def _check_loading_indicators(self, page: Page, url: str, page_name: str) -> list[UXIssue]:
        """Check for loading indicators.

        Args:
            page: Playwright page object
            url: Current page URL
            page_name: Name of the page

        Returns:
            List of loading-related UX issues
        """
        issues = []

        # This is a passive check - loading indicators should exist in the DOM
        # even if not currently visible
        has_loading = (
            page.locator(common.loading_indicator).count() > 0 or
            page.locator(common.loading_spinner).count() > 0
        )

        # Note: This is informational - some pages may not need loading indicators
        # So we mark as LOW severity
        if not has_loading:
            issues.append(UXIssue(
                issue_id=f"NO_LOADING_{page_name.upper()}",
                category="loading",
                severity=Severity.LOW,
                title="No loading indicator found in DOM",
                description="Page does not appear to have loading indicators for async operations.",
                url=url,
                evidence="No loading/spinner element found in DOM",
                recommendation="Consider adding loading indicators for better user feedback during async operations."
            ))

        return issues

    def _check_form_validation(self, page: Page, url: str, page_name: str) -> list[UXIssue]:
        """Check for form validation feedback.

        Args:
            page: Playwright page object
            url: Current page URL
            page_name: Name of the page

        Returns:
            List of form validation UX issues
        """
        issues = []

        # Look for forms
        forms = page.locator(common.form).all()

        for form in forms:
            try:
                # Check if form has error message elements
                form_html = form.inner_html()
                has_validation = (
                    "invalid-feedback" in form_html or
                    "error" in form_html or
                    "text-danger" in form_html or
                    "aria-invalid" in form_html or
                    "required" in form_html
                )

                if not has_validation:
                    issues.append(UXIssue(
                        issue_id=f"NO_FORM_VALIDATION_{page_name.upper()}",
                        category="form",
                        severity=Severity.LOW,
                        title="Form may lack client-side validation feedback",
                        description="Form does not appear to have visible validation error message elements.",
                        url=url,
                        evidence="Form found without standard validation classes",
                        recommendation="Add client-side validation with clear error messages for better UX.",
                    ))
                    break  # Only report once per page
            except Exception:
                continue

        return issues

    def _check_responsive_design(self, page: Page, url: str, page_name: str) -> list[UXIssue]:
        """Check for responsive design considerations.

        Args:
            page: Playwright page object
            url: Current page URL
            page_name: Name of the page

        Returns:
            List of responsive design UX issues
        """
        issues = []

        # Check for viewport meta tag
        viewport_meta = page.locator('meta[name="viewport"]').count() > 0

        if not viewport_meta:
            issues.append(UXIssue(
                issue_id=f"NO_VIEWPORT_{page_name.upper()}",
                category="responsive",
                severity=Severity.MEDIUM,
                title="Missing viewport meta tag for responsive design",
                description="Page does not have a viewport meta tag, which is essential for responsive design on mobile devices.",
                url=url,
                evidence="No meta[name='viewport'] tag found",
                recommendation='Add <meta name="viewport" content="width=device-width, initial-scale=1"> to the head.'
            ))

        return issues

    def _get_base_url(self, url: str) -> str:
        """Extract base URL from a full URL.

        Args:
            url: Full URL

        Returns:
            Base URL
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def get_issues_by_severity(self, severity: Severity) -> list[UXIssue]:
        """Get all issues of a specific severity.

        Args:
            severity: Severity level to filter by

        Returns:
            List of UX issues with the specified severity
        """
        return [issue for issue in self.issues if issue.severity == severity]

    def get_issues_by_category(self, category: str) -> list[UXIssue]:
        """Get all issues of a specific category.

        Args:
            category: Category to filter by

        Returns:
            List of UX issues in the specified category
        """
        return [issue for issue in self.issues if issue.category == category]

    def generate_report(self) -> dict:
        """Generate a summary report of all issues.

        Returns:
            Dictionary containing issue statistics and details
        """
        total = len(self.issues)
        by_severity = {
            "critical": len([i for i in self.issues if i.severity == Severity.CRITICAL]),
            "high": len([i for i in self.issues if i.severity == Severity.HIGH]),
            "medium": len([i for i in self.issues if i.severity == Severity.MEDIUM]),
            "low": len([i for i in self.issues if i.severity == Severity.LOW]),
        }
        by_category = {}

        for issue in self.issues:
            if issue.category not in by_category:
                by_category[issue.category] = 0
            by_category[issue.category] += 1

        return {
            "total_issues": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "issues": [
                {
                    "id": issue.issue_id,
                    "category": issue.category,
                    "severity": issue.severity.value,
                    "title": issue.title,
                    "description": issue.description,
                    "url": issue.url,
                    "recommendation": issue.recommendation,
                    "screenshot": issue.screenshot_path,
                }
                for issue in self.issues
            ],
        }

    def save_markdown_report(self, filepath: str) -> None:
        """Save a markdown report of UX issues.

        Args:
            filepath: Path to save the markdown report
        """
        report = self.generate_report()

        md_content = f"""# UX Audit Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary

- **Total Issues:** {report['total_issues']}
- **Critical:** {report['by_severity']['critical']}
- **High:** {report['by_severity']['high']}
- **Medium:** {report['by_severity']['medium']}
- **Low:** {report['by_severity']['low']}

## Issues by Category

"""

        for category, count in report['by_category'].items():
            md_content += f"- **{category.title()}:** {count}\n"

        md_content += "\n## Detailed Issues\n\n"

        # Group by severity
        for severity in ["critical", "high", "medium", "low"]:
            severity_issues = [i for i in report['issues'] if i['severity'] == severity]
            if severity_issues:
                md_content += f"### {severity.title()} Priority\n\n"
                for issue in severity_issues:
                    md_content += f"#### {issue['id']}\n"
                    md_content += f"**Title:** {issue['title']}\n\n"
                    md_content += f"**Category:** {issue['category']}\n\n"
                    md_content += f"**Description:** {issue['description']}\n\n"
                    md_content += f"**URL:** {issue['url']}\n\n"
                    if issue['screenshot']:
                        md_content += f"**Screenshot:** `{issue['screenshot']}`\n\n"
                    md_content += f"**Recommendation:** {issue['recommendation']}\n\n"
                    md_content += "---\n\n"

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        Path(filepath).write_text(md_content, encoding="utf-8")


# Global UX auditor instance
ux_auditor = UXAuditor()
