"""Regression coverage for visible TUI create and row-level mutation affordances."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)

_IA_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "tui"
    / "ia"
    / "tui_information_architecture.v1.json"
)

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MUTATION_EFFECTS = {"approve", "create", "delete", "execute", "reject", "toggle", "update"}
# These commands intentionally operate on a complete/default set rather than
# collecting user-entered fields.  Keeping the allow-list explicit prevents a
# future create/update action from silently degrading into a view-only card.
_NO_INPUT_MUTATIONS = {
    "capability-router.sync-mcp-tools",
    "equity.pool-refresh",
    "equity.valuation-config-clear-cache",
    "hedge.alert-monitor",
    "hedge.snapshot-update-all",
    "rotation.asset-import",
    "signal.batch-check",
    "task-monitor.scheduler-bootstrap",
}
_NON_MUTATING_POST_COMMANDS = {
    "audit.threshold-update-preview",
    "audit.validation-preview",
    "data-center.market-thermometer-import-preview",
    "data-center.provider-test",
}


def _ia_screen(screen_key: str) -> dict[str, Any]:
    payload = json.loads(_IA_PATH.read_text(encoding="utf-8"))
    return next(screen for screen in payload["published_screens"] if screen["key"] == screen_key)


def _panel(screen: dict[str, Any], panel_key: str) -> dict[str, Any]:
    return next(panel for panel in screen["dashboard_panels"] if panel["key"] == panel_key)


def _runtime_screen(screen_key: str) -> dict[str, Any]:
    payload = PublishedTuiMetadataRepository()._load_published_file()
    return next(screen for screen in payload["screens"] if screen["key"] == screen_key)


def _runtime_actions(screen_key: str) -> dict[str, dict[str, Any]]:
    payload = PublishedTuiMetadataRepository()._load_published_file()
    return {
        action["key"]: action
        for action in payload["actions"]
        if action.get("screen_key") == screen_key
    }


def test_ia_declares_visible_create_and_provider_row_mutations() -> None:
    """The canonical IA must expose create, edit, toggle and delete affordances."""

    provider_screen = _ia_screen("ai-ops.providers")
    provider_create = _panel(provider_screen, "my-provider-create")
    assert provider_create["action_key"] == "ai-ops.create-my-provider"

    provider_list = _panel(provider_screen, "my-providers")
    assert provider_list["columns"]
    assert {row_action["action_key"] for row_action in provider_list["row_actions"]} == {
        "ai-ops.my-provider-detail",
        "ai-ops.update-my-provider",
        "ai-ops.toggle-my-provider",
        "ai-ops.delete-my-provider",
    }
    assert all(
        row_action["param_map"] == {"provider_id": "id"}
        for row_action in provider_list["row_actions"]
    )


def test_ia_declares_visible_account_create_affordance() -> None:
    """The account screen must let an authenticated user start account setup."""

    account_screen = _ia_screen("execution.accounts")
    account_create = _panel(account_screen, "account-create")
    assert account_create["action_key"] == "simulated-trading.account-create"
    assert account_create["presentation_semantic"] == "next_step"


def test_ia_declares_policy_and_signal_mutation_rows() -> None:
    """Policy review and signal governance must be completable from their rows."""

    policy_screen = _ia_screen("policy.workbench")
    assert _panel(policy_screen, "policy-create")["action_key"] == "policy.event-create"
    policy_actions = _panel(policy_screen, "policy-items")["row_actions"]
    assert {row_action["action_key"] for row_action in policy_actions} == {
        "policy.workbench-item-detail",
        "policy.workbench-approve",
        "policy.workbench-reject",
        "policy.workbench-rollback",
        "policy.workbench-override",
    }
    assert next(
        row_action["param_map"]
        for row_action in policy_actions
        if row_action["action_key"] == "policy.workbench-approve"
    ) == {"event_id": "id"}
    assert next(
        row_action["param_map"]
        for row_action in policy_actions
        if row_action["action_key"] == "policy.workbench-reject"
    ) == {"event_id": "id", "reason": "review_notes"}
    assert next(
        row_action["param_map"]
        for row_action in policy_actions
        if row_action["action_key"] == "policy.workbench-rollback"
    ) == {"event_id": "id", "reason": "rollback_reason"}

    signal_screen = _ia_screen("research.signals")
    assert _panel(signal_screen, "signal-create")["action_key"] == "signal.create"
    signal_actions = _panel(signal_screen, "active-signals")["row_actions"]
    assert {row_action["action_key"] for row_action in signal_actions} == {
        "signal.update",
        "signal.approve",
        "signal.reject",
        "signal.invalidate",
        "signal.delete",
    }
    assert next(
        row_action["param_map"]
        for row_action in signal_actions
        if row_action["action_key"] == "signal.update"
    ) == {"signal_id": "id"}
    assert all(
        row_action["param_map"] == {"signal_id": "id", "reason": "rejection_reason"}
        for row_action in signal_actions
        if row_action["action_key"] in {"signal.reject", "signal.invalidate"}
    )


def test_normalized_runtime_metadata_binds_mutations_to_visible_rows() -> None:
    """Runtime injection must retain the IA affordances and real write actions."""

    provider_screen = _runtime_screen("ai-ops.providers")
    provider_actions = _runtime_actions("ai-ops.providers")
    provider_create = _panel(provider_screen, "my-provider-create")
    provider_list = _panel(provider_screen, "my-providers")

    assert provider_create["action_key"] in provider_actions
    assert provider_actions[provider_create["action_key"]]["method"] == "POST"
    assert provider_actions[provider_create["action_key"]]["effect"] == "create"
    assert {row_action["action_key"] for row_action in provider_list["row_actions"]} == {
        "ai-ops.my-provider-detail",
        "ai-ops.update-my-provider",
        "ai-ops.toggle-my-provider",
        "ai-ops.delete-my-provider",
    }
    assert all(
        row_action["action_key"] in provider_actions for row_action in provider_list["row_actions"]
    )
    assert provider_actions["ai-ops.update-my-provider"]["method"] == "PATCH"
    assert provider_actions["ai-ops.toggle-my-provider"]["method"] == "POST"
    assert provider_actions["ai-ops.delete-my-provider"]["method"] == "DELETE"

    account_screen = _runtime_screen("execution.accounts")
    account_actions = _runtime_actions("execution.accounts")
    account_create = _panel(account_screen, "account-create")
    assert account_create["action_key"] in account_actions
    assert account_actions[account_create["action_key"]]["method"] == "POST"
    assert account_actions[account_create["action_key"]]["effect"] == "create"

    policy_screen = _runtime_screen("policy.workbench")
    policy_actions = _runtime_actions("policy.workbench")
    policy_create = _panel(policy_screen, "policy-create")
    policy_rows = _panel(policy_screen, "policy-items")["row_actions"]
    assert policy_create["action_key"] in policy_actions
    assert policy_actions[policy_create["action_key"]]["method"] == "POST"
    assert policy_actions[policy_create["action_key"]]["effect"] == "create"
    assert all(row_action["action_key"] in policy_actions for row_action in policy_rows)
    assert policy_actions["policy.workbench-reject"]["fields"][-1]["key"] == "reason"
    assert policy_actions["policy.workbench-approve"]["method"] == "POST"
    assert policy_actions["policy.workbench-reject"]["method"] == "POST"

    signal_screen = _runtime_screen("research.signals")
    signal_actions = _runtime_actions("research.signals")
    signal_create = _panel(signal_screen, "signal-create")
    signal_rows = _panel(signal_screen, "active-signals")["row_actions"]
    assert signal_create["action_key"] in signal_actions
    assert signal_actions[signal_create["action_key"]]["method"] == "POST"
    assert signal_actions[signal_create["action_key"]]["effect"] == "create"
    assert all(row_action["action_key"] in signal_actions for row_action in signal_rows)
    assert signal_actions["signal.reject"]["fields"][-1]["key"] == "reason"
    assert signal_actions["signal.update"]["method"] == "PATCH"
    assert signal_actions["signal.approve"]["method"] == "POST"
    assert signal_actions["signal.delete"]["method"] == "DELETE"


def test_runtime_mutations_are_submit_ready_or_explicit_no_input_commands() -> None:
    """Every write/admin action must be a real submit action, not a read-only card."""

    payload = PublishedTuiMetadataRepository()._load_published_file()
    for action in payload["actions"]:
        method = str(action.get("method", "GET")).upper()
        risk = str(action.get("risk", "read")).lower()
        if method not in _MUTATING_METHODS or risk not in {"write", "admin"}:
            continue

        action_key = str(action["key"])
        effect = str(action.get("effect") or "").lower()
        if effect == "read":
            assert (
                action_key in _NON_MUTATING_POST_COMMANDS
            ), f"{action_key} is a POST/read action without an explicit command classification"
            assert action.get(
                "fields"
            ), f"{action_key} is an input-bearing preview/test command but exposes no fields"
            continue
        assert effect in _MUTATION_EFFECTS, (
            f"{action_key} is mutating but has no supported effect; "
            "a read-only action must not masquerade as a write"
        )
        fields = action.get("fields") or []
        if not fields:
            assert action_key in _NO_INPUT_MUTATIONS, (
                f"{action_key} is a mutating action without visible input fields; "
                "add a form field or explicitly classify it as a no-input command"
            )


def test_edit_row_actions_map_required_fields_for_form_prefill() -> None:
    """Update rows must carry their identity into the form before the user edits."""

    payload = PublishedTuiMetadataRepository()._load_published_file()
    actions = {action["key"]: action for action in payload["actions"]}
    ia_payload = json.loads(_IA_PATH.read_text(encoding="utf-8"))
    for screen in ia_payload["published_screens"]:
        for panel in screen.get("dashboard_panels", []):
            for descriptor in panel.get("row_actions", []):
                action = actions.get(descriptor.get("action_key"))
                if not action:
                    continue
                method = str(action.get("method", "GET")).upper()
                effect = str(action.get("effect") or "").lower()
                if method not in _MUTATING_METHODS or effect not in {"create", "update"}:
                    continue
                required_fields = {
                    field["key"]
                    for field in action.get("fields", [])
                    if field.get("required") and field.get("input_type") != "hidden"
                }
                assert required_fields <= set(descriptor.get("param_map", {})), (
                    f"{descriptor.get('action_key')} row action must map required form fields "
                    "so the edit form can be opened with the row identity"
                )
