"""Machine contracts for TUX-03 action copy and density governance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.check_tui_action_copy_and_density import (
    check_tui_action_copy_and_density,
    load_json_payload,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_PATH = ROOT / "config/tui/published/tui_operation_graph.published.json"
IA_PATH = ROOT / "config/tui/ia/tui_information_architecture.v1.json"


def _screen(key: str, *, summary: str = "完成当前任务。") -> dict[str, Any]:
    """Return one minimal screen for focused guard tests."""

    return {
        "key": key,
        "label": key,
        "summary": summary,
        "default_action_key": "",
        "dashboard_panels": [],
    }


def _action(
    key: str,
    *,
    screen_key: str,
    label: str,
    description: str,
    task_tier: str = "support",
    task_group: str = "01 当前任务",
) -> dict[str, Any]:
    """Return one minimal action for focused guard tests."""

    return {
        "key": key,
        "screen_key": screen_key,
        "label": label,
        "description": description,
        "task_tier": task_tier,
        "task_group": task_group,
    }


def _ia_payload(*screens: dict[str, Any]) -> dict[str, Any]:
    """Return one IA registry with a deliberately small density budget."""

    return {
        "published_screens": list(screens),
        "runtime_screens": [],
        "action_density": {
            "default_primary_operation_limit": 1,
            "screen_limits": {},
            "task_group_limit": 1,
        },
    }


def test_guard_reports_every_tux03_copy_reference_and_density_rule() -> None:
    """The focused guard emits stable violations for every TUX-03 rule family."""

    screen = _screen("published", summary="检查当前状态。")
    screen["default_action_key"] = "auto.api.get.api.health"
    screen["dashboard_panels"] = [{"key": "health", "action_key": "auto.api.get.api.health"}]
    published_actions = [
        _action(
            "auto.api.get.api.health",
            screen_key="published",
            label="健康 Db",
            description="检查当前状态。（查看）",
            task_tier="primary",
        ),
        _action(
            "published.first",
            screen_key="published",
            label="重复任务",
            description="查看第一项任务的当前结果。",
            task_tier="operation",
        ),
        _action(
            "published.second",
            screen_key="published",
            label="重复任务",
            description="不要展示 /api/private/ 或 POST。",
            task_tier="operation",
        ),
    ]
    runtime_actions = [dict(action) for action in published_actions]

    report = check_tui_action_copy_and_density(
        published_payload={"screens": [screen], "actions": published_actions},
        ia_payload=_ia_payload(screen),
        runtime_payload={"screens": [screen], "actions": runtime_actions},
    )

    assert not report.passed
    rule_ids = {violation.rule_id for violation in report.violations}
    assert {
        "action_copy:boilerplate_description",
        "action_copy:machine_fragment:db-token",
        "action_copy:route_fragment",
        "action_split:promoted_route_exposed",
        "duplicate_label:published",
        "duplicate_label:runtime",
        "screen_reference:route_default",
        "screen_reference:route_panel",
        "density:screen_limit",
        "density:task_group_limit",
    } <= rule_ids
    assert report.published_action_count == 3
    assert report.route_action_count == 1
    assert report.boilerplate_description_count == 1
    assert report.machine_copy_count == 1
    assert report.over_budget_screen_count == 1


def test_runtime_only_screens_do_not_expand_the_tux03_density_exit_scope() -> None:
    """Only the 12 IA-published screens own the TUX-03 density exit budget."""

    published_screen = _screen("published")
    runtime_screen = _screen("runtime-only")
    ia = _ia_payload(published_screen)
    ia["runtime_screens"] = [runtime_screen]
    runtime_actions = [
        _action(
            f"runtime-only.{index}",
            screen_key="runtime-only",
            label=f"运行时任务 {index}",
            description=f"运行第 {index} 项任务。",
            task_tier="operation",
        )
        for index in range(5)
    ]

    report = check_tui_action_copy_and_density(
        published_payload={"screens": [published_screen], "actions": []},
        ia_payload=ia,
        runtime_payload={
            "screens": [published_screen, runtime_screen],
            "actions": runtime_actions,
        },
    )

    assert report.passed, report.as_json()
    assert [density.screen_key for density in report.screen_densities] == ["published"]
    assert report.over_budget_screen_count == 0


def test_real_tui_sources_publish_the_expected_pre_remediation_inventory() -> None:
    """The TUX-03 guard keeps the current 430-action debt explicit until remediated."""

    pytest.importorskip("django")
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    published = load_json_payload(PUBLISHED_PATH)
    ia = load_json_payload(IA_PATH)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()

    report = check_tui_action_copy_and_density(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert not report.passed
    assert report.published_action_count == 430
    assert report.runtime_action_count >= report.published_action_count
    assert report.published_screen_count == 12
    assert report.route_action_count == 370
    assert report.read_boilerplate_description_count == 349
    assert report.machine_copy_count == 22
    assert report.machine_copy_pattern_count == 10
    assert report.over_budget_screen_count == 11
