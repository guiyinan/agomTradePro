"""Contract tests for hidden plan pins and visible dashboard row actions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError
from apps.terminal.infrastructure.tui_metadata_runtime_injection_rebalance_plan import (
    RUNTIME_REBALANCE_PLAN_ACTIONS,
    RUNTIME_REBALANCE_PLAN_SCREENS,
)
from tests.unit.test_tui_workbench import _metadata_payload


def _action(key: str) -> dict[str, Any]:
    for action in RUNTIME_REBALANCE_PLAN_ACTIONS:
        if action.get("key") == key:
            return cast(dict[str, Any], action)
    raise AssertionError(f"missing action {key}")


def _runtime_payload() -> dict[str, Any]:
    screen = deepcopy(RUNTIME_REBALANCE_PLAN_SCREENS[0])
    screen.update(
        {
            "label": "模拟调仓计划",
            "module_key": "daily-decisions",
            "group": "daily",
            "summary": "查看和跟进本人模拟调仓计划。",
            "view_type": "datagrid",
            "status": "online",
            "default_action_key": "rebalance-plan.accounts",
            "user_experience": {
                "journey": "workspace",
                "primary_task": "查看并跟进调仓计划",
                "primary_outcome": "显示计划目标、成交进度和下一步",
                "empty_state_hint": "选择本人模拟账户",
                "next_step_hint": "每笔订单均需单独预览和确认",
            },
        }
    )
    payload = _metadata_payload(
        screens=[screen],
        actions=list(deepcopy(RUNTIME_REBALANCE_PLAN_ACTIONS)),
    )
    return cast(dict[str, Any], validate_tui_metadata(payload))


def _panel(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    screen = cast(list[dict[str, Any]], metadata["screens"])[0]
    panels = cast(list[dict[str, Any]], screen["dashboard_panels"])
    return next(panel for panel in panels if panel["key"] == key)


def test_plan_row_actions_use_dashboard_panels_and_keep_exact_pins_hidden() -> None:
    metadata = _runtime_payload()
    account_panel = _panel(metadata, "rebalance-plan-accounts")
    plan_panel = _panel(metadata, "rebalance-plan-list")
    order_panel = _panel(metadata, "rebalance-plan-order-grid")

    assert "row_actions" not in _action("rebalance-plan.accounts")["view_model"]
    assert "row_actions" not in _action("rebalance-plan.list")["view_model"]
    assert "row_actions" not in _action("rebalance-plan.orders")["view_model"]

    for panel in (account_panel, plan_panel, order_panel):
        visible = {column["key"] for column in panel["columns"]}
        hidden = set(panel["hidden_columns"])
        assert visible.isdisjoint(hidden)
        assert not hidden.intersection({column["key"] for column in panel["columns"]})

    assert account_panel["hidden_columns"] == ["account_id"]
    assert {
        "plan_id",
        "plan_version",
        "revision_hash_id",
        "account_id",
    }.issubset(set(plan_panel["hidden_columns"]))
    assert {
        "plan_id",
        "plan_version",
        "revision_hash_id",
        "order_ordinal",
        "order_content_hash",
        "plan_order_binding_id",
    }.issubset(set(order_panel["hidden_columns"]))

    account_action = cast(list[dict[str, Any]], account_panel["row_actions"])[0]
    assert account_action["label_template"] == "查看 {account_name} 资金与规则说明"
    assert account_action["param_map"] == {"account_id": "account_id"}
    order_action = cast(list[dict[str, Any]], order_panel["row_actions"])[0]
    assert order_action["param_map"]["order_content_hash"] == "order_content_hash"
    assert order_action["param_map"]["revision_hash"] == "revision_hash_id"
    assert order_action["label_template"].format(order_label="600036.SH 买入") == (
        "重新核对 600036.SH 买入 的本次数量和限价"
    )

    preview = _action("rebalance-plan.preview-order")
    assert preview["module_key"] == "daily-decisions"
    assert preview["endpoint"].endswith("/orders/<int:order_ordinal>/preview/")
    assert preview["method"] == "POST"
    assert preview["risk"] == "read"
    assert preview["result_continuation"] == {
        "target_action_key": "rebalance-plan.order-confirm",
        "field_map": {
            "account_id": "account_id",
            "order_key": "order_key",
            "preview_token": "preview_token",
        },
        "reuse_source_idempotency_key": True,
        "readback_action_key": "rebalance-plan.order-by-key",
    }
    fields = {
        cast(str, field["key"]): field for field in cast(list[dict[str, Any]], preview["fields"])
    }
    assert fields["quantity"]["required"] is True
    assert fields["limit_price"]["required"] is True
    assert "计划参考价不会自动填入" in fields["limit_price"]["placeholder"]
    assert fields["order_content_hash"]["input_type"] == "hidden"
    assert fields["plan_order_binding_id"]["input_type"] == "hidden"
    assert not {
        "asset_code",
        "security_id",
        "side",
        "fee_budget",
        "cash",
        "positions",
    }.intersection(fields)
    assert "preview_token" not in fields


def test_plan_metadata_describes_version_targets_without_claiming_staff_approval() -> None:
    metadata = _runtime_payload()
    order_action = _action("rebalance-plan.orders")
    read_action = _action("rebalance-plan.read")
    order_panel = _panel(metadata, "rebalance-plan-order-grid")

    assert "本版本计划目标" in order_action["description"]
    assert "批准目标" not in order_action["description"]
    assert "本版本目标" in read_action["description"]
    assert "批准目标" not in read_action["description"]
    action_columns = {
        column["key"]: column["label"]
        for column in cast(list[dict[str, Any]], order_action["view_model"]["columns"])
    }
    column_labels = {column["key"]: column["label"] for column in order_panel["columns"]}
    assert action_columns == column_labels
    assert column_labels["approved_label"] == "本版本办理上限"
    assert column_labels["limit_label"] == "计划限价"


def test_hidden_row_pin_must_not_overlap_a_visible_column() -> None:
    payload = _runtime_payload()
    panel = _panel(payload, "rebalance-plan-order-grid")
    panel["hidden_columns"].append("order_label")

    with pytest.raises(TuiMetadataValidationError, match="hidden_columns"):
        validate_tui_metadata(payload)


def test_hidden_row_pin_must_bind_a_row_action_parameter() -> None:
    payload = _runtime_payload()
    panel = _panel(payload, "rebalance-plan-order-grid")
    panel["hidden_columns"].append("unused_pin")

    with pytest.raises(TuiMetadataValidationError, match="only supply row-action parameters"):
        validate_tui_metadata(payload)


def test_session_only_plan_actions_are_gated_but_account_summary_is_not() -> None:
    actions = {str(action["key"]): action for action in RUNTIME_REBALANCE_PLAN_ACTIONS}
    session_only = {
        "rebalance-plan.account-risk",
        "rebalance-plan.list",
        "rebalance-plan.read",
        "rebalance-plan.orders",
        "rebalance-plan.reconcile",
        "rebalance-plan.create",
        "rebalance-plan.review",
        "rebalance-plan.successor",
        "rebalance-plan.preview-order",
        "rebalance-plan.order-confirm",
        "rebalance-plan.order-by-key",
    }
    assert {key for key, action in actions.items() if action.get("session_auth_required")} >= (
        session_only
    )
    assert actions["rebalance-plan.accounts"].get("session_auth_required") is not True
    assert actions["rebalance-plan.account-detail"].get("session_auth_required") is not True
    assert actions["rebalance-plan.positions"].get("session_auth_required") is not True


def test_create_form_receives_the_selected_account_through_its_row_action() -> None:
    """Make the first plan reachable without asking users to enter a hidden identity."""

    payload = _runtime_payload()
    panel = _panel(payload, "rebalance-plan-accounts")
    action = next(item for item in payload["actions"] if item["key"] == "rebalance-plan.create")
    descriptor = next(item for item in panel["row_actions"] if item["action_key"] == action["key"])
    account_field = next(field for field in action["fields"] if field["key"] == "account_id")
    assert account_field["input_type"] == "hidden"
    assert account_field["required"] is True
    assert descriptor["param_map"] == {"account_id": "account_id"}
    assert descriptor["result_panel_key"] == action["result_panel_key"]
    validate_tui_metadata(payload)


def test_only_visible_read_preview_can_start_a_dashboard_continuation() -> None:
    payload = _runtime_payload()
    preview = next(
        action for action in payload["actions"] if action["key"] == "rebalance-plan.preview-order"
    )
    preview_panel = _panel(payload, "rebalance-plan-order-grid")
    row_action = next(
        item
        for item in preview_panel["row_actions"]
        if item["action_key"] == "rebalance-plan.preview-order"
    )
    assert row_action["result_panel_key"] == preview["result_panel_key"]
    assert any(
        field["input_type"] != "hidden" and field["binding"] == "body"
        for field in preview["fields"]
    )
    assert payload["screens"][0]["module_key"] == "daily-decisions"

    preview["fields"] = [
        {**field, "input_type": "hidden"} if field.get("binding") == "body" else field
        for field in preview["fields"]
    ]
    with pytest.raises(TuiMetadataValidationError, match="visible same-screen read-preview"):
        validate_tui_metadata(payload)


def test_confirmed_mutation_and_readback_remain_forbidden_as_dashboard_row_actions() -> None:
    payload = _runtime_payload()
    panels = cast(list[dict[str, Any]], payload["screens"][0]["dashboard_panels"])
    order_panel = next(panel for panel in panels if panel["key"] == "rebalance-plan-order-grid")
    actions = cast(list[dict[str, Any]], payload["actions"])
    target = next(action for action in actions if action["key"] == "rebalance-plan.order-confirm")
    cast(list[str], order_panel["hidden_columns"]).append("order_key")
    cast(list[dict[str, Any]], order_panel["row_actions"]).append(
        {
            "action_key": target["key"],
            "label_template": "确认所选订单",
            "param_map": {"order_key": "order_key"},
            "result_panel_key": "rebalance-plan-order-preview",
        }
    )
    with pytest.raises(TuiMetadataValidationError, match="visible same-screen read-preview"):
        validate_tui_metadata(payload)

    payload = _runtime_payload()
    order_panel = _panel(payload, "rebalance-plan-order-grid")
    cast(list[str], order_panel["hidden_columns"]).append("order_key")
    readback = next(
        action for action in payload["actions"] if action["key"] == "rebalance-plan.order-by-key"
    )
    cast(list[dict[str, Any]], order_panel["row_actions"]).append(
        {
            "action_key": readback["key"],
            "label_template": "查询原模拟订单",
            "param_map": {"account_id": "account_id", "order_key": "order_key"},
            "result_panel_key": "rebalance-plan-order-preview",
        }
    )
    with pytest.raises(TuiMetadataValidationError, match="visible same-screen read-preview"):
        validate_tui_metadata(payload)


def test_mutating_continuation_source_cannot_be_a_dashboard_row_action() -> None:
    payload = _runtime_payload()
    preview = next(
        action for action in payload["actions"] if action["key"] == "rebalance-plan.preview-order"
    )
    preview.update(
        {"risk": "write", "effect": "update", "confirmation_required": True, "audit_required": True}
    )
    with pytest.raises(TuiMetadataValidationError, match="visible same-screen read-preview"):
        validate_tui_metadata(payload)
