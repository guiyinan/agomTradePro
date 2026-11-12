"""Strict safe projection tests for versioned corporate-action consent results."""

from __future__ import annotations

from typing import cast

import pytest

from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA as _V1_SCHEMA,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA as _V2_SCHEMA,
)
from apps.terminal.application.tui_simulated_corporate_action_consent_result import (
    CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
    project_simulated_corporate_action_consent_result,
)

_TERMS_VERSION = "simulated-corporate-action-owner-terms.v2"
_TERMS_SHA256 = "a" * 64
_CASH = "simulated_corporate_action_stage_write"
_ASSESS = "simulated.corporate_action_tax.assess"
_WITHHOLD = "simulated.corporate_action_tax.withhold"
_TERMS_TEXT = (
    "现金分红模拟权益和模拟到账。\n\n"
    "模拟税额评估\n核对来源、持仓历史和适用政策。\n\n"
    "模拟税额扣缴\n仅从模拟可用资金扣除。\n\n"
    "授权范围与限制：\n缺少依据时阻断；不产生真实交易。"
)


def _legacy_response() -> dict[str, object]:
    """Build the exact legacy response shape accepted before capability output."""
    return {
        "account_id": 42,
        "outcome": "success",
        "consent_status": "awaiting_confirmation",
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


def _expanded_v1_response() -> dict[str, object]:
    """Build the producer's expanded V1/empty scope without implying tax rights."""
    return {
        **_legacy_response(),
        "grant_schema": None,
        "selected_capabilities": [],
        "capability_labels": [],
        "terms_version": None,
        "terms_sha256": None,
        "terms_text": "",
    }


def _v2_response() -> dict[str, object]:
    """Build one complete, explicitly selected V2 consent preparation."""
    return {
        **_legacy_response(),
        "grant_schema": _V2_SCHEMA,
        "selected_capabilities": [_ASSESS],
        "capability_labels": ["模拟税额评估"],
        "terms_version": _TERMS_VERSION,
        "terms_sha256": _TERMS_SHA256,
        "terms_text": _TERMS_TEXT,
    }


def _field_values(view: dict[str, object]) -> dict[str, str]:
    """Index rendered detail values by their stable internal field key."""
    fields = cast(list[object], view["fields"])
    result: dict[str, str] = {}
    for item in fields:
        row = cast(dict[str, object], item)
        result[cast(str, row["key"])] = cast(str, row["value"])
    return result


def _project(action_key: str, payload: object) -> dict[str, object]:
    """Project one same-account server result through the user-facing boundary."""
    return project_simulated_corporate_action_consent_result(
        action_key,
        payload,
        http_status=200,
        requested_params={"account_id": 42},
    )


@pytest.mark.parametrize(
    ("action", "status"),
    [
        (CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY, "stored"),
        (CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY, "expired"),
        (CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY, "revoked"),
    ],
)
def test_unknown_historical_terms_do_not_prevent_withdrawal_display(
    action: str, status: str
) -> None:
    payload = _v2_response()
    payload.update(
        consent_status=status,
        capability_labels=[],
        terms_version=None,
        terms_sha256=None,
        terms_text="",
    )
    view = _project(action, payload)
    assert view["outcome"] == "success"
    assert "暂无法核对" in _field_values(view)["selected_capabilities"]
    assert _ASSESS not in repr(view)
    assert "terms_text" not in _field_values(view)
    denied = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, payload)
    assert denied["outcome"] == "blocked"


def test_legacy_fourteen_field_v1_result_keeps_existing_projection() -> None:
    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, _legacy_response())

    assert view["outcome"] == "success"
    values = _field_values(view)
    assert values["account_id"] == "42"
    assert values["source_observed_at"] == "2026-11-11T08:00:00Z"
    assert values["source_valid_until"] == "2026-11-11T08:05:00Z"
    assert values["consent_valid_until"] == "2026-12-01T00:00:00+08:00"
    assert "不会实际入账" in cast(str, view["business_summary"])


def test_expanded_v1_result_has_no_capability_or_terms_claim() -> None:
    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, _expanded_v1_response())

    assert view["outcome"] == "success"
    assert "selected_capabilities" not in _field_values(view)
    assert "terms_text" not in _field_values(view)
    assert _CASH not in repr(view)
    assert _ASSESS not in repr(view)


def test_ready_v2_result_shows_selected_labels_full_terms_and_no_protocol_values() -> None:
    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, _v2_response())

    values = _field_values(view)
    assert view["outcome"] == "success"
    assert values["selected_capabilities"] == "模拟税额评估"
    assert values["terms_text"] == _TERMS_TEXT
    summary = cast(str, view["business_summary"])
    assert "本次操作只保存或撤回所选授权" in summary
    assert "不会评估税额、扣缴模拟资金、模拟入账或下单" in summary
    rendered = repr(view)
    assert _V2_SCHEMA not in rendered
    assert _TERMS_VERSION not in rendered
    assert _TERMS_SHA256 not in rendered
    assert _ASSESS not in rendered
    assert _CASH not in rendered
    assert _WITHHOLD not in rendered
    assert "consent_token" not in rendered and "withdrawal_token" not in rendered


def test_active_v2_result_shows_existing_scope_without_claiming_new_confirmation() -> None:
    payload = _v2_response()
    payload["consent_status"] = "active"
    payload["summary"] = "已有有限期的模拟授权。"

    view = _project(CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY, payload)

    assert view["outcome"] == "success"
    assert _field_values(view)["selected_capabilities"] == "模拟税额评估"
    assert _field_values(view)["terms_text"] == _TERMS_TEXT
    assert "等待单独确认" not in cast(str, view["status"])


def test_blocked_v2_without_usable_terms_preserves_withdrawal_result_safely() -> None:
    payload = _v2_response()
    payload.update(
        {
            "outcome": "blocked",
            "consent_status": "active",
            "blocking_reason": "simulated_action_consent_terms_unavailable",
            "summary": "已有授权的条款暂时无法核对，但仍可撤回。",
            "selected_capabilities": [_ASSESS],
            "capability_labels": [],
            "terms_version": None,
            "terms_sha256": None,
            "terms_text": "",
            "withdrawal_token": None,
            "grant_id": "grant-1",
            "grant_version": "version-1",
            "grant_content_hash": "b" * 64,
        }
    )

    view = _project(CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY, payload)

    assert view["outcome"] == "blocked"
    assert _field_values(view)["blocking_reason"] != _ASSESS
    assert _ASSESS not in repr(view)
    assert _TERMS_VERSION not in repr(view)
    assert _TERMS_SHA256 not in repr(view)
    assert "现有授权范围暂无法核对" in _field_values(view)["selected_capabilities"]
    assert "仍可撤回" in cast(str, view["business_summary"])


def test_withdrawal_receipt_accepts_expanded_empty_v1_scope() -> None:
    payload = _expanded_v1_response()
    payload.update(
        {
            "outcome": "success",
            "consent_status": "expired",
            "summary": "已找到本人尚未撤销的原授权，请核对后明确撤销。",
            "grant_id": "grant-1",
            "grant_version": "version-1",
            "grant_content_hash": "c" * 64,
        }
    )

    view = _project(CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY, payload)

    assert view["outcome"] == "success"
    assert _field_values(view)["consent_status"] == "授权已过期，仍可撤回记录"
    assert "不会实际入账" in cast(str, view["business_summary"])


@pytest.mark.parametrize(
    "change",
    [
        {"grant_schema": "unknown.v3"},
        {"grant_schema": []},
        {"selected_capabilities": ["unknown.capability"]},
        {"selected_capabilities": [_ASSESS, _ASSESS]},
        {"selected_capabilities": [_WITHHOLD, _ASSESS]},
        {"selected_capabilities": [True]},
        {"selected_capabilities": _ASSESS},
        {"capability_labels": []},
        {"capability_labels": [""]},
        {"capability_labels": ["模拟税额评估", "多余标签"]},
        {"terms_version": ""},
        {"terms_version": None},
        {"terms_sha256": "A" * 64},
        {"terms_sha256": None},
        {"terms_text": " "},
        {"terms_text": ""},
        {"unexpected": "field"},
    ],
)
def test_ready_v2_rejects_unknown_noncanonical_or_incomplete_fields(
    change: dict[str, object],
) -> None:
    payload = _v2_response()
    payload.update(change)

    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, payload)

    assert view["outcome"] == "blocked"
    assert view["blocking_reason"] == "simulated_action_consent_response_invalid"
    assert _ASSESS not in repr(view)
    assert _TERMS_TEXT not in repr(view)


def test_v1_cannot_claim_tax_capabilities_or_terms() -> None:
    payload = _expanded_v1_response()
    payload["selected_capabilities"] = [_ASSESS]
    payload["capability_labels"] = ["模拟税额评估"]

    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, payload)

    assert view["outcome"] == "blocked"
    assert view["blocking_reason"] == "simulated_action_consent_response_invalid"
    assert _ASSESS not in repr(view)


def test_explicit_v1_schema_still_has_no_additional_rights() -> None:
    payload = _expanded_v1_response()
    payload["grant_schema"] = _V1_SCHEMA

    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, payload)

    assert view["outcome"] == "success"
    assert "所选模拟能力" not in repr(view)
    assert _ASSESS not in repr(view)


def test_token_echo_remains_rejected_in_expanded_result() -> None:
    payload = _v2_response()
    payload["consent_token"] = "secret-token"

    view = _project(CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY, payload)

    assert view["outcome"] == "blocked"
    assert view["blocking_reason"] == "simulated_action_consent_response_invalid"
    assert "secret-token" not in repr(view)
