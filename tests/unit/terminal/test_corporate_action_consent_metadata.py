"""Contracts for the simulated corporate-action consent TUI actions and result view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from apps.terminal.application.tui_metadata_continuation_validation import (
    _validate_result_continuations,
)
from apps.terminal.application.tui_simulated_corporate_action_consent_result import (
    CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
    project_simulated_corporate_action_consent_result,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_corporate_action_consent import (
    RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS,
)

_BASE_ENDPOINT = "/api/simulated-trading/accounts/<int:account_id>/corporate-action-consent/"


def test_published_runtime_metadata_accepts_the_complete_consent_dashboard() -> None:
    """Exercise full runtime injection and validation, including existing dashboard guards."""
    from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository

    payload = PublishedTuiMetadataRepository()._load_published_file()
    keys = {action["key"] for action in payload["actions"]}
    assert {action["key"] for action in RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS} <= keys


def test_account_dashboard_rows_reach_both_owner_preparation_tasks() -> None:
    """Both session previews must be reachable from the selected owner's row."""
    from apps.terminal.application.tui_metadata import (
        _validate_dashboard_collection_actionability,
    )

    architecture = json.loads(
        Path("config/tui/ia/tui_information_architecture.v1.json").read_text(encoding="utf-8")
    )
    screen = next(
        item for item in architecture["published_screens"] if item["key"] == "execution.accounts"
    )
    panel = next(item for item in screen["dashboard_panels"] if item["key"] == "simulated-accounts")
    assert panel["row_actions"][0]["action_key"] == "simulated-trading.account-detail"
    actions = {str(action["key"]): action for action in RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS}
    actions["simulated-trading.accounts"] = {
        "key": "simulated-trading.accounts",
        "screen_key": "execution.accounts",
        "method": "GET",
        "endpoint": "/api/simulated-trading/accounts/",
    }
    _validate_dashboard_collection_actionability(screen=screen, action_by_key=actions)
    _validate_result_continuations(
        actions=list(RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS),
        screens=[screen],
        action_by_key=actions,
    )
    for key in (
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
    ):
        descriptor = next(item for item in panel["row_actions"] if item["action_key"] == key)
        assert descriptor["param_map"] == {"account_id": "account_id"}
        assert descriptor["result_panel_key"] == "simulated-account-workspace"
        account_field = next(
            field for field in actions[key]["fields"] if field["key"] == "account_id"
        )
        assert account_field["binding"] == "body"
        assert account_field["input_type"] == "number"


def _response() -> dict[str, object]:
    """Build the exact safe payload after opaque tokens move to continuation."""

    return {
        "account_id": 42,
        "outcome": "success",
        "consent_status": "not_consented",
        "summary": "来源资料已读取，请核对有效期后单独确认。",
        "blocking_reason": None,
        "source_observed_at": "2026-11-11T08:00:00Z",
        "source_valid_until": "2026-11-11T08:05:00Z",
        "consent_valid_until": "2026-12-01T00:00:00+08:00",
        "consent_token": None,
        "withdrawal_token": None,
        "grant_id": None,
        "grant_version": None,
        "grant_content_hash": None,
        "must_not_execute": True,
    }


def _fields(view: dict[str, object]) -> dict[str, str]:
    """Return projected detail values by their stable field key."""

    rows = cast(list[object], view["fields"])
    result: dict[str, str] = {}
    for item in rows:
        row = cast(dict[str, object], item)
        result[cast(str, row["key"])] = cast(str, row["value"])
    return result


def _action_fields(action: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index one action's metadata fields by key."""

    fields = cast(list[object], action["fields"])
    return {
        cast(str, cast(dict[str, object], item)["key"]): cast(dict[str, object], item)
        for item in fields
    }


def test_actions_use_two_session_bound_result_to_confirmation_flows() -> None:
    actions = {
        cast(str, action["key"]): action for action in RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS
    }
    assert set(actions) == {
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
    }
    assert len(actions) == 4

    for action in actions.values():
        assert action["screen_key"] == "execution.accounts"
        assert action["session_auth_required"] is True
        assert action["raw_debug"] is False
        assert action["method"] == "POST"

    consent_prepare = actions[CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY]
    consent_confirm = actions[CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY]
    withdrawal_prepare = actions[CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY]
    withdrawal = actions[CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY]

    assert consent_prepare["endpoint"] == f"{_BASE_ENDPOINT}prepare/"
    assert consent_prepare["risk"] == "read"
    assert consent_prepare["effect"] == "read"
    assert consent_prepare["confirmation_required"] is False
    assert consent_prepare["audit_required"] is False
    choice_fields = _action_fields(consent_prepare)
    assert set(choice_fields) == {
        "account_id",
        "cash_dividend",
        "tax_assessment",
        "tax_withholding",
    }
    for key in ("cash_dividend", "tax_assessment", "tax_withholding"):
        assert choice_fields[key]["input_type"] == "checkbox"
        assert choice_fields[key]["value_type"] == "boolean"
        assert choice_fields[key]["required"] is False
        assert choice_fields[key]["default"] is False
    assert consent_prepare["result_continuation"] == {
        "target_action_key": CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
        "field_map": {
            "account_id": "account_id",
            "consent_token": "consent_token",
        },
    }

    assert consent_confirm["endpoint"] == _BASE_ENDPOINT
    assert consent_confirm["risk"] == "write"
    assert consent_confirm["effect"] == "update"
    assert consent_confirm["audit_required"] is True
    assert consent_confirm["confirmation_required"] is True

    assert withdrawal_prepare["endpoint"] == f"{_BASE_ENDPOINT}withdraw/prepare/"
    assert withdrawal_prepare["risk"] == "read"
    assert withdrawal_prepare["effect"] == "read"
    assert withdrawal_prepare["confirmation_required"] is False
    assert withdrawal_prepare["audit_required"] is False
    assert withdrawal_prepare["result_continuation"] == {
        "target_action_key": CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
        "field_map": {
            "account_id": "account_id",
            "withdrawal_token": "withdrawal_token",
        },
    }

    assert withdrawal["endpoint"] == f"{_BASE_ENDPOINT}withdraw/"
    assert withdrawal["risk"] == "write"
    assert withdrawal["effect"] == "update"
    assert withdrawal["audit_required"] is True
    assert withdrawal["confirmation_required"] is True

    for action, token_key in (
        (consent_confirm, "consent_token"),
        (withdrawal, "withdrawal_token"),
    ):
        fields = _action_fields(action)
        assert set(fields) == {"account_id", token_key, "confirmed"}
        for hidden_key in ("account_id", token_key):
            hidden = fields[hidden_key]
            assert hidden["binding"] == "body"
            assert hidden["input_type"] == "hidden"
            assert hidden["value_type"] == "string"
            assert hidden["required"] is True
            assert hidden["presentation_semantic"] == "api_token"
            assert hidden.get("default") in (None, "")
        confirmation = fields["confirmed"]
        assert confirmation["binding"] == "body"
        assert confirmation["input_type"] == "select"
        assert confirmation["value_type"] == "boolean"
        assert confirmation["required"] is True
        assert confirmation.get("default") in (None, "")
        options = cast(list[object], confirmation["options"])
        assert cast(dict[str, object], options[0])["value"] == ""

    _validate_result_continuations(
        actions=list(RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS),
        screens=[],
        action_by_key=actions,
    )


def test_result_shows_source_clock_consent_expiry_and_simulation_boundary() -> None:
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        _response(),
        http_status=200,
        requested_params={"account_id": 42},
    )

    values = _fields(view)
    assert view["outcome"] == "success"
    assert view["status"] == "资料已准备，等待单独确认"
    assert values["account_id"] == "42"
    assert values["source_observed_at"] == "2026-11-11T08:00:00Z"
    assert values["source_valid_until"] == "2026-11-11T08:05:00Z"
    assert values["consent_valid_until"] == "2026-12-01T00:00:00+08:00"
    assert values["blocking_reason"] == "无"
    assert "现金分红模拟权益" in cast(str, view["business_summary"])
    assert "支付日模拟到账" in cast(str, view["business_summary"])
    assert "不会实际入账" in cast(str, view["business_summary"])
    assert "consent_token" not in repr(view)
    assert "withdrawal_token" not in repr(view)


@pytest.mark.parametrize(
    ("payload_account_id", "requested_account_id", "expected_reason"),
    [
        (43, 42, "simulated_action_consent_account_scope_mismatch"),
        (42, 43, "simulated_action_consent_account_scope_mismatch"),
        (True, 42, "simulated_action_consent_response_invalid"),
        (42, "042", "simulated_action_consent_account_scope_mismatch"),
    ],
)
def test_result_rejects_cross_account_or_noncanonical_scope(
    payload_account_id: object,
    requested_account_id: object,
    expected_reason: str,
) -> None:
    payload = _response()
    payload["account_id"] = payload_account_id
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        payload,
        http_status=200,
        requested_params={"account_id": requested_account_id},
    )

    assert view["outcome"] == "blocked"
    assert view["blocking_reason"] == expected_reason


def test_result_preserves_a_bounded_block_reason() -> None:
    payload = _response()
    payload["outcome"] = "blocked"
    payload["blocking_reason"] = "simulated_action_source_expired"
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
        payload,
        http_status=200,
        requested_params={"account_id": 42},
    )

    assert view["outcome"] == "blocked"
    assert view["blocking_reason"] == "simulated_action_source_expired"
    assert _fields(view)["blocking_reason"] == "来源资料已过期，请重新读取核对。"


def test_expired_withdrawal_copy_does_not_claim_current_write_permission() -> None:
    payload = _response()
    payload["consent_status"] = "expired"
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
        payload,
        http_status=200,
        requested_params={"account_id": 42},
    )
    assert _fields(view)["consent_status"] == "授权已过期，仍可撤回记录"
    assert _fields(view)["outcome"] == "已完成"
    assert "不会实际入账" in view["business_summary"]


def test_unavailable_service_uses_ordinary_copy_without_transport_details() -> None:
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        {},
        http_status=403,
        requested_params={"account_id": 42},
    )
    assert _fields(view) == {"blocking_reason": "授权服务暂不可用，请稍后重新读取。"}
    assert view["blocking_reason"] == "simulated_action_consent_request_unavailable"


def test_result_rejects_and_never_echoes_a_token_in_display_payload() -> None:
    payload = _response()
    payload["consent_token"] = "private-consent-token"
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        payload,
        http_status=200,
        requested_params={"account_id": 42},
    )

    assert view["outcome"] == "blocked"
    assert view["blocking_reason"] == "simulated_action_consent_response_invalid"
    assert "private-consent-token" not in repr(view)


def test_result_rejects_malformed_source_clock_and_missing_execution_boundary() -> None:
    malformed_clock = _response()
    malformed_clock["source_observed_at"] = "2026-11-11T08:00:00"
    view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
        malformed_clock,
        http_status=200,
        requested_params={"account_id": 42},
    )
    assert view["outcome"] == "blocked"

    unsafe = _response()
    unsafe["must_not_execute"] = False
    unsafe_view = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
        unsafe,
        http_status=200,
        requested_params={"account_id": 42},
    )
    assert unsafe_view["outcome"] == "blocked"


@pytest.mark.parametrize(
    ("action_key", "expected_status", "account_id", "grant_version"),
    [
        (
            CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
            "已有有效授权，无需重复同意",
            42,
            None,
        ),
        (
            CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
            "没有待撤回授权",
            1,
            "1",
        ),
    ],
)
def test_noop_prepare_is_terminal_without_confirmation_credentials(
    action_key: str,
    expected_status: str,
    account_id: int,
    grant_version: str | None,
) -> None:
    payload = _response()
    payload["account_id"] = account_id
    payload["outcome"] = "noop"
    payload["consent_status"] = "already_current" if grant_version is None else "not_consented"
    payload["summary"] = "当前授权状态无需变更。"
    payload["blocking_reason"] = None
    payload["grant_version"] = grant_version

    view = project_simulated_corporate_action_consent_result(
        action_key,
        payload,
        http_status=200,
        requested_params={"account_id": account_id},
    )

    assert view["outcome"] == "noop"
    assert view["status"] == expected_status
    assert view["blocking_reason"] == ""
    assert _fields(view)["blocking_reason"] == "无"
    assert "等待单独确认" not in cast(str, view["status"])
    assert "consent_token" not in repr(view)
    assert "withdrawal_token" not in repr(view)
