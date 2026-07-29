"""T5 invalid-boundary contracts for TUI metadata validation helpers."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.terminal.application import tui_metadata
from apps.terminal.application.tui_metadata import TuiMetadataValidationError


def _raises(function: object, *args: object) -> None:
    """Assert one validator helper rejects the supplied arguments."""
    assert callable(function)
    with pytest.raises(TuiMetadataValidationError):
        function(*args)


def test_collection_field_alias_and_pagination_validators_reject_bad_shapes() -> None:
    """Collection, key, field, alias, and pagination boundaries must be strict."""
    _raises(tui_metadata._require_list, {"items": {}}, "items")
    _raises(tui_metadata._require_list, {"items": ["bad"]}, "items")
    _raises(tui_metadata._require_fields, {}, "item", ("key",))
    _raises(tui_metadata._unique_keys, [{}], "items")
    _raises(tui_metadata._unique_keys, [{"key": "a"}, {"key": "a"}], "items")

    action = {"key": "sample"}
    invalid_fields = [
        {"key": "x", "input_type": "money"},
        {"key": "x", "input_type": "text", "value_type": "uuid"},
        {"key": "x", "input_type": "text", "binding": "header"},
        {"key": "x", "input_type": "select", "options": None},
        {"key": "x", "input_type": "text", "aliases": [1]},
        {"key": "x", "input_type": "text", "semantic": 1},
        {"key": "x", "input_type": "file", "accept": 1},
        {
            "key": "x",
            "input_type": "text",
            "presentation_semantic": "unknown",
        },
        {
            "key": "prompt",
            "input_type": "text",
            "presentation_semantic": "prompt_text",
        },
        {
            "key": "endpoint",
            "input_type": "number",
            "value_type": "integer",
            "presentation_semantic": "endpoint_url",
        },
    ]
    for field in invalid_fields:
        _raises(tui_metadata._validate_field, action, field)

    integer_field = {"key": "portfolio_id", "input_type": "number"}
    tui_metadata._validate_field(action, integer_field)
    assert integer_field["value_type"] == "integer"
    checkbox = {"key": "enabled", "input_type": "checkbox"}
    tui_metadata._validate_field(action, checkbox)
    assert checkbox["value_type"] == "boolean"

    for registry in ([], {"": ["id"]}, {"id": [1]}):
        _raises(tui_metadata._validate_field_alias_registry, registry)
    tui_metadata._validate_field_alias_registry(None)

    for pagination in (
        [],
        {"mode": "page", "unknown": "x"},
        {"mode": "unknown"},
        {"mode": "page", "page_param": 1},
    ):
        _raises(
            tui_metadata._validate_action_pagination,
            {"key": "sample", "pagination": pagination},
        )


def test_governance_source_and_confirmation_validators_cover_invalid_contracts() -> None:
    """Governed actions must publish typed flags, safe sources, and reviewable fields."""
    _raises(tui_metadata._validate_action_source, {"key": "sample", "source": ""})
    _raises(
        tui_metadata._validate_action_source,
        {"key": "sample", "source": "invented"},
    )

    base = {
        "key": "sample",
        "risk": "read",
        "method": "GET",
        "confirmation_required": False,
        "requires_password": False,
        "audit_required": False,
        "sensitive_level": "none",
        "executor": "",
        "task_group": "",
        "task_tier": "primary",
        "submit_label": "Run",
        "sequence": 1,
    }
    mutations = [
        {"confirmation_required": "false"},
        {"sensitive_level": "unknown"},
        {"executor": 1},
        {"task_group": 1},
        {"task_tier": "unknown"},
        {"submit_label": ""},
        {"sequence": "bad"},
        {"risk": "write", "method": "POST", "confirmation_required": False},
        {
            "risk": "admin",
            "method": "POST",
            "confirmation_required": True,
            "audit_required": False,
        },
    ]
    for mutation in mutations:
        _raises(
            tui_metadata._validate_governance_contract,
            {**base, **mutation},
        )

    _raises(
        tui_metadata._validate_confirmed_operation_contract,
        {"key": "write", "risk": "write", "method": "GET", "fields": []},
    )
    _raises(
        tui_metadata._validate_confirmed_operation_contract,
        {
            "key": "write",
            "risk": "write",
            "method": "POST",
            "fields": [{"key": "amount", "input_type": "text"}],
        },
    )
    _raises(
        tui_metadata._validate_confirmed_operation_contract,
        {
            "key": "write",
            "risk": "write",
            "method": "POST",
            "fields": [
                {
                    "key": "amount",
                    "input_type": "number",
                    "value_type": "string",
                }
            ],
        },
    )


def test_user_experience_panel_and_result_semantic_validators() -> None:
    """User-facing hierarchy must retain supported journeys, panels, and result semantics."""
    screen = {"key": "screen", "default_action_key": "read", "dashboard_panels": []}
    _raises(
        tui_metadata._validate_screen_user_experience,
        {**screen, "user_experience": []},
    )
    for user_experience in (
        {
            "journey": "unknown",
            "primary_task": "task",
            "primary_outcome": "outcome",
            "empty_state_hint": "empty",
            "next_step_hint": "next",
        },
        {
            "journey": "workspace",
            "primary_task": "GET /api/private/",
            "primary_outcome": "outcome",
            "empty_state_hint": "empty",
            "next_step_hint": "next",
        },
    ):
        _raises(
            tui_metadata._validate_screen_user_experience,
            {**screen, "user_experience": user_experience},
        )

    dashboard_ux = {
        "journey": "dashboard",
        "primary_task": "task",
        "primary_outcome": "outcome",
        "empty_state_hint": "empty",
        "next_step_hint": "next",
    }
    _raises(
        tui_metadata._validate_screen_user_experience,
        {**screen, "user_experience": dashboard_ux},
    )
    workspace_ux = {**dashboard_ux, "journey": "workspace"}
    _raises(
        tui_metadata._validate_screen_user_experience,
        {
            "key": "screen",
            "default_action_key": "",
            "dashboard_panels": [],
            "user_experience": workspace_ux,
        },
    )

    panel_screen = {"key": "screen"}
    invalid_panels = [
        {"key": "p", "user_priority": "p9", "presentation_semantic": "supporting_detail"},
        {"key": "p", "user_priority": "p1", "presentation_semantic": "unknown"},
        {
            "key": "p",
            "user_priority": "p1",
            "presentation_semantic": "copyable_secret",
            "kind": "datagrid",
            "action_key": "read",
        },
        {
            "key": "p",
            "user_priority": "p1",
            "presentation_semantic": "endpoint_list",
            "kind": "detail",
            "action_key": "",
        },
        {
            "key": "p",
            "user_priority": "p1",
            "presentation_semantic": "primary_status",
            "kind": "datagrid",
        },
        {
            "key": "p",
            "user_priority": "p0",
            "presentation_semantic": "supporting_detail",
            "kind": "detail",
        },
    ]
    for panel in invalid_panels:
        _raises(tui_metadata._validate_dashboard_panel, panel_screen, panel)

    _raises(
        tui_metadata._normalize_result_semantics,
        {"key": "a", "result_semantics": "status"},
    )
    for action in (
        {
            "key": "a",
            "view_type": "detail",
            "view_model": {},
            "result_semantics": ["unknown"],
        },
        {
            "key": "a",
            "view_type": "chart",
            "view_model": {"kind": "chart"},
            "result_semantics": ["copyable_secret"],
        },
        {
            "key": "a",
            "view_type": "chart",
            "view_model": {},
            "result_semantics": ["primary_status"],
        },
    ):
        _raises(tui_metadata._validate_result_semantics, action)

    assert tui_metadata._default_screen_journey(
        {"key": "self-service", "label": "接入"}
    ) == "self_service"
    assert tui_metadata._default_screen_journey(
        {"key": "admin", "label": "治理"}
    ) == "admin"
    assert tui_metadata._default_panel_presentation_semantic(
        {"key": "prompt", "title": "Prompt", "kind": "detail"}
    ) == "multiline_prompt"
    assert tui_metadata._default_panel_presentation_semantic(
        {"key": "endpoint", "title": "Endpoint", "kind": "detail"}
    ) == "endpoint_list"


def test_compaction_and_json_schema_failure_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compaction must ignore malformed entries and schema errors must include paths."""
    payload = {
        "modules": ["bad", {"key": "m", "status": "online"}],
        "screens": [
            "bad",
            {
                "key": "s",
                "module_key": "m",
                "status": "online",
                "default_action_key": "",
                "dashboard_panels": [
                    "bad",
                    {
                        "key": "p",
                        "action_key": "",
                        "status": "",
                        "note": "",
                        "layout_area": "",
                        "target_screen": "",
                        "columns": [],
                        "max_rows": 8,
                    },
                ],
            },
        ],
        "actions": [
            "bad",
            {
                "key": "a",
                "screen_key": "s",
                "module_key": "m",
                "method": "GET",
                "risk": "read",
                "fields": [],
                "view_model": {},
                "pagination": {},
                "raw_debug": True,
                "description": "",
                "confirmation_required": False,
                "requires_password": False,
                "audit_required": False,
                "sensitive_level": "none",
                "executor": "",
                "task_group": "",
                "task_tier": "primary",
                "submit_label": "执行查询",
                "sequence": 999,
                "result_semantics": [],
            },
        ],
    }
    compacted = tui_metadata.compact_tui_metadata_payload(deepcopy(payload))
    assert compacted["modules"][1] == {"key": "m"}
    assert "module_key" not in compacted["actions"][1]
    assert compacted["screens"][1]["dashboard_panels"][1] == {"key": "p"}

    error = SimpleNamespace(path=["actions", 0], message="invalid")
    validator = MagicMock()
    validator.iter_errors.return_value = [error]
    monkeypatch.setattr(tui_metadata, "Draft202012Validator", object())
    monkeypatch.setattr(tui_metadata, "_tui_metadata_schema_validator", lambda: validator)
    with pytest.raises(TuiMetadataValidationError, match="actions.0"):
        tui_metadata._validate_with_json_schema({})
