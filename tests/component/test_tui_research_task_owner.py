"""Consume actual source-bearing synthetic facts through real HTTP and TUI.

No owner/readiness/publication reader is replaced. Calendar transport and
stored health/universe are synthetic. This proves local integration only.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from decimal import Decimal
from typing import NoReturn

import pytest
from django.conf import settings
from django.test import Client

from apps.data_center.infrastructure.models import FinancialFactModel
from tests.support.tui_research.scenario import research_scenario

ACTION = "/api/tui/actions/equity.research-snapshot/run/"
OWNER = "/api/equity/research-snapshot/600000.SH/"


@pytest.mark.django_db(transaction=True)
def test_research_page_initializes_csrf_without_weakening_post_checks(
    django_user_model, deny_network
) -> None:
    """A valid session can submit its first read after opening the task page."""

    user = django_user_model.objects.create_user(username="tux08-first-csrf")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    with research_scenario():
        page = client.get("/tui/")
        assert page.status_code == 200
        assert settings.CSRF_COOKIE_NAME in client.cookies
        params = {"params": {"stock_code": "600000.SH"}}
        rejected = client.post(ACTION, params, content_type="application/json")
        assert rejected.status_code == 403
        accepted = client.post(
            ACTION,
            params,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies[settings.CSRF_COOKIE_NAME].value,
        )
        assert accepted.status_code == 200
        assert accepted.json()["outcome"] == "success"


@pytest.fixture
def deny_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Treat even swallowed external connection attempts as failed acceptance."""

    attempts: list[str] = []

    def deny(_socket: socket.socket, address: object) -> NoReturn:
        attempts.append(repr(address))
        raise AssertionError("Actual local research consumer attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    yield
    assert attempts == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("with_optionals,expected", [(True, "success"), (False, "partial")])
def test_actual_research_facts_reach_curated_task(
    client, django_user_model, deny_network, with_optionals: bool, expected: str
) -> None:
    """All four actual checks precede the existing owner, executor and task view."""

    user = django_user_model.objects.create_user(username=f"tux08-real-{expected}")
    client.force_login(user)
    with research_scenario(with_optionals=with_optionals) as scenario:
        assert {key: item["status"] for key, item in scenario.strict_checks.items()} == {
            "runtime_state": "ok",
            "core_coverage": "ok",
            "provider_capabilities": "ok",
            "decision_data": "ok",
        }
        owner = client.get(OWNER)
        assert owner.status_code == 200
        assert owner.headers["Content-Type"].startswith("application/json")
        payload = owner.json()
        assert payload["outcome"] == expected
        assert payload["must_not_use_for_decision"] is False
        requested = "研究夹具" if with_optionals else "600000.SH"
        response = client.post(
            ACTION, {"params": {"stock_code": requested}}, content_type="application/json"
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("application/json")
        result = response.json()
        assert result["response"]["status_code"] == 200
        assert result["outcome"] == expected
        view = result["view_model"]
        assert view["must_not_use_for_decision"] is False
        assert view["owner_status"] == payload["status"]
        sections = {item["key"]: item for item in view["sections"]}
        assert len(sections) == 6
        assert sections["financials"]["rows"][0]["fields"]
        announced = scenario.financial.refreshed_fact.announced_at.isoformat()
        assert any(
            item["field"] == "announced_at" and item["value"] == announced
            for item in sections["financials"]["source_times"]
        )
        assert all(
            item["label"] == "行情数据发布记录时间"
            for item in sections["latest_quote"]["source_times"]
            if item["field"] == "published_at"
        )
        assert result["debug"] == {"raw_available": False, "raw_response": None}
        assert "证伪条件" in view["business_summary"]
        assert not any("confirmed" in step.get("params", {}) for step in view["next_steps"])


@pytest.mark.django_db(transaction=True)
def test_financial_tamper_blocks_actual_task_and_restoration_allows_retry(
    client, django_user_model, deny_network
) -> None:
    """A changed persisted fact cannot be hidden behind successful HTTP transport."""

    user = django_user_model.objects.create_user(username="tux08-real-tamper")
    client.force_login(user)
    with research_scenario() as scenario:
        fact = scenario.financial.fact
        original = fact.value
        FinancialFactModel.objects.filter(pk=fact.pk).update(value=original + Decimal("1"))
        blocked = client.get(OWNER)
        assert blocked.status_code == 200
        blocked_payload = blocked.json()
        assert blocked_payload["status"] == "blocked"
        assert blocked_payload["outcome"] == "blocked"
        assert blocked_payload["must_not_use_for_decision"] is True
        assert (
            blocked_payload["sections"]["financials"]["data"]["blocked_reason"]
            == "publication_member_fact_changed"
        )
        response = client.post(
            ACTION, {"params": {"stock_code": "600000.SH"}}, content_type="application/json"
        )
        assert response.status_code == 200
        result = response.json()
        assert result["response"]["status_code"] == 200
        assert result["outcome"] == "blocked"
        assert result["view_model"]["must_not_use_for_decision"] is True
        assert result["debug"] == {"raw_available": False, "raw_response": None}
        FinancialFactModel.objects.filter(pk=fact.pk).update(value=original)
        recovered = client.post(
            ACTION, {"params": {"stock_code": "600000.SH"}}, content_type="application/json"
        )
        assert recovered.status_code == 200
        assert recovered.json()["outcome"] == "success"


@pytest.mark.django_db(transaction=True)
def test_actual_unresolved_identity_and_expired_login_are_bounded(
    client, django_user_model, deny_network
) -> None:
    """Unknown exact names and revoked sessions cannot turn into another asset."""

    user = django_user_model.objects.create_user(username="tux08-real-missing")
    client.force_login(user)
    with research_scenario():
        missing = client.post(
            ACTION, {"params": {"stock_code": "NO_MATCH_TUX08"}}, content_type="application/json"
        )
        assert missing.status_code == 200
        result = missing.json()
        assert result["outcome"] == "blocked"
        assert result["view_model"]["owner_status"] == "missing"
        assert result["view_model"]["next_steps"] == []
        client.logout()
        forbidden = client.post(
            ACTION, {"params": {"stock_code": "600000.SH"}}, content_type="application/json"
        )
        assert forbidden.status_code == 403
        assert forbidden.headers["Content-Type"].startswith("application/json")


@pytest.mark.django_db(transaction=True)
def test_stale_financial_source_cannot_be_refreshed_by_a_new_publication(
    client, django_user_model, deny_network
) -> None:
    """A new fetch/publication cannot turn a 91-day-old financial source fresh."""

    user = django_user_model.objects.create_user(username="tux08-real-stale")
    client.force_login(user)
    with research_scenario(financial_age_days=91, require_ready=False):
        response = client.get(OWNER)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["outcome"] == "blocked"
        assert payload["must_not_use_for_decision"] is True
        financial = payload["sections"]["financials"]
        assert financial["data"]["freshness_status"] == "stale"
        result = client.post(
            ACTION, {"params": {"stock_code": "600000.SH"}}, content_type="application/json"
        ).json()
        assert result["outcome"] == "blocked"
        assert result["view_model"]["must_not_use_for_decision"] is True
        projected = next(
            section
            for section in result["view_model"]["sections"]
            if section["key"] == "financials"
        )
        assert projected["upstream_freshness_status"] == "stale"
        assert projected["block_reason_code"] == financial["block_reason_code"]
