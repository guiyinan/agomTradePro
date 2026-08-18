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


def test_execution_audit_screen_patch_is_not_registered_after_ia_cutover() -> None:
    """The canonical audit screen owns its panels in the reviewed IA graph."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    audit = next(screen for screen in runtime["screens"] if screen["key"] == "execution.audit")

    assert aliases["execution.events"] == "execution.audit"
    assert aliases["execution.share"] == "execution.audit"
    assert "execution.audit" not in RUNTIME_SCREEN_PATCHES
    assert audit["summary"] == "查看审计健康、事件指标、实盘对账与操作记录。"
    assert [
        panel["action_key"] for panel in audit["dashboard_panels"] if panel.get("action_key")
    ] == [
        "auto.api.get.api.audit.health",
        "auto.api.get.api.events.metrics",
        "broker-execution.reconciliation-list",
        "broker-execution.audit-list",
    ]


def test_research_signals_screen_patch_removed_after_ia_cutover() -> None:
    """The canonical IA screen owns research.signals after patch removal."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    ia = load_json_payload(IA_PATH)
    research_signals = next(
        screen for screen in ia["published_screens"] if screen["key"] == "research.signals"
    )

    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "research.signals"
    )

    assert "research.signals" not in RUNTIME_SCREEN_PATCHES
    assert research_signals["label"] == "Beta 态势与 Alpha 选股"
    assert (
        research_signals["summary"] == "先判断市场是否允许参与，再查看 Alpha 选股清单、理由与约束。"
    )
    assert runtime_screen["label"] == research_signals["label"]
    assert runtime_screen["summary"] == research_signals["summary"]


def test_research_asset_lab_screen_patch_removed_after_ia_cutover() -> None:
    """The canonical asset research screen owns its panels after cutover."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    ia = load_json_payload(IA_PATH)
    asset_lab = next(
        screen for screen in ia["published_screens"] if screen["key"] == "research.asset-lab"
    )
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "research.asset-lab"
    )

    assert "research.asset-lab" not in RUNTIME_SCREEN_PATCHES
    for key in ("label", "summary", "view_type", "default_action_key", "user_experience"):
        assert runtime_screen[key] == asset_lab[key]
    assert [
        panel["action_key"]
        for panel in runtime_screen["dashboard_panels"]
        if panel.get("action_key")
    ] == [panel["action_key"] for panel in asset_lab["dashboard_panels"] if panel.get("action_key")]


def test_prompt_screen_injection_does_not_repeat_ia_owned_copy() -> None:
    """Prompt runtime injection keeps behavior, while IA owns screen semantics."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_prompt import (
        RUNTIME_PROMPT_SCREEN,
    )

    ia = load_json_payload(IA_PATH)
    prompt_ia = next(
        screen
        for screen in [*ia["published_screens"], *ia["runtime_screens"]]
        if screen["key"] == "prompt.workbench"
    )
    owned_keys = {
        "label",
        "module_key",
        "group",
        "audience",
        "summary",
        "view_type",
        "default_action_key",
        "user_experience",
    }

    assert owned_keys.isdisjoint(RUNTIME_PROMPT_SCREEN)

    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    prompt_runtime = next(
        screen for screen in runtime["screens"] if screen["key"] == "prompt.workbench"
    )
    for key in owned_keys:
        assert prompt_runtime[key] == prompt_ia[key]
    runtime_panels = {panel["key"]: panel for panel in prompt_runtime["dashboard_panels"]}
    for injected_panel in RUNTIME_PROMPT_SCREEN["dashboard_panels"]:
        normalized_panel = runtime_panels[injected_panel["key"]]
        for key, value in injected_panel.items():
            assert normalized_panel[key] == value


def test_runtime_action_replacements_keep_published_copy() -> None:
    """Runtime action behavior may be richer, but IA-owned copy stays canonical."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    published = load_json_payload(PUBLISHED_PATH)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    action_keys = {
        "auto.api.get.api.dashboard.allocation",
        "auto.api.get.api.dashboard.performance",
        "auto.api.get.api.data-center.providers",
        "auto.api.get.api.data-center.publishers",
        "regime.current",
        "regime.navigator_history",
    }
    published_actions = {
        str(action["key"]): action
        for action in published["actions"]
        if str(action.get("key") or "") in action_keys
    }
    runtime_actions = {
        str(action["key"]): action
        for action in runtime["actions"]
        if str(action.get("key") or "") in action_keys
    }

    assert set(runtime_actions) == action_keys
    for action_key in action_keys:
        for copy_key in ("label", "description"):
            assert runtime_actions[action_key][copy_key] == published_actions[action_key][copy_key]


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
