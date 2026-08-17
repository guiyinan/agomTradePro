"""Focused contract tests for the TUI screen-patch production boundary."""

from __future__ import annotations

from typing import Any

from scripts.check_tui_metadata_source_consistency import (
    check_tui_metadata_source_consistency,
)


def _screen(key: str) -> dict[str, Any]:
    """Return a minimal IA-owned screen projection."""

    return {
        "key": key,
        "label": key,
        "summary": "Summary",
        "user_experience": {"primary_task": "Task", "primary_outcome": "Outcome"},
        "business_context": {},
        "audience": "authenticated",
        "view_type": "detail",
        "group": "group",
        "module_key": "module",
        "default_action_key": "",
        "dashboard_panels": [],
    }


def test_patch_boundary_reports_filtered_and_unmapped_keys_without_mutation() -> None:
    """Full IA loads filter published patches; unknown keys stay explicit."""

    published_screen = _screen("published")
    runtime_screen = _screen("runtime")
    published_payload = {
        "ia_version": "test",
        "screens": [published_screen],
        "actions": [],
    }
    ia_payload = {
        "version": "test",
        "published_screens": [published_screen],
        "runtime_screens": [runtime_screen],
    }
    runtime_payload = {"screens": [published_screen, runtime_screen], "actions": []}

    report = check_tui_metadata_source_consistency(
        published_payload=published_payload,
        ia_payload=ia_payload,
        runtime_payload=runtime_payload,
        runtime_screen_patch_keys=("legacy-screen", "published", "published"),
    )

    assert report.patch_boundary.configured_keys == ("legacy-screen", "published")
    assert report.patch_boundary.ignored_on_full_ia_payload == ("published",)
    assert report.patch_boundary.not_in_ia_registry == ("legacy-screen",)
