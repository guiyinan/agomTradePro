"""Contract tests for opt-in, same-screen continuation readback metadata."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from apps.terminal.application.tui_metadata_continuation_validation import (
    _validate_result_continuations,
)
from apps.terminal.application.tui_metadata_filter_validation import (
    TuiMetadataValidationError,
)
from apps.terminal.application.tui_workbench_catalog import TuiWorkbenchCatalogMixin
from apps.terminal.application.tui_workbench_execution import TuiWorkbenchExecutionMixin


def _hidden_string_field(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "binding": "body",
        "presentation_semantic": "api_token",
        "default": "",
    }


def _readback_actions() -> list[dict[str, Any]]:
    source = {
        "key": "simulated-trading.fee-correction-preview",
        "screen_key": "execution.accounts",
        "method": "POST",
        "risk": "read",
        "effect": "read",
        "session_auth_required": True,
        "result_continuation": {
            "target_action_key": "simulated-trading.fee-correction-confirm",
            "field_map": {
                "account_id": "account_id",
                "trade_id": "trade_id",
                "confirmation_token": "confirmation_token",
            },
            "reuse_source_idempotency_key": True,
            "readback_action_key": "simulated-trading.fee-correction-head",
        },
    }
    target = {
        "key": "simulated-trading.fee-correction-confirm",
        "screen_key": "execution.accounts",
        "endpoint": "/api/accounts/<int:account_id>/trades/<int:trade_id>/corrections/",
        "method": "POST",
        "risk": "write",
        "session_auth_required": True,
        "confirmation_required": True,
        "fields": [
            _hidden_string_field("account_id"),
            _hidden_string_field("trade_id"),
            _hidden_string_field("confirmation_token"),
        ],
    }
    readback = {
        "key": "simulated-trading.fee-correction-head",
        "screen_key": "execution.accounts",
        "endpoint": "/api/accounts/<int:account_id>/trades/<int:trade_id>/corrections/head/",
        "method": "GET",
        "risk": "read",
        "effect": "read",
        "session_auth_required": True,
        "confirmation_required": False,
        "fields": [_hidden_string_field("account_id"), _hidden_string_field("trade_id")],
    }
    return [source, target, readback]


def _validate(actions: list[dict[str, Any]]) -> None:
    _validate_result_continuations(
        actions=actions,
        screens=[],
        action_by_key={action["key"]: action for action in actions},
    )


def test_readback_metadata_uses_exact_hidden_same_screen_path_scope() -> None:
    _validate(_readback_actions())


def _locator_actions() -> list[dict[str, Any]]:
    """Add only the fee material's public, readback-only locator."""

    actions = _readback_actions()
    actions[0]["result_continuation"]["readback_scope_map"] = {
        "source_locator": "preview.source_locator"
    }
    actions[2]["endpoint"] = (
        "/api/accounts/<int:account_id>/trades/<int:trade_id>/"
        "recovery/<uuid:source_locator>/head/"
    )
    actions[2]["fields"].append(_hidden_string_field("source_locator"))
    return actions


def test_locator_readback_scope_is_disjoint_from_confirmation_fields() -> None:
    actions = _locator_actions()
    _validate(actions)
    assert "source_locator" not in actions[0]["result_continuation"]["field_map"]
    assert "source_locator" not in {field["key"] for field in actions[1]["fields"]}


@pytest.mark.parametrize(
    "extra", [{"csv_text": ""}, {"original_filename": "a.csv"}, {"attestation_acknowledged": False}]
)
def test_fee_preview_rejects_mixed_modes_without_dropping_even_empty_fields(
    extra: dict[str, Any],
) -> None:
    action = {"key": "simulated-trading.fee-correction-preview"}
    params = {"source_locator": "fb0f96e3-277c-4ee0-91ee-87be88781037", **extra}
    assert TuiWorkbenchExecutionMixin._fee_preview_input_error(action, params) is not None


def test_fee_preview_locator_mode_does_not_require_upload_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_fee_correction import (
        RUNTIME_FEE_CORRECTION_ACTIONS,
    )

    action = next(
        row
        for row in RUNTIME_FEE_CORRECTION_ACTIONS
        if row["key"] == "simulated-trading.fee-correction-preview"
    )
    executor = TuiWorkbenchExecutionMixin()
    monkeypatch.setattr(executor, "_resolved_field_default", lambda *args: None, raising=False)
    monkeypatch.setattr(executor, "_field_payload", lambda field, **kwargs: field, raising=False)
    params = {
        "account_id": 12,
        "trade_id": 77,
        "source_locator": "fb0f96e3-277c-4ee0-91ee-87be88781037",
    }
    assert executor._fee_preview_input_error(action, params) is None
    assert executor._missing_required_fields(action, params) == []
    assert {
        row["key"]
        for row in executor._missing_required_fields(action, {"account_id": 12, "trade_id": 77})
    } == {"csv_text", "original_filename", "attestation_acknowledged"}


@pytest.mark.parametrize("scope", ["bad", "FB0F96E3-277C-4EE0-91EE-87BE88781037", None])
def test_locator_readback_rejects_invalid_public_identity(
    monkeypatch: pytest.MonkeyPatch, scope: str | None
) -> None:
    actions = _locator_actions()
    executor = TuiWorkbenchExecutionMixin()
    monkeypatch.setattr(executor, "_metadata", lambda: {"actions": actions}, raising=False)
    payload = {
        "success": True,
        "outcome": "success",
        "preview": {"account_id": 613, "trade_id": 600000, "source_locator": scope},
        "continuation": {
            "action_key": actions[1]["key"],
            "input": {
                "account_id": "613",
                "trade_id": "600000",
                "confirmation_token": "opaque-preview-token",
            },
            "expires_at": "2099-01-01T00:00:00Z",
        },
    }
    _, continuation, error = executor._validate_owner_result_continuation(
        action=actions[0], payload=payload, status_code=200
    )
    assert continuation is None
    assert error == "tui_result_continuation_invalid"


def test_server_extracts_public_locator_without_changing_confirmation_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions = _locator_actions()
    executor = TuiWorkbenchExecutionMixin()
    monkeypatch.setattr(executor, "_metadata", lambda: {"actions": actions}, raising=False)
    locator = "fb0f96e3-277c-4ee0-91ee-87be88781037"
    payload = {
        "success": True,
        "outcome": "success",
        "preview": {"account_id": 613, "trade_id": 600000, "source_locator": locator},
        "continuation": {
            "action_key": actions[1]["key"],
            "input": {"account_id": "613", "trade_id": "600000", "confirmation_token": "opaque"},
            "expires_at": "2099-01-01T00:00:00Z",
        },
    }
    safe, continuation, error = executor._validate_owner_result_continuation(
        action=actions[0], payload=payload, status_code=200
    )
    assert error is None
    assert continuation is not None
    assert continuation["readback_scope"] == {"source_locator": locator}
    assert set(continuation["input"]) == {"account_id", "trade_id", "confirmation_token"}
    assert safe["preview"]["source_locator"] == locator
    _, foreign, foreign_error = executor._validate_owner_result_continuation(
        action=actions[0],
        payload=payload,
        status_code=200,
        requested_params={"account_id": 614, "trade_id": 600000},
    )
    assert foreign is None
    assert foreign_error == "tui_result_continuation_invalid"


def test_readback_requires_source_key_reuse_and_strict_boolean() -> None:
    actions = _readback_actions()
    actions[0]["result_continuation"]["reuse_source_idempotency_key"] = 1
    with pytest.raises(TuiMetadataValidationError):
        _validate(actions)

    actions = _readback_actions()
    del actions[0]["result_continuation"]["reuse_source_idempotency_key"]
    with pytest.raises(TuiMetadataValidationError):
        _validate(actions)


@pytest.mark.parametrize(
    ("mutation",),
    [
        (lambda actions: actions[2].update(method="POST"),),
        (
            lambda actions: actions[2].update(
                endpoint="/api/accounts/<int:account_id>/corrections/head/"
            ),
        ),
        (lambda actions: actions[2]["fields"].append(_hidden_string_field("extra")),),
        (lambda actions: actions[2]["fields"][0].update(required=False),),
    ],
)
def test_readback_rejects_write_or_unscoped_metadata(mutation: Any) -> None:
    actions = deepcopy(_readback_actions())
    mutation(actions)
    with pytest.raises(TuiMetadataValidationError):
        _validate(actions)


@pytest.mark.parametrize("action_index", [1, 2])
def test_catalog_preserves_hidden_confirmation_and_readback_scope(action_index: int) -> None:
    catalog = TuiWorkbenchCatalogMixin()
    catalog._account_options_cache = {7: [{"value": 613, "label": "Owned account"}]}
    actions = _readback_actions()
    action = actions[action_index]
    action["fields"] = [
        catalog._field_payload(field, action=action, user=SimpleNamespace(id=7))
        for field in action["fields"]
    ]

    account_field = action["fields"][0]
    assert account_field["input_type"] == "hidden"
    assert account_field["value_type"] == "string"
    assert "options" not in account_field
    _validate(actions)


def test_catalog_still_offers_owned_accounts_for_visible_account_input() -> None:
    catalog = TuiWorkbenchCatalogMixin()
    catalog._account_options_cache = {7: [{"value": 613, "label": "Owned account"}]}
    payload = catalog._field_payload(
        {"key": "account_id", "input_type": "number", "required": True},
        user=SimpleNamespace(id=7),
    )

    assert payload["input_type"] == "select"
    assert payload["value_type"] == "integer"
    assert payload["options"] == [
        {"value": "", "label": "请选择账户"},
        {"value": 613, "label": "Owned account"},
    ]


@pytest.mark.parametrize("leak_token", [False, True])
def test_readback_scope_id_can_equal_displayed_asset_code_but_token_stays_secret(
    monkeypatch: pytest.MonkeyPatch, leak_token: bool
) -> None:
    actions = _readback_actions()
    _validate(actions)
    executor = TuiWorkbenchExecutionMixin()
    monkeypatch.setattr(executor, "_metadata", lambda: {"actions": actions}, raising=False)
    payload = {
        "success": True,
        "outcome": "success",
        "preview": {"asset_code": "600000"},
        "continuation": {
            "action_key": actions[1]["key"],
            "input": {
                "account_id": "613",
                "trade_id": "600000",
                "confirmation_token": "opaque-preview-token",
            },
            "expires_at": "2099-01-01T00:00:00Z",
        },
    }
    if leak_token:
        payload["preview"]["note"] = "opaque-preview-token"

    safe_payload, continuation, error = executor._validate_owner_result_continuation(
        action=actions[0], payload=payload, status_code=200
    )

    if leak_token:
        assert error == "tui_result_continuation_leaked"
        assert continuation is None
    else:
        assert error is None
        assert continuation is not None
        assert continuation["input"]["trade_id"] == "600000"
        assert safe_payload["preview"]["asset_code"] == "600000"
        assert "continuation" not in safe_payload
