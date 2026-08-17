"""Machine checks for the TUI metadata source boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.check_tui_metadata_source_consistency import (
    check_tui_metadata_source_consistency,
    load_json_payload,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_PATH = ROOT / "config/tui/published/tui_operation_graph.published.json"
IA_PATH = ROOT / "config/tui/ia/tui_information_architecture.v1.json"


def _minimal_payload() -> dict[str, Any]:
    """Return a small source graph for violation tests."""

    screen = {
        "key": "published",
        "label": "Published",
        "summary": "Summary",
        "user_experience": {"primary_task": "Task", "primary_outcome": "Outcome"},
        "business_context": {},
        "audience": "authenticated",
        "view_type": "detail",
        "group": "daily",
        "module_key": "daily",
        "dashboard_panels": [],
    }
    return {
        "version": "test",
        "ia_version": "test",
        "groups": [],
        "modules": [],
        "screens": [screen],
        "actions": [],
    }


def test_real_tui_sources_have_consistent_published_screen_ownership() -> None:
    """The real static, IA, and normalized runtime sources agree."""

    pytest.importorskip("django")
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    published = load_json_payload(PUBLISHED_PATH)
    ia = load_json_payload(IA_PATH)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()

    report = check_tui_metadata_source_consistency(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert report.passed, report.as_json()
    assert report.published_screen_count == 12
    assert report.runtime_screen_count == 24
    assert report.published_action_count == 430
    assert report.runtime_action_count >= report.published_action_count


def test_retired_alias_screen_patch_is_not_registered_after_ia_cutover() -> None:
    """A legacy alias must resolve through IA, not a parallel screen patch."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen_keys = {str(screen["key"]) for screen in runtime["screens"]}

    assert aliases["command-center.auto-advisor"] == "command-center.decision-flow"
    assert "command-center.auto-advisor" not in RUNTIME_SCREEN_PATCHES
    assert "command-center.auto-advisor" not in runtime_screen_keys


def test_source_guard_rejects_runtime_replacement_of_ia_copy() -> None:
    """A runtime copy override must fail closed instead of being accepted."""

    ia = {
        "version": "test",
        "published_screens": [_minimal_payload()["screens"][0]],
        "runtime_screens": [],
    }
    published = _minimal_payload()
    runtime = _minimal_payload()
    runtime["screens"][0]["label"] = "Runtime override"

    report = check_tui_metadata_source_consistency(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert not report.passed
    assert [item.rule_id for item in report.violations] == ["runtime_screen_copy:published"]


def test_source_guard_requires_runtime_screen_default_action() -> None:
    """Runtime-only screens must expose the contract needed by the shell."""

    base = _minimal_payload()
    runtime_screen = {
        "key": "runtime",
        "label": "Runtime",
        "summary": "Runtime summary",
        "user_experience": {"primary_task": "Task", "primary_outcome": "Outcome"},
        "default_action_key": "",
    }
    ia = {
        "version": "test",
        "published_screens": [base["screens"][0]],
        "runtime_screens": [runtime_screen],
    }
    published = base
    runtime = dict(base)
    runtime["screens"] = [base["screens"][0], runtime_screen]

    report = check_tui_metadata_source_consistency(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert not report.passed
    assert report.violations[0].rule_id == "runtime_screen_contract:runtime"
