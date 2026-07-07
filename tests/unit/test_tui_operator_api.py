from __future__ import annotations

import pytest
from django.contrib.auth.models import User

import apps.terminal.interface.api_views as tui_api_views


@pytest.fixture
def tui_user(db):
    return User.objects.create_user(username="tui_operator_api", password="test-password")


def test_tui_operator_home_api_returns_fixed_payload(client, tui_user, monkeypatch):
    captured = {}

    def fake_home_payload(*, user):
        captured["user"] = user.username
        return {
            "status": "warning",
            "decision_queue": {"rows": [], "total": 0, "status": "ok", "badge": {}},
            "market_context": {"rows": [], "total": 0, "status": "ok", "badge": {}},
            "account_signal_summary": {"rows": [], "total": 0, "status": "ok", "badge": {}},
            "system_exception_summary": {
                "rows": [],
                "total": 0,
                "status": "warning",
                "badge": {"blocked_count": 0, "warning_count": 1},
            },
            "data_task_summary": {"rows": [], "total": 0, "status": "ok", "badge": {}},
            "ai_config_summary": {"rows": [], "total": 0, "status": "ok", "badge": {}},
        }

    monkeypatch.setattr(tui_api_views, "build_operator_home_payload", fake_home_payload)
    client.force_login(tui_user)

    response = client.get("/api/tui/operator/home/")

    assert response.status_code == 200
    payload = response.json()
    assert captured["user"] == "tui_operator_api"
    assert payload["status"] == "warning"
    assert list(payload.keys()) == [
        "status",
        "decision_queue",
        "market_context",
        "account_signal_summary",
        "system_exception_summary",
        "data_task_summary",
        "ai_config_summary",
    ]


def test_tui_operator_governance_queue_api_forwards_domain(client, tui_user, monkeypatch):
    captured = {}

    def fake_governance_payload(*, user, domain=""):
        captured["username"] = user.username
        captured["domain"] = domain
        return {
            "status": "blocked",
            "items": [
                {
                    "severity": "blocked",
                    "domain": domain,
                    "title": "blocked item",
                    "status": "blocked",
                    "blocking_reason": "reason",
                    "next_action": "fix",
                    "target_screen": "api-library.runtime",
                    "target_action_key": "operator.governance.runtime_summary",
                    "observed_at": "2026-07-07T10:00:00+00:00",
                }
            ],
            "total": 1,
            "summary": {"blocked": 1},
        }

    monkeypatch.setattr(
        tui_api_views,
        "build_operator_governance_queue_payload",
        fake_governance_payload,
    )
    client.force_login(tui_user)

    response = client.get("/api/tui/operator/governance-queue/?domain=runtime")

    assert response.status_code == 200
    payload = response.json()
    assert captured == {"username": "tui_operator_api", "domain": "runtime"}
    assert payload["items"][0]["target_screen"] == "api-library.runtime"
    assert payload["items"][0]["target_action_key"] == "operator.governance.runtime_summary"


def test_tui_operator_api_requires_authentication(client):
    home_response = client.get("/api/tui/operator/home/")
    governance_response = client.get("/api/tui/operator/governance-queue/")

    assert home_response.status_code in {302, 401, 403}
    assert governance_response.status_code in {302, 401, 403}
