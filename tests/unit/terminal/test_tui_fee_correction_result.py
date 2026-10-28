"""TUI contracts for owner fee-policy and correction-result projections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest

from apps.simulated_trading.application.fee_correction_evidence import MAX_UPLOAD_BYTES
from apps.terminal.application.tui_fee_correction_result import (
    project_fee_correction_result,
)
from apps.terminal.application.tui_metadata_continuation_validation import (
    _validate_result_continuations,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_fee_correction import (
    RUNTIME_FEE_CORRECTION_ACTIONS,
)

_POLICY_ACTION = "simulated-trading.fee-correction-policy"
_POLICY_SAVE_ACTION = "simulated-trading.fee-correction-policy-save"
_POLICY_DISABLE_ACTION = "simulated-trading.fee-correction-policy-disable"
_PREVIEW_ACTION = "simulated-trading.fee-correction-preview"
_CONFIRM_ACTION = "simulated-trading.fee-correction-confirm"
_HEAD_ACTION = "simulated-trading.fee-correction-head"
_RECOVER_ACTION = "simulated-trading.fee-correction-recover"
_DISCOVER_ACTION = "simulated-trading.fee-correction-discover"
_SOURCE_LOCATOR = "fb0f96e3-277c-4ee0-91ee-87be88781037"


def _action_by_key(key: str) -> dict[str, Any]:
    action = next(action for action in RUNTIME_FEE_CORRECTION_ACTIONS if action["key"] == key)
    return action


def _policy_payload(
    *,
    version: int = 0,
    enabled: bool = False,
    allow_operator_attested_upload: bool = False,
    ledger_currency: str = "",
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "policy": {
            "account_id": 12,
            "version": version,
            "enabled": enabled,
            "allow_operator_attested_upload": allow_operator_attested_upload,
            "ledger_currency": ledger_currency,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "updated_by_id": 71,
            "assurance_class": "operator_attested_upload",
            "assurance_notice": "费用材料由账户所有者声明，不代表券商或发行方认证。",
        },
    }


def _preview_payload(*, status: str = "preview") -> dict[str, Any]:
    if status == "already_applied":
        return {
            "success": True,
            "outcome": "noop",
            "status": "already_applied",
            "preview": None,
            "receipt": {
                "event_id": 901,
                "account_id": 12,
                "trade_id": 77,
                "revision": 1,
                "payload_hash": "sha256:private-payload-digest",
                "replayed": True,
            },
            "assurance_notice": "费用材料由账户所有者声明，不代表券商或发行方认证。",
            "message": "本次更正已入账，无需再次确认。",
        }
    return {
        "success": True,
        "outcome": "success",
        "status": "preview",
        "preview": {
            "account_id": 12,
            "trade_id": 77,
            "asset_code": "600000.SH",
            "ledger_currency": "CNY",
            "expected_revision": 0,
            "expected_predecessor_id": None,
            "source_locator": _SOURCE_LOCATOR,
            "content_sha256": "private-content-digest",
            "payload_sha256": "private-payload-digest",
            "assurance_class": "operator_attested_upload",
            "source_observed_at": "2026-10-26T15:00:00+08:00",
            "verified_at": "2026-10-27T08:01:00+08:00",
            "stored_at": "2026-10-27T08:00:00+08:00",
            "as_of": "2026-10-27T08:02:00+08:00",
            "previous_fee_components": {
                "commission": "7.00",
                "transfer_fee": "0.10",
                "stamp_duty": "0.00",
            },
            "revised_fee_components": {
                "commission": "9.00",
                "transfer_fee": "0.10",
                "stamp_duty": "0.00",
            },
            "delta": {
                "commission": "2.00",
                "transfer_fee": "0.00",
                "stamp_duty": "0.00",
                "total_fee_delta": "2.00",
                "cash_delta": "-2.00",
            },
        },
        "receipt": None,
        "assurance_notice": "费用材料由账户所有者声明，不代表券商或发行方认证。",
        "message": "已保存并核对材料，费用更正尚未入账。",
        "continuation": {
            "action_key": _CONFIRM_ACTION,
            "input": {
                "account_id": "12",
                "trade_id": "77",
                "confirmation_token": "private-confirmation-token",
            },
            "expires_at": "2026-10-27T08:05:00Z",
        },
    }


def _field_map(view: Mapping[str, Any]) -> dict[str, str]:
    return {field["key"]: field["value"] for field in view["fields"]}


def test_actions_are_session_scoped_and_use_exact_fee_api_contracts() -> None:
    actions = {action["key"]: action for action in RUNTIME_FEE_CORRECTION_ACTIONS}

    assert set(actions) == {
        _POLICY_ACTION,
        _POLICY_SAVE_ACTION,
        _POLICY_DISABLE_ACTION,
        _PREVIEW_ACTION,
        _CONFIRM_ACTION,
        _HEAD_ACTION,
        _RECOVER_ACTION,
        _DISCOVER_ACTION,
    }
    for action in actions.values():
        assert action["screen_key"] == "execution.accounts"
        assert action["audience"] == "authenticated"
        assert action["session_auth_required"] is True
        assert action["raw_debug"] is False

    preview = actions[_PREVIEW_ACTION]
    schema = json.loads(
        Path("config/tui/schema/tui_metadata.schema.v3.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema["$defs"]["resultContinuation"]).validate(
        preview["result_continuation"]
    )
    assert preview["endpoint"] == (
        "/api/simulated-trading/accounts/<int:account_id>/trades/"
        "<int:trade_id>/fee-correction-preview/"
    )
    assert preview["confirmation_required"] is True
    assert preview["result_continuation"] == {
        "target_action_key": _CONFIRM_ACTION,
        "field_map": {
            "account_id": "account_id",
            "trade_id": "trade_id",
            "confirmation_token": "confirmation_token",
        },
        "reuse_source_idempotency_key": True,
        "readback_action_key": _HEAD_ACTION,
        "readback_scope_map": {"source_locator": "preview.source_locator"},
    }
    upload_field = next(field for field in preview["fields"] if field["key"] == "csv_text")
    assert upload_field["input_type"] == "file"
    assert upload_field["file_name_field"] == "original_filename"
    assert upload_field["max_bytes"] == MAX_UPLOAD_BYTES

    policy_save = actions[_POLICY_SAVE_ACTION]
    field_keys = {field["key"]: field for field in policy_save["fields"]}
    assert field_keys["account_id"]["binding"] == "body"
    assert field_keys["account_id"]["input_type"] == "hidden"
    assert field_keys["ledger_currency"]["required"] is True
    for key in ("enabled", "allow_operator_attested_upload", "attestation_acknowledged"):
        field = field_keys[key]
        assert field["input_type"] == "select"
        assert field.get("default") in (None, "")
        assert field["options"][0]["value"] == ""
    assert field_keys["valid_from"]["required"] is False
    assert field_keys["valid_until"]["required"] is False
    policy_disable_fields = {
        field["key"]: field for field in actions[_POLICY_DISABLE_ACTION]["fields"]
    }
    assert policy_disable_fields["account_id"]["binding"] == "body"
    assert policy_disable_fields["account_id"]["input_type"] == "hidden"

    confirm = actions[_CONFIRM_ACTION]
    assert confirm["endpoint"].endswith("/fee-corrections/confirm/")
    assert confirm["confirmation_required"] is True
    assert {field["key"] for field in confirm["fields"]} == {
        "account_id",
        "trade_id",
        "confirmation_token",
    }
    assert all(field["input_type"] == "hidden" for field in confirm["fields"])

    _validate_result_continuations(
        actions=list(RUNTIME_FEE_CORRECTION_ACTIONS),
        screens=[],
        action_by_key=actions,
    )


@pytest.mark.parametrize("state", ["completed", "unresolved", "fenced", "unknown"])
def test_material_discovery_keeps_owner_state_and_exact_public_locator(state: str) -> None:
    payload = _discovery_payload(state)
    view = project_fee_correction_result(
        _DISCOVER_ACTION,
        payload,
        http_status=200,
        requested_params={"account_id": 12, "trade_id": 77, "limit": 1},
    )
    assert view["kind"] == "detail"
    assert state in repr(view["sections"])
    assert _SOURCE_LOCATOR in repr(view)
    steps = view["next_steps"]
    preview_steps = [step for step in steps if step["action_key"] == _PREVIEW_ACTION]
    assert len(preview_steps) == (1 if state == "unresolved" else 0)
    if preview_steps:
        assert preview_steps[0]["params"] == {
            "account_id": 12,
            "trade_id": 77,
            "source_locator": _SOURCE_LOCATOR,
        }
    assert any(step["params"].get("cursor") == _SOURCE_LOCATOR for step in steps)
    assert "本页" in view["business_summary"]
    assert not any(step["action_key"] == _POLICY_DISABLE_ACTION for step in steps)
    if state == "fenced":
        assert "整个账户" in repr(view)
        assert "不代表" in repr(view)
        assert view["_fee_recovery"][0]["source_locator"] == _SOURCE_LOCATOR
    else:
        assert view["_fee_recovery"] == []


def _discovery_payload(state: str = "fenced") -> dict[str, Any]:
    """Represent one owner discovery page, without making a database claim."""

    return {
        "success": True,
        "outcome": "success",
        "recovery": {
            "account_id": 12,
            "trade_id": 77,
            "items": [
                {
                    "source_locator": _SOURCE_LOCATOR,
                    "state": state,
                    "content_sha256": "a" * 64,
                    "payload_sha256": "b" * 64,
                    "stored_at": "2026-10-28T01:00:00Z",
                    "expected_revision": 0,
                    "expected_predecessor_id": None,
                    "binding_policy_version": 1,
                    "current_policy_version": 2,
                    "reason_code": (
                        "FEE_CORRECTION_RECOVERY_POLICY_SUPERSEDED" if state == "fenced" else None
                    ),
                }
            ],
            "has_more": True,
            "next_cursor": _SOURCE_LOCATOR,
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"current_policy_version": 1},
        {"current_policy_version": None},
        {"current_policy_version": True},
        {"reason_code": None},
        {"reason_code": "FEE_CORRECTION_RECOVERY_COMPLETED"},
        {"source_locator": _SOURCE_LOCATOR.upper()},
        {"stored_at": "2026-10-28T01:00:00"},
        {"state": "cancelled"},
        {"payload_sha256": "private-token"},
    ],
)
def test_unverified_discovery_cannot_offer_fenced_exit(change: dict[str, Any]) -> None:
    payload = _discovery_payload()
    payload["recovery"]["items"][0].update(change)
    view = project_fee_correction_result(
        _DISCOVER_ACTION,
        payload,
        http_status=200,
        requested_params={"account_id": 12, "trade_id": 77},
    )
    assert view["outcome"] == "blocked"
    assert "_fee_recovery" not in view
    assert not view["next_steps"]


@pytest.mark.parametrize(
    "change", [{"account_id": 13}, {"trade_id": 78}, {"next_cursor": None}, {"has_more": "true"}]
)
def test_foreign_or_inconsistent_page_cannot_offer_recovery(change: dict[str, Any]) -> None:
    payload = _discovery_payload()
    payload["recovery"].update(change)
    view = project_fee_correction_result(
        _DISCOVER_ACTION,
        payload,
        http_status=200,
        requested_params={"account_id": 12, "trade_id": 77},
    )
    assert view["outcome"] == "blocked"
    assert "_fee_recovery" not in view


@pytest.mark.parametrize("action_key,valid", [(_DISCOVER_ACTION, True), (_HEAD_ACTION, False)])
def test_real_workbench_envelope_separates_proof_and_rejects_unreceipted_success(
    monkeypatch: pytest.MonkeyPatch,
    action_key: str,
    valid: bool,
) -> None:
    """Exercise the execution/projector boundary with no ORM or owner request."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    action = deepcopy(_action_by_key(action_key))
    payload = (
        _discovery_payload()
        if valid
        else {
            "success": True,
            "outcome": "success",
            "head": {
                "account_id": 12,
                "trade_id": 77,
                "revision": 0,
                "expected_predecessor_id": None,
                "as_of": "2026-10-28T01:00:00Z",
                "request_receipt": None,
            },
        }
    )
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(
            execute=lambda **kwargs: {"status_code": 200, "payload": payload}
        ),
    )
    monkeypatch.setattr(service, "_action_by_key", lambda *args, **kwargs: action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda user: {"read"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda user: False)
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: dict(field))
    monkeypatch.setattr(service, "_action_payload", lambda *args, **kwargs: {"key": action_key})
    monkeypatch.setattr(service, "_metadata", lambda: {"screens": []})
    result = service.run_action(
        action_key=action_key,
        params=(
            {"account_id": "12", "trade_id": "77", "source_locator": _SOURCE_LOCATOR}
            if not valid
            else {"account_id": 12, "trade_id": 77}
        ),
        user=SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_staff=False),
    )
    assert result["outcome"] == ("success" if valid else "blocked")
    assert "_fee_recovery" not in result["view_model"]
    if valid:
        assert result["fee_recovery"][0]["source_locator"] == _SOURCE_LOCATOR
    else:
        assert "fee_recovery" not in result


def test_policy_projection_preserves_empty_currency_null_window_and_version_cas() -> None:
    view = project_fee_correction_result(
        _POLICY_ACTION,
        _policy_payload(),
        http_status=200,
        requested_params={"account_id": "12"},
    )

    assert view["outcome"] == "success"
    assert view["status"] == "材料策略已停用"
    assert view["assurance_notice"] == "费用材料由账户所有者声明，不代表券商或发行方认证。"
    assert "version" not in _field_map(view)
    configure_step = next(
        step for step in view["next_steps"] if step["action_key"] == _POLICY_SAVE_ACTION
    )
    assert configure_step["params"] == {
        "account_id": 12,
        "expected_version": 0,
        "ledger_currency": "",
        "valid_from": None,
        "valid_until": None,
    }
    assert not any(step["action_key"] == _POLICY_DISABLE_ACTION for step in view["next_steps"])


def test_enabled_policy_without_material_permission_still_explains_unavailability() -> None:
    view = project_fee_correction_result(
        _POLICY_ACTION,
        _policy_payload(enabled=True, allow_operator_attested_upload=False, ledger_currency="CNY"),
        http_status=200,
        requested_params={"account_id": 12},
    )
    assert "当前不能进行费用更正" in view["business_summary"]
    assert _field_map(view)["operator_attested_upload"] == "不允许"


def test_enabled_policy_projection_offers_explicit_disable_with_exact_current_state() -> None:
    view = project_fee_correction_result(
        _POLICY_ACTION,
        _policy_payload(
            version=4,
            enabled=True,
            allow_operator_attested_upload=True,
            ledger_currency="CNY",
            valid_from="2026-10-27T00:00:00+08:00",
            valid_until=None,
        ),
        http_status=200,
        requested_params={"account_id": 12},
    )

    disable_step = next(
        step for step in view["next_steps"] if step["action_key"] == _POLICY_DISABLE_ACTION
    )
    assert disable_step["params"] == {
        "account_id": 12,
        "expected_version": 4,
        "enabled": False,
        "allow_operator_attested_upload": False,
        "ledger_currency": "CNY",
        "valid_from": "2026-10-27T00:00:00+08:00",
        "valid_until": None,
        "attestation_acknowledged": False,
    }
    assert "revision" not in _field_map(view)


def test_preview_projection_keeps_exact_money_and_clock_values_without_private_material() -> None:
    view = project_fee_correction_result(
        _PREVIEW_ACTION,
        _preview_payload(),
        http_status=200,
        requested_params={"account_id": "12", "trade_id": "77"},
    )
    fields = _field_map(view)

    assert view["outcome"] == "success"
    assert view["status"] == "预览完成；尚未入账"
    assert fields["previous_commission"] == "7.00"
    assert fields["revised_commission"] == "9.00"
    assert fields["cash_delta"] == "-2.00"
    assert fields["source_observed_at"] == "2026-10-26T15:00:00+08:00"
    assert fields["verified_at"] == "2026-10-27T08:01:00+08:00"
    assert fields["stored_at"] == "2026-10-27T08:00:00+08:00"
    assert fields["as_of"] == "2026-10-27T08:02:00+08:00"
    assert fields["assurance"] == "账户所有者声明；未经券商或发行方认证。"
    serialized = repr(view)
    for private_value in (
        "private-content-digest",
        "private-payload-digest",
        "private-confirmation-token",
        "expected_revision",
        "expected_predecessor_id",
    ):
        assert private_value not in serialized
    assert not any(step.get("action_key") == _CONFIRM_ACTION for step in view["next_steps"])


def test_preview_provides_copyable_recovery_reference_without_exposing_submission_key() -> None:
    view = project_fee_correction_result(_PREVIEW_ACTION, _preview_payload(), http_status=200)
    reference = next(field for field in view["fields"] if field["key"] == "source_locator")
    assert reference["value"] == _SOURCE_LOCATOR
    assert reference["presentation"] == "copyable"
    assert "刷新" in view["business_summary"]
    assert "idempotency" not in repr(view).lower()


def test_recovery_action_uses_existing_read_only_owner_route_and_explicit_locator() -> None:
    action = _action_by_key(_RECOVER_ACTION)
    assert action["endpoint"] == _action_by_key(_HEAD_ACTION)["endpoint"]
    assert action["method"] == "GET"
    assert action["effect"] == "read"
    assert action["confirmation_required"] is False
    assert action["session_auth_required"] is True
    fields = {field["key"]: field for field in action["fields"]}
    assert set(fields) == {"account_id", "trade_id", "source_locator"}
    assert fields["account_id"]["binding"] == "path"
    assert fields["trade_id"]["binding"] == "path"
    assert fields["source_locator"]["binding"] == "path"
    assert "/recovery/<uuid:source_locator>/head/" in action["endpoint"]
    assert fields["source_locator"]["required"] is True
    assert all(field["input_type"] != "hidden" for field in fields.values())


@pytest.mark.parametrize(
    "outcome,receipt,expected",
    [
        ("partial", None, "partial"),
        ("success", None, "blocked"),
        ("success", {"replayed": False}, "blocked"),
        ("success", {"replayed": True}, "success"),
        ("success", {"replayed": True, "trade_id": 78}, "blocked"),
    ],
)
def test_material_recovery_requires_matching_original_receipt(
    outcome: str, receipt: dict[str, object] | None, expected: str
) -> None:
    request_receipt = None
    if receipt is not None:
        request_receipt = {
            "event_id": 901,
            "account_id": 12,
            "trade_id": 77,
            "revision": 1,
            "payload_hash": "private-payload-digest",
            **receipt,
        }
    payload = {
        "success": True,
        "outcome": outcome,
        "head": {
            "account_id": 12,
            "trade_id": 77,
            "revision": 1,
            "expected_predecessor_id": 901,
            "as_of": "2026-10-27T08:02:00+08:00",
            "request_receipt": request_receipt,
        },
    }
    view = project_fee_correction_result(
        _RECOVER_ACTION,
        payload,
        http_status=200,
        requested_params={"account_id": 12, "trade_id": 77, "source_locator": _SOURCE_LOCATOR},
    )
    assert view["outcome"] == expected
    assert view["next_steps"] == []
    assert "private-payload-digest" not in repr(view)


@pytest.mark.parametrize(
    "revision,predecessor,expected",
    [(0, None, "partial"), (1, 901, "partial"), (0, 901, "blocked"), (1, None, "blocked")],
)
def test_pending_material_recovery_preserves_valid_head_revision(
    revision: int, predecessor: int | None, expected: str
) -> None:
    view = project_fee_correction_result(
        _RECOVER_ACTION,
        {
            "success": True,
            "outcome": "partial",
            "head": {
                "account_id": 12,
                "trade_id": 77,
                "revision": revision,
                "expected_predecessor_id": predecessor,
                "as_of": "2026-10-27T08:02:00+08:00",
                "request_receipt": None,
            },
        },
        http_status=200,
        requested_params={"account_id": 12, "trade_id": 77, "source_locator": _SOURCE_LOCATOR},
    )
    assert view["outcome"] == expected


def test_already_applied_preview_shows_receipt_state_without_confirmation() -> None:
    view = project_fee_correction_result(
        _PREVIEW_ACTION,
        _preview_payload(status="already_applied"),
        http_status=200,
        requested_params={"account_id": "12", "trade_id": "77"},
    )

    assert view["outcome"] == "noop"
    assert view["status"] == "已入账；无需再次确认"
    assert not any(step["action_key"] == _CONFIRM_ACTION for step in view["next_steps"])
    serialized = repr(view)
    assert "private-payload-digest" not in serialized
    assert "event_id" not in serialized
    assert "revision" not in serialized


def test_confirm_projection_displays_posting_outcome_without_receipt_internals() -> None:
    view = project_fee_correction_result(
        _CONFIRM_ACTION,
        {
            "success": True,
            "receipt": {
                "event_id": 901,
                "account_id": 12,
                "trade_id": 77,
                "revision": 1,
                "payload_hash": "private-payload-digest",
                "replayed": False,
            },
            "message": "费用更正已入账。",
        },
        http_status=200,
        requested_params={"account_id": "12", "trade_id": "77"},
    )

    assert view["outcome"] == "success"
    assert view["status"] == "费用更正已入账"
    serialized = repr(view)
    assert "private-payload-digest" not in serialized
    assert "event_id" not in serialized
    assert "revision" not in serialized


def test_head_partial_stays_unresolved_and_matching_receipt_is_safe_to_show() -> None:
    partial = project_fee_correction_result(
        _HEAD_ACTION,
        {
            "success": True,
            "outcome": "partial",
            "message": "尚未找到原请求回执。",
            "head": {
                "account_id": 12,
                "trade_id": 77,
                "revision": 1,
                "expected_predecessor_id": 900,
                "as_of": "2026-10-27T08:02:00+08:00",
                "request_receipt": None,
            },
        },
        http_status=200,
        requested_params={"account_id": "12", "trade_id": "77"},
    )
    assert partial["outcome"] == "partial"
    assert partial["status"] == "结果仍待核对"
    assert "不要另建请求" in partial["message"]
    assert "revision" not in repr(partial)

    resolved = project_fee_correction_result(
        _HEAD_ACTION,
        {
            "success": True,
            "outcome": "success",
            "message": "已核对原请求，费用更正已入账。",
            "head": {
                "account_id": 12,
                "trade_id": 77,
                "revision": 1,
                "expected_predecessor_id": 901,
                "as_of": "2026-10-27T08:02:00+08:00",
                "request_receipt": {
                    "event_id": 901,
                    "account_id": 12,
                    "trade_id": 77,
                    "revision": 1,
                    "payload_hash": "private-payload-digest",
                    "replayed": True,
                },
            },
        },
        http_status=200,
        requested_params={"account_id": "12", "trade_id": "77"},
    )
    assert resolved["outcome"] == "success"
    assert resolved["status"] == "已核对原请求"
    assert "private-payload-digest" not in repr(resolved)


def test_malformed_or_failed_responses_are_bounded_without_raw_owner_errors() -> None:
    malformed = project_fee_correction_result(
        _PREVIEW_ACTION,
        _preview_payload() | {"preview": None},
        http_status=200,
        requested_params={"account_id": "12", "trade_id": "77"},
    )
    assert malformed["outcome"] == "blocked"

    failed = project_fee_correction_result(
        _PREVIEW_ACTION,
        {"success": False, "error": "private raw SQL diagnostic"},
        http_status=503,
        requested_params={"account_id": "12", "trade_id": "77"},
    )
    assert failed["outcome"] == "failed"
    assert "private raw SQL diagnostic" not in repr(failed)
