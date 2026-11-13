"""JSON, explicit confirmation and exact owner scope contracts for consent routes."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.simulated_trading.interface import corporate_action_consent_views as views
from core.exceptions import AuthorizationError


def _call(method, *, body=None, authenticated=True, withdrawal=False, path=None):
    factory = APIRequestFactory()
    target = path or "/api/simulated-trading/accounts/41/corporate-action-consent/"
    request = getattr(factory, method)(target, body or {}, format="json")
    if authenticated:
        force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    view = (
        views.SimulatedActionConsentWithdrawalAPIView
        if withdrawal
        else views.SimulatedActionConsentAPIView
    )
    response = view.as_view()(request, account_id=41)
    response.render()
    assert response.headers["Content-Type"].startswith("application/json")
    return response


def test_anonymous_and_unsupported_methods_return_bounded_json():
    assert _call("get", authenticated=False).status_code == 403
    assert _call("delete").status_code == 405
    assert _call("get", withdrawal=True).status_code == 405


def test_owner_read_invokes_preparation_without_a_write(monkeypatch):
    calls = []

    def prepare(request, *, account_id):
        calls.append((request.user.pk, account_id))
        return {"outcome": "blocked", "consent_status": "not_consented", "must_not_execute": True}

    monkeypatch.setattr(views, "prepare_owner_simulated_action_consent", prepare)
    result = _call("get")
    assert result.status_code == 200
    assert result.data["must_not_execute"] is True
    assert calls == [(81, 41)]


@pytest.mark.parametrize(
    "body",
    [
        {"consent_token": "prepared"},
        {"consent_token": "prepared", "confirmed": False},
        {"consent_token": "prepared", "confirmed": 1},
        {"consent_token": "prepared", "confirmed": "true"},
        {"consent_token": 123, "confirmed": True},
        {"consent_token": "prepared", "confirmed": True, "owner_user_id": 82},
    ],
)
def test_confirmation_rejects_missing_coerced_or_unknown_fields(monkeypatch, body):
    monkeypatch.setattr(
        views,
        "confirm_owner_simulated_action_consent",
        lambda *args, **kwargs: pytest.fail("invalid request reached issuer"),
    )
    assert _call("post", body=body).status_code == 400


@pytest.mark.parametrize("withdrawal", [False, True])
def test_confirm_and_withdraw_keep_exact_prepared_locator_and_path_account(monkeypatch, withdrawal):
    calls = []
    field = "withdrawal_token" if withdrawal else "consent_token"
    function = (
        "withdraw_owner_simulated_action_consent"
        if withdrawal
        else "confirm_owner_simulated_action_consent"
    )

    def invoke(request, **kwargs):
        calls.append((request.user.pk, kwargs))
        return {"outcome": "success", "must_not_execute": True}

    monkeypatch.setattr(views, function, invoke)
    result = _call("post", body={field: "prepared", "confirmed": True}, withdrawal=withdrawal)
    assert result.status_code == 200
    assert calls == [(81, {"account_id": 41, field: "prepared", "confirmed": True})]


@pytest.mark.parametrize(
    "error,status",
    [
        (AuthorizationError("private owner detail"), 403),
        (SimulatedCorporateActionWriteGrantConflict("private conflict detail"), 409),
        (SimulatedCorporateActionWriteGrantUnavailable("private source detail"), 422),
    ],
)
def test_known_failures_publish_status_without_internal_details(monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(views, "prepare_owner_simulated_action_consent", fail)
    result = _call("get")
    assert result.status_code == status
    assert b"private" not in result.content


def test_query_scope_substitution_is_rejected_before_preparation(monkeypatch):
    monkeypatch.setattr(
        views,
        "prepare_owner_simulated_action_consent",
        lambda *args, **kwargs: pytest.fail("query scope reached service"),
    )
    assert _call("get", path="/consent?owner_user_id=82").status_code == 400


@pytest.mark.parametrize("withdrawal", [False, True])
def test_preparation_tokens_appear_only_inside_exact_protected_continuation(
    monkeypatch, withdrawal
):
    field = "withdrawal_token" if withdrawal else "consent_token"
    function = (
        "prepare_owner_simulated_action_withdrawal"
        if withdrawal
        else "prepare_owner_simulated_action_consent"
    )
    payload = {
        "account_id": 41,
        "outcome": "success",
        "consent_status": "active" if withdrawal else "awaiting_confirmation",
        "consent_token": "private-consent",
        "withdrawal_token": "private-withdrawal",
        "consent_valid_until": (timezone.now() + timedelta(minutes=1)).isoformat(),
    }
    monkeypatch.setattr(views, function, lambda *args, **kwargs: payload)
    monkeypatch.setattr(
        views,
        "read_authenticated_withdrawal_session_deadline",
        lambda request: timezone.now() + timedelta(minutes=2),
    )
    request = APIRequestFactory().post("/prepare/", {}, format="json")
    force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    view = (
        views.SimulatedActionWithdrawalPreparationAPIView
        if withdrawal
        else views.SimulatedActionConsentPreparationAPIView
    )
    response = view.as_view()(request, account_id=41)
    response.render()
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.data["consent_token"] is None and response.data["withdrawal_token"] is None
    continuation = response.data["continuation"]
    assert set(continuation) == {"action_key", "input", "expires_at"}
    assert continuation["input"] == {"account_id": "41", field: payload[field]}
    assert response.data["account_id"] == 41


@pytest.mark.parametrize(
    "body,selected",
    [
        (
            {"cash_dividend": True, "tax_assessment": False, "tax_withholding": False},
            (Capability.CASH_STAGE_WRITE,),
        ),
        (
            {"cash_dividend": False, "tax_assessment": True, "tax_withholding": False},
            (Capability.TAX_ASSESS,),
        ),
        (
            {"cash_dividend": True, "tax_assessment": True, "tax_withholding": True},
            (Capability.TAX_ASSESS, Capability.TAX_WITHHOLD, Capability.CASH_STAGE_WRITE),
        ),
    ],
)
def test_explicit_capability_checkboxes_reach_preparation_as_an_exact_set(
    monkeypatch, body, selected
):
    calls = []

    def prepare(request, **kwargs):
        calls.append(kwargs)
        return {
            "account_id": 41,
            "outcome": "blocked",
            "consent_token": None,
            "withdrawal_token": None,
        }

    monkeypatch.setattr(views, "prepare_owner_simulated_action_consent", prepare)
    request = APIRequestFactory().post("/prepare/", body, format="json")
    force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    response = views.SimulatedActionConsentPreparationAPIView.as_view()(request, account_id=41)
    response.render()
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert calls == [{"account_id": 41, "grant_schema": None, "requested_capabilities": selected}]


@pytest.mark.parametrize(
    "body",
    [
        {"tax_assessment": True},
        {"cash_dividend": True, "tax_assessment": True},
        {"cash_dividend": False, "tax_assessment": False, "tax_withholding": False},
        {"cash_dividend": True, "tax_assessment": "true", "tax_withholding": False},
        {"cash_dividend": True, "tax_assessment": 1, "tax_withholding": False},
        {"cash_dividend": True, "tax_assessment": None, "tax_withholding": False},
        {
            "cash_dividend": True,
            "tax_assessment": True,
            "tax_withholding": False,
            "owner_user_id": 82,
        },
    ],
)
def test_capability_preparation_rejects_partial_coerced_empty_or_extra_choices(monkeypatch, body):
    monkeypatch.setattr(
        views,
        "prepare_owner_simulated_action_consent",
        lambda *args, **kwargs: pytest.fail("Invalid choice reached owner preparation"),
    )
    request = APIRequestFactory().post("/prepare/", body, format="json")
    force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    response = views.SimulatedActionConsentPreparationAPIView.as_view()(request, account_id=41)
    response.render()
    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")


def test_v3_five_literal_choices_keep_independent_share_and_decline_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(
        views,
        "prepare_owner_simulated_action_consent",
        lambda request, **kwargs: calls.append(kwargs)
        or {
            "account_id": 41,
            "outcome": "blocked",
            "consent_token": None,
            "withdrawal_token": None,
        },
    )
    body = {
        "cash_dividend": False,
        "tax_assessment": False,
        "tax_withholding": False,
        "share_distribution": True,
        "rights_not_exercised": True,
    }
    request = APIRequestFactory().post("/prepare/", body, format="json")
    force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    response = views.SimulatedActionConsentPreparationAPIView.as_view()(request, account_id=41)
    response.render()
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert calls == [
        {
            "account_id": 41,
            "grant_schema": None,
            "requested_capabilities": (
                Capability.RIGHTS_NOT_EXERCISED,
                Capability.SHARE_STAGE_WRITE,
            ),
        }
    ]


@pytest.mark.parametrize("defect", ["partial", "coerced", "empty", "extra"])
def test_v3_choices_reject_partial_coerced_empty_or_extra_fields(monkeypatch, defect):
    monkeypatch.setattr(
        views,
        "prepare_owner_simulated_action_consent",
        lambda *a, **kw: pytest.fail("Invalid choice reached preparation"),
    )
    body = {
        "cash_dividend": False,
        "tax_assessment": False,
        "tax_withholding": False,
        "share_distribution": True,
        "rights_not_exercised": False,
    }
    if defect == "partial":
        del body["rights_not_exercised"]
    elif defect == "coerced":
        body["share_distribution"] = "true"
    elif defect == "empty":
        body["share_distribution"] = False
    else:
        body["rights_exercise"] = True
    request = APIRequestFactory().post("/prepare/", body, format="json")
    force_authenticate(request, user=SimpleNamespace(pk=81, is_authenticated=True))
    response = views.SimulatedActionConsentPreparationAPIView.as_view()(request, account_id=41)
    response.render()
    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
