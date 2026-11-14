"""TUI routing, explicit handoff, and owner-account scoping for company actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from apps.terminal.application.tui_account_action_scope import (
    continuation_public_account_fields,
    continuation_secret_values,
    requires_account_result_scope,
)
from apps.terminal.application.tui_metadata_continuation_validation import (
    _validate_result_continuations,
)
from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository
from apps.terminal.infrastructure.tui_metadata_runtime_injection_corporate_action_workflow import (
    CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY,
    CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY,
    CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY,
    CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY,
    CORPORATE_ACTION_WORKFLOW_READ_ACTION_KEY,
    CORPORATE_ACTION_WORKFLOW_REFRESH_ACTION_KEY,
    RUNTIME_CORPORATE_ACTION_WORKFLOW_ACTIONS,
)

ROOT = Path(__file__).resolve().parents[3]
_CONSENT_ACTION_KEYS = {
    "simulated-trading.corporate-action-consent-prepare",
    "simulated-trading.corporate-action-consent-confirm",
    "simulated-trading.corporate-action-consent-withdraw-prepare",
    "simulated-trading.corporate-action-consent-withdraw",
}


def _action_map() -> dict[str, dict[str, object]]:
    """Index the single runtime action set without copying consent implementations."""
    return {str(action["key"]): action for action in RUNTIME_CORPORATE_ACTION_WORKFLOW_ACTIONS}


def _fields(action: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index one action's declared parameters for exact contract assertions."""
    return {str(field["key"]): field for field in cast(list[dict[str, object]], action["fields"])}


def test_runtime_overlay_has_one_dedicated_action_set_and_moves_existing_consent_actions() -> None:
    actions = _action_map()
    assert len(actions) == 10
    assert actions[CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY]["endpoint"].endswith("/events/")
    assert {
        CORPORATE_ACTION_WORKFLOW_READ_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_REFRESH_ACTION_KEY,
        *_CONSENT_ACTION_KEYS,
    } == set(actions)
    assert all(action["screen_key"] == "execution.corporate-actions" for action in actions.values())
    assert actions["simulated-trading.corporate-action-consent-prepare"]["endpoint"].endswith(
        "corporate-action-consent/prepare/"
    )
    assert actions["simulated-trading.corporate-action-consent-confirm"]["endpoint"].endswith(
        "corporate-action-consent/"
    )
    assert actions["simulated-trading.corporate-action-consent-withdraw-prepare"][
        "endpoint"
    ].endswith("corporate-action-consent/withdraw/prepare/")
    assert actions["simulated-trading.corporate-action-consent-withdraw"]["endpoint"].endswith(
        "corporate-action-consent/withdraw/"
    )


def test_workflow_prepare_maps_only_the_protected_account_and_token() -> None:
    actions = _action_map()
    prepare = actions[CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY]
    confirm = actions[CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY]
    assert prepare["result_continuation"] == {
        "target_action_key": CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY,
        "field_map": {
            "account_id": "account_id",
            "continuation_token": "continuation_token",
        },
    }
    fields = _fields(confirm)
    assert set(fields) == {"account_id", "continuation_token", "confirmed"}
    for key in ("account_id", "continuation_token"):
        assert fields[key]["binding"] == "body"
        assert fields[key]["input_type"] == "hidden"
        assert fields[key]["value_type"] == "string"
        assert fields[key]["presentation_semantic"] == "api_token"
    assert fields["continuation_token"]["max"] == 65536
    assert confirm["risk"] == "write"
    assert confirm["confirmation_required"] is True
    assert confirm["session_auth_required"] is True


def test_all_nine_operations_are_explicit_choices_without_amount_or_quantity_fields() -> None:
    prepare = _action_map()[CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY]
    fields = _fields(prepare)
    assert set(fields) == {"account_id", "event_id", "action", "settlement_date", "correction_mode"}
    assert fields["correction_mode"]["binding"] == "body"
    assert fields["correction_mode"]["default"] == "ordinary"
    assert {option["value"] for option in fields["correction_mode"]["options"]} == {
        "ordinary",
        "correct_existing",
    }
    assert fields["event_id"]["binding"] == "body"
    assert fields["settlement_date"]["required"] is False
    options = cast(list[dict[str, object]], fields["action"]["options"])
    assert {str(option["value"]) for option in options} == {
        "cash_entitlement",
        "cash_payment",
        "share_entitlement",
        "share_delivery",
        "share_sellable_release",
        "rights_not_exercised",
        "tax_assess",
        "tax_recognize",
        "tax_collect",
    }
    assert not {"quantity", "cash_amount", "price", "owner_user_id", "source_hash"}.intersection(
        fields
    )


def test_event_and_receipt_lists_are_real_grids_with_safe_public_columns() -> None:
    actions = _action_map()
    event_action = actions[CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY]
    receipt_action = actions[CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY]
    assert event_action["view_type"] == "datagrid"
    assert cast(dict[str, object], event_action["view_model"])["rows_path"] == "events"
    assert receipt_action["view_type"] == "datagrid"
    assert cast(dict[str, object], receipt_action["view_model"])["rows_path"] == "audit_receipts"
    for action in actions.values():
        assert action["raw_debug"] is False
        assert action["session_auth_required"] is True


def test_workflow_actions_require_exact_owner_result_scope_and_protect_only_the_token() -> None:
    for key in (
        CORPORATE_ACTION_WORKFLOW_READ_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY,
        CORPORATE_ACTION_WORKFLOW_REFRESH_ACTION_KEY,
    ):
        assert requires_account_result_scope(key)
    action_key = CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY
    payload = {"account_id": 41, "continuation": {}}
    continuation = {"account_id": "41", "continuation_token": "protected"}
    assert continuation_public_account_fields(
        action_key=action_key,
        payload=payload,
        continuation_input=continuation,
        requested_params={"account_id": "41"},
    ) == frozenset({"account_id"})
    assert continuation_secret_values(
        action_key,
        payload,
        continuation,
        {"account_id": "41"},
        {"account_id": "account_id", "continuation_token": "continuation_token"},
        set(),
    ) == {"protected"}
    assert (
        continuation_public_account_fields(
            action_key=action_key,
            payload=payload,
            continuation_input=continuation,
            requested_params={"account_id": "42"},
        )
        is None
    )


def test_events_prefill_event_and_account_into_a_nonconfirming_prepare_action() -> None:
    architecture = json.loads(
        (ROOT / "config/tui/ia/tui_information_architecture.v1.json").read_text(encoding="utf-8")
    )
    screen = next(
        item
        for item in architecture["published_screens"]
        if item["key"] == "execution.corporate-actions"
    )
    panel = next(
        item
        for item in screen["dashboard_panels"]
        if item["key"] == "corporate-action-workflow-events"
    )
    row_action = panel["row_actions"][0]
    assert row_action["action_key"] == CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY
    assert row_action["param_map"] == {"account_id": "account_id", "event_id": "event_id"}
    assert row_action["result_panel_key"] == "corporate-action-workflow-result"
    assert panel["hidden_columns"] == ["account_id"]
    assert panel["user_priority"] == "p0"


def test_account_navigation_and_effective_published_runtime_metadata_are_valid() -> None:
    architecture = json.loads(
        (ROOT / "config/tui/ia/tui_information_architecture.v1.json").read_text(encoding="utf-8")
    )
    account_screen = next(
        item for item in architecture["published_screens"] if item["key"] == "execution.accounts"
    )
    account_panel = next(
        item
        for item in account_screen["dashboard_panels"]
        if item["key"] == "corporate-actions-entry"
    )
    assert account_panel["target_screen"] == "execution.corporate-actions"
    rows = next(
        item for item in account_screen["dashboard_panels"] if item["key"] == "simulated-accounts"
    )["row_actions"]
    assert not any("corporate-action-consent" in item["action_key"] for item in rows)

    payload = PublishedTuiMetadataRepository()._load_published_file()
    effective_actions = {str(action["key"]): action for action in payload["actions"]}
    assert effective_actions["simulated-trading.corporate-action-consent-prepare"][
        "screen_key"
    ] == ("execution.corporate-actions")
    screen = next(
        item for item in payload["screens"] if item["key"] == "execution.corporate-actions"
    )
    _validate_result_continuations(
        actions=list(RUNTIME_CORPORATE_ACTION_WORKFLOW_ACTIONS),
        screens=[screen],
        action_by_key=effective_actions,
    )
