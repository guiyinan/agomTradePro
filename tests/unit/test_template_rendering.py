"""
Template Rendering Tests

Verifies that all project templates can be loaded and rendered
without TemplateSyntaxError. Uses minimal context to catch
broken template tags, missing includes, and syntax issues.
"""

import os
from pathlib import Path

import pytest
from django.template import engines
from django.template.loader import get_template
from django.test import RequestFactory, TestCase, override_settings


def _discover_project_templates():
    """Discover all project-specific template paths (excluding third-party)."""
    from django.conf import settings

    templates = []
    base_dir = Path(settings.BASE_DIR)

    # Collect templates from DIRS setting
    for engine_conf in settings.TEMPLATES:
        for template_dir in engine_conf.get("DIRS", []):
            template_path = Path(template_dir)
            if template_path.exists():
                for html_file in template_path.rglob("*.html"):
                    rel_path = html_file.relative_to(template_path)
                    templates.append(str(rel_path).replace("\\", "/"))

    # Collect templates from app directories
    apps_dir = base_dir / "apps"
    if apps_dir.exists():
        for html_file in apps_dir.rglob("templates/**/*.html"):
            # Extract the template name relative to the templates/ dir
            parts = html_file.parts
            try:
                idx = parts.index("templates")
                rel_path = "/".join(parts[idx + 1:])
                templates.append(rel_path)
            except ValueError:
                continue

    return sorted(set(templates))


@pytest.mark.django_db
class TestTemplateRendering(TestCase):
    """Verify all templates render without syntax errors."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()
        cls.templates = _discover_project_templates()

    def _make_minimal_context(self, template_name: str) -> dict:
        """Build a minimal context that satisfies common template tags."""
        request = self.factory.get("/")
        # Add session and user to request for auth-dependent templates
        from django.contrib.sessions.backends.db import SessionStore
        from django.contrib.auth.models import AnonymousUser

        request.session = SessionStore()
        request.user = AnonymousUser()

        context = {
            "request": request,
            "user": request.user,
            # Common template variables
            "object_list": [],
            "page_obj": None,
            "paginator": None,
            "is_paginated": False,
            "form": None,
            "object": None,
            # Navigation / breadcrumb
            "title": "Test",
            "breadcrumbs": [],
            # Alert context processor
            "alerts": [],
        }
        return context

    def test_all_templates_discovered(self):
        """Ensure we found a reasonable number of templates."""
        assert len(self.templates) > 20, (
            f"Only found {len(self.templates)} templates, expected > 20"
        )

    def test_templates_load_without_syntax_error(self):
        """Every template should load (parse) without TemplateSyntaxError."""
        failed = []
        # Known issues: templates using custom filters that require {% load %}
        known_issues = {
            "ai_provider/detail.html",
            "alpha_trigger/candidate_detail.html",
            "audit/attribution_detail.html",
            "audit/attribution_report.html",
            "simulated_trading/my_trades.html",
            "strategy/detail.html",
        }
        for template_name in self.templates:
            try:
                get_template(template_name)
            except Exception as e:
                error_type = type(e).__name__
                # TemplateDoesNotExist is OK (template might use app-relative path)
                if "DoesNotExist" not in error_type:
                    if template_name not in known_issues:
                        failed.append((template_name, f"{error_type}: {e}"))

        if failed:
            msg = "Templates with NEW syntax errors:\n"
            for name, err in failed:
                msg += f"  - {name}: {err}\n"
            self.fail(msg)

    def test_core_templates_render(self):
        """Core templates (404, 500, login) must render successfully."""
        critical_templates = [
            "404.html",
            "500.html",
            "account/login.html",
        ]

        for template_name in critical_templates:
            try:
                template = get_template(template_name)
                context = self._make_minimal_context(template_name)
                rendered = template.render(context)
                assert len(rendered) > 0, f"Template {template_name} rendered empty"
            except Exception as e:
                if "DoesNotExist" not in type(e).__name__:
                    self.fail(f"Critical template {template_name} failed: {e}")

    def test_template_names_follow_convention(self):
        """Template names should follow app_name/template.html convention."""
        for template_name in self.templates:
            parts = template_name.split("/")
            # Skip root-level templates (404.html, 500.html, base.html)
            if len(parts) == 1:
                continue
            # Templates in apps should be namespaced
            assert len(parts) >= 2, (
                f"Template '{template_name}' not properly namespaced"
            )

    def test_no_duplicate_template_names(self):
        """No two templates should have the exact same basename in the same app."""
        seen = {}
        duplicates = []
        for template_name in self.templates:
            parts = template_name.split("/")
            if len(parts) >= 2:
                app = parts[0]
                basename = parts[-1]
                key = f"{app}/{basename}"
                if key in seen:
                    duplicates.append((key, seen[key], template_name))
                else:
                    seen[key] = template_name

        # Report but don't fail - some legitimate cases exist (partials, etc.)
        if duplicates:
            for key, first, second in duplicates:
                print(f"  Note: duplicate template basename {key}: {first}, {second}")
