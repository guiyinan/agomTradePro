"""Strict owner scope, continuation, and response contracts for company actions."""

from __future__ import annotations

from datetime import UTC, date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.interface import corporate_action_workflow_views as views
from apps.simulated_trading.interface.corporate_action_workflow_serializers import (
    MAX_CONTINUATION_TOKEN_LENGTH,
    OwnerCorporateActionWorkflowResponseSerializer,
)

_ACCOUNT_ID = 41
_TOKEN = "owner-workflow-private-continuation"


def _payload(*, account_id: int = _ACCOUNT_ID) -> dict[str, Any]:
    """Build the agreed safe workflow response without claiming real source evidence."""
    return {
        "account_id": account_id,
        "outcome": "success",
        "summary": "受控测试账户摘要。",
        "blocking_reason": None,
        "source_observed_at": "2026-11-13T10:00:00Z",
        "checked_at": "2026-11-13T10:01:00Z",
        "freshness_status": "current_source_seen",
        "reliability_status": "controlled_fixture",
        "must_not_use_for_decision": True,
        "book_cash": "1000.00",
        "spendable_cash": None,
        "net_asset_value": None,
        "dividend_receivable": "20.00",
        "share_receivable": None,
        "tax_payable": None,
        "events": [
            {
                "event_id": "szse-event-1",
                "asset_code": "000001.SZ",
                "title": "受控测试事件",
                "event_type": "cash_dividend",
                "announced_on": "2026-11-01",
                "record_date": "2026-11-10",
                "effective_date": "2026-11-12",
                "source_observed_at": "2026-11-13T10:00:00Z",
                "status": "blocked_without_consent",
                "blocking_reason": "尚未取得对应授权。",
            }
        ],
        "audit_receipts": [
            {
                "receipt_id": "receipt-1",
                "recorded_at": "2026-11-12T09:00:00Z",
                "asset_code": "000001.SZ",
                "stage_label": "现金权益",
                "cash_delta": "20.00",
                "share_delta": "0.000000",
                "summary": "受控测试回执。",
            }
        ],
    }


def _call(
    method: str,
    *,
    suffix: str = "",
    body: object | None = None,
    account_id: int = _ACCOUNT_ID,
    authenticated: bool = True,
    query: str = "",
) -> Any:
    """Call one APIView using the same JSON/session boundary as the owner TUI."""
    factory = APIRequestFactory()
    path = f"/api/simulated-trading/accounts/{account_id}/corporate-actions/{suffix}{query}"
    request = getattr(factory, method)(path, body if body is not None else {}, format="json")
    if authenticated:
        force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    view_by_method = {
        ("get", ""): views.OwnerCorporateActionWorkflowReadAPIView,
        ("get", "events"): views.OwnerCorporateActionWorkflowEventsAPIView,
        ("post", "prepare"): views.OwnerCorporateActionWorkflowPrepareAPIView,
        ("post", "confirm"): views.OwnerCorporateActionWorkflowConfirmAPIView,
        ("post", "refresh"): views.OwnerCorporateActionWorkflowRefreshAPIView,
    }
    normalized_suffix = suffix.strip("/").split("/")[0]
    response = view_by_method[(method, normalized_suffix)].as_view()(
        request,
        account_id=account_id,
    )
    response.render()
    assert response.headers["Content-Type"].startswith("application/json")
    return response


def test_read_is_session_bound_and_binds_event_rows_to_url_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def read(request: Request, *, account_id: int) -> dict[str, Any]:
        assert request.user.pk == 81
        calls.append(account_id)
        return _payload()

    monkeypatch.setattr(views, "read_owner_corporate_action_workflow", read)
    response = _call("get")
    assert response.status_code == 200
    assert response.data["must_not_use_for_decision"] is True
    assert response.data["book_cash"] == "1000.00"
    assert response.data["spendable_cash"] is None
    assert response.data["events"][0]["account_id"] == _ACCOUNT_ID
    assert response.data["audit_receipts"][0]["receipt_id"] == "receipt-1"
    assert calls == [_ACCOUNT_ID]
    assert views.OwnerCorporateActionWorkflowReadAPIView.authentication_classes == (
        views.SessionAuthentication,
    )
    assert views.OwnerCorporateActionWorkflowReadAPIView.permission_classes == (
        views.IsAuthenticated,
    )


def test_events_discovery_uses_its_dedicated_owner_service_without_balances(monkeypatch):
    payload = _payload()
    for key in (
        "book_cash",
        "spendable_cash",
        "net_asset_value",
        "dividend_receivable",
        "share_receivable",
        "tax_payable",
    ):
        payload[key] = None
    payload["audit_receipts"] = []
    calls = []

    def events(request, *, account_id):
        assert request.user.pk == 81
        calls.append(account_id)
        return payload

    monkeypatch.setattr(views, "read_owner_corporate_action_events", events)
    monkeypatch.setattr(
        views,
        "read_owner_corporate_action_workflow",
        lambda *a, **k: pytest.fail("event discovery rebuilt financial balances"),
    )
    response = _call("get", suffix="events/")
    assert response.status_code == 200
    assert calls == [_ACCOUNT_ID]
    assert response.data["events"][0]["account_id"] == _ACCOUNT_ID
    assert response.data["must_not_use_for_decision"] is True
    assert response.data["net_asset_value"] is None
    assert response.data["book_cash"] is None
    assert response.data["audit_receipts"] == []


@pytest.mark.parametrize(
    "query,authenticated,status", [("?owner_user_id=82", True, 400), ("", False, 403)]
)
def test_events_rejects_foreign_query_scope_and_anonymous_session(
    monkeypatch, query, authenticated, status
):
    monkeypatch.setattr(
        views,
        "read_owner_corporate_action_events",
        lambda *a, **k: pytest.fail("unscoped event read"),
    )
    assert (
        _call("get", suffix="events/", query=query, authenticated=authenticated).status_code
        == status
    )


def test_response_serializer_accepts_the_exact_public_fact_contract() -> None:
    payload = _payload()
    event = dict(payload["events"][0])
    event["account_id"] = _ACCOUNT_ID
    payload["events"] = [event]
    serializer = OwnerCorporateActionWorkflowResponseSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors


def test_read_rejects_query_scope_and_anonymous_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        views,
        "read_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("unscoped request reached the owner service"),
    )
    assert _call("get", query="?owner_user_id=82").status_code == 400
    assert _call("get", authenticated=False).status_code == 403


def test_prepare_accepts_only_the_server_selected_event_and_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    expires_at = (timezone.now() + timedelta(minutes=2)).astimezone(UTC)
    response_payload = _payload()
    response_payload["continuation"] = {
        "action_key": "simulated-trading.corporate-action-workflow-confirm",
        "input": {"account_id": str(_ACCOUNT_ID), "continuation_token": _TOKEN},
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }

    def prepare(request: Request, **kwargs: object) -> dict[str, Any]:
        assert request.user.pk == 81
        calls.append(dict(kwargs))
        return response_payload

    monkeypatch.setattr(views, "prepare_owner_corporate_action_workflow", prepare)
    response = _call(
        "post",
        suffix="prepare/",
        body={
            "account_id": str(_ACCOUNT_ID),
            "event_id": "szse-event-1",
            "action": "tax_assess",
            "settlement_date": "2026-11-14",
        },
    )
    assert response.status_code == 200
    assert calls == [
        {
            "account_id": _ACCOUNT_ID,
            "event_id": "szse-event-1",
            "action": "tax_assess",
            "settlement_date": date(2026, 11, 14),
            "correction_mode": "ordinary",
        }
    ]
    assert response.data["continuation"]["input"] == {
        "account_id": str(_ACCOUNT_ID),
        "continuation_token": _TOKEN,
    }
    assert _TOKEN not in repr(
        {key: value for key, value in response.data.items() if key != "continuation"}
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"quantity": "1"},
        {"cash_amount": "5.00"},
        {"owner_user_id": 82},
        {"source_hash": "forged"},
        {"StageRequest": {}},
    ],
)
def test_prepare_rejects_client_authority_and_financial_facts(
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, object],
) -> None:
    monkeypatch.setattr(
        views,
        "prepare_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("invalid prepare body reached owner service"),
    )
    body: dict[str, object] = {
        "event_id": "szse-event-1",
        "action": "cash_payment",
    }
    body.update(extra)
    response = _call("post", suffix="prepare/", body=body)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {"event_id": "szse-event-1"},
        {"event_id": "szse-event-1", "action": "unsupported"},
        {"event_id": "szse-event-1", "action": "cash_payment", "settlement_date": "11/14/2026"},
        {"event_id": "szse-event-1", "action": "cash_payment", "settlement_date": 20261114},
        {"event_id": "szse-event-1", "action": "cash_payment", "account_id": "041"},
    ],
)
def test_prepare_rejects_missing_invalid_or_noncanonical_fields(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    monkeypatch.setattr(
        views,
        "prepare_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("invalid prepare body reached owner service"),
    )
    assert _call("post", suffix="prepare/", body=body).status_code == 400


@pytest.mark.parametrize("mode", ["ordinary", "correct_existing"])
def test_prepare_forwards_the_selected_correction_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    calls: list[dict[str, object]] = []
    payload = _payload()
    payload["continuation"] = {
        "action_key": "simulated-trading.corporate-action-workflow-confirm",
        "input": {"account_id": str(_ACCOUNT_ID), "continuation_token": _TOKEN},
        "expires_at": (timezone.now() + timedelta(minutes=2)).astimezone(UTC).isoformat(),
    }

    def prepare(request: Request, **kwargs: object) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return payload

    monkeypatch.setattr(views, "prepare_owner_corporate_action_workflow", prepare)
    response = _call(
        "post",
        suffix="prepare/",
        body={"event_id": "szse-event-1", "action": "cash_payment", "correction_mode": mode},
    )
    assert response.status_code == 200
    assert calls[0]["correction_mode"] == mode


def test_prepare_rejects_body_account_id_that_differs_from_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views,
        "prepare_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("cross-account prepare reached owner service"),
    )
    response = _call(
        "post",
        suffix="prepare/",
        body={
            "account_id": 42,
            "event_id": "szse-event-1",
            "action": "cash_payment",
        },
    )
    assert response.status_code == 400


def test_confirm_true_uses_only_the_exact_prepared_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def confirm(request: object, **kwargs: object) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return _payload()

    monkeypatch.setattr(views, "confirm_owner_corporate_action_workflow", confirm)
    response = _call(
        "post",
        suffix="confirm/",
        body={
            "account_id": str(_ACCOUNT_ID),
            "continuation_token": _TOKEN,
            "confirmed": True,
        },
    )
    assert response.status_code == 200
    assert calls == [
        {
            "account_id": _ACCOUNT_ID,
            "continuation_token": _TOKEN,
            "confirmed": True,
        }
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"continuation_token": _TOKEN},
        {"continuation_token": _TOKEN, "confirmed": 1},
        {"continuation_token": _TOKEN, "confirmed": "true"},
        {"continuation_token": _TOKEN, "confirmed": True, "quantity": "1"},
        {"continuation_token": _TOKEN, "confirmed": True, "source_revision": "forged"},
    ],
)
def test_confirm_rejects_coercions_missing_confirmation_and_extra_authority(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    monkeypatch.setattr(
        views,
        "confirm_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("invalid confirmation reached owner service"),
    )
    assert _call("post", suffix="confirm/", body=body).status_code == 400


def test_confirm_false_cancels_without_reaching_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        views,
        "confirm_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("cancelled continuation reached owner service"),
    )
    response = _call(
        "post",
        suffix="confirm/",
        body={"account_id": _ACCOUNT_ID, "continuation_token": _TOKEN, "confirmed": False},
    )
    assert response.status_code == 200
    assert response.data["outcome"] == "noop"
    assert response.data["book_cash"] is None


def test_refresh_false_cancels_and_true_requires_path_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views,
        "refresh_owner_corporate_action_workflow",
        lambda *args, **kwargs: pytest.fail("unconfirmed refresh reached owner service"),
    )
    cancelled = _call("post", suffix="refresh/", body={"confirmed": False})
    assert cancelled.status_code == 200
    assert cancelled.data["outcome"] == "noop"
    mismatch = _call(
        "post",
        suffix="refresh/",
        body={"account_id": 42, "confirmed": True},
    )
    assert mismatch.status_code == 400


def test_refresh_true_calls_only_the_authenticated_owner_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        views,
        "refresh_owner_corporate_action_workflow",
        lambda request, **kwargs: calls.append(kwargs) or _payload(),
    )
    response = _call("post", suffix="refresh/", body={"confirmed": True})
    assert response.status_code == 200
    assert calls == [{"account_id": _ACCOUNT_ID, "confirmed": True}]


def test_prepare_continuation_accepts_full_technical_limit_and_rejects_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expires_at = (timezone.now() + timedelta(minutes=2)).astimezone(UTC)
    token = "x" * MAX_CONTINUATION_TOKEN_LENGTH
    payload = _payload()
    payload["continuation"] = {
        "action_key": "simulated-trading.corporate-action-workflow-confirm",
        "input": {"account_id": str(_ACCOUNT_ID), "continuation_token": token},
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }
    monkeypatch.setattr(views, "prepare_owner_corporate_action_workflow", lambda *a, **kw: payload)
    success = _call(
        "post",
        suffix="prepare/",
        body={"event_id": "szse-event-1", "action": "cash_payment"},
    )
    assert success.status_code == 200
    assert success.data["continuation"]["input"]["continuation_token"] == token
    payload["summary"] = f"leaked {token}"
    blocked = _call(
        "post",
        suffix="prepare/",
        body={"event_id": "szse-event-1", "action": "cash_payment"},
    )
    assert blocked.status_code == 503
    assert token.encode() not in blocked.content


def test_workflow_response_drops_unapproved_fields_and_rejects_raw_receipt_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    payload["events"][0]["source_sha256"] = "private-hash"
    monkeypatch.setattr(views, "read_owner_corporate_action_workflow", lambda *a, **kw: payload)
    response = _call("get")
    assert response.status_code == 503
    assert b"private-hash" not in response.content


def test_registered_api_routes_are_the_five_owner_workflow_endpoints() -> None:
    from django.urls import resolve

    expected = {
        "/api/simulated-trading/accounts/41/corporate-actions/": "corporate-action-workflow-read",
        "/api/simulated-trading/accounts/41/corporate-actions/events/": "corporate-action-workflow-events",
        "/api/simulated-trading/accounts/41/corporate-actions/prepare/": "corporate-action-workflow-prepare",
        "/api/simulated-trading/accounts/41/corporate-actions/confirm/": "corporate-action-workflow-confirm",
        "/api/simulated-trading/accounts/41/corporate-actions/refresh/": "corporate-action-workflow-refresh",
    }
    for url, name in expected.items():
        assert resolve(url).url_name == name
