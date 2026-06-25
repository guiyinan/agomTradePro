from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.decision_rhythm.application.advisor_services import AdvisorAccessError


@pytest.fixture
def authenticated_client(db):
    user = User.objects.create_user(username="advisor_api_user", password="testpass")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_advisor_sheet_requires_account_id(authenticated_client):
    response = authenticated_client.get("/api/decision/advisor/sheet/")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "account_id" in payload["error"]


@pytest.mark.django_db
def test_advisor_sheet_maps_account_access_error(authenticated_client, monkeypatch):
    def fake_execute(self, *, account_id, user):
        raise AdvisorAccessError("无权查看该账户", 403)

    monkeypatch.setattr(
        "apps.decision_rhythm.interface.advisor_api_views.GenerateAdvisorDecisionSheetUseCase.execute",
        fake_execute,
    )

    response = authenticated_client.get("/api/decision/advisor/sheet/?account_id=9")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "无权查看该账户"


@pytest.mark.django_db
def test_advisor_sheet_returns_account_holdings_allocation_and_order_intents(
    authenticated_client,
    monkeypatch,
):
    def fake_execute(self, *, account_id, user):
        return {
            "account": {"account_id": account_id, "account_name": "A"},
            "baseline": "existing_positions",
            "today_conclusion": "ACT",
            "holdings": [{"asset_code": "AAA"}],
            "allocation": [{"asset_class": "equity"}],
            "order_intents": [{"order_intent_id": "oi_1", "side": "BUY"}],
            "order_summary": {"total": 1},
            "blockers": [],
            "next_actions": [],
        }

    monkeypatch.setattr(
        "apps.decision_rhythm.interface.advisor_api_views.GenerateAdvisorDecisionSheetUseCase.execute",
        fake_execute,
    )

    response = authenticated_client.get("/api/decision/advisor/sheet/?account_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["today_conclusion"] in {"ACT", "REVIEW", "WAIT", "BLOCKED"}
    assert "holdings" in data
    assert "allocation" in data
    assert "order_intents" in data
