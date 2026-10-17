"""Real URLConf, persisted ownership and Session/CSRF scope tests.

Only the trading engine is replaced. These tests never qualify market data or
execute orders; they verify which stored accounts the public trigger can reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_user_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep user onboarding integrations outside this account-scope test."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")


@dataclass(frozen=True)
class _Accounts:
    owner: Any
    other: Any
    admin: Any
    own_simulated: SimulatedAccountModel
    foreign_simulated: SimulatedAccountModel
    own_real: SimulatedAccountModel
    own_disabled: SimulatedAccountModel
    own_inactive: SimulatedAccountModel
    admin_simulated: SimulatedAccountModel


@pytest.fixture
def accounts() -> _Accounts:
    """Persist two ordinary owners and an administrator with distinct accounts."""

    users = get_user_model()
    owner = users.objects.create_user(username="ash-scope-owner")
    other = users.objects.create_user(username="ash-scope-other")
    admin = users.objects.create_user(username="ash-scope-admin", is_superuser=True, is_staff=True)

    def account(user: Any, name: str, **values: object) -> SimulatedAccountModel:
        return SimulatedAccountModel.objects.create(
            user=user,
            account_name=name,
            initial_capital=Decimal("10000.00"),
            current_cash=Decimal("10000.00"),
            total_value=Decimal("10000.00"),
            **values,
        )

    return _Accounts(
        owner=owner,
        other=other,
        admin=admin,
        own_simulated=account(owner, "owned-simulated", account_type="simulated"),
        foreign_simulated=account(other, "foreign-simulated", account_type="simulated"),
        own_real=account(owner, "owned-real", account_type="real"),
        own_disabled=account(owner, "owned-disabled", auto_trading_enabled=False),
        own_inactive=account(owner, "owned-inactive", is_active=False),
        admin_simulated=account(admin, "admin-simulated", account_type="simulated"),
    )


class _EngineSpy:
    def __init__(self) -> None:
        self.builds = 0
        self.calls: list[tuple[date, list[int] | None]] = []
        self.result_override: object | None = None
        self.error: Exception | None = None
        self.build_error: Exception | None = None

    def build(self) -> _EngineSpy:
        self.builds += 1
        if self.build_error is not None:
            raise self.build_error
        return self

    def run_daily_trading(self, trade_date: date, account_ids: list[int] | None = None) -> object:
        self.calls.append((trade_date, account_ids))
        if self.error is not None:
            raise self.error
        if self.result_override is not None:
            return self.result_override
        return {
            account_id: AccountAutoTradingOutcome(account_id, 0, 0)
            for account_id in account_ids or []
        }


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> _EngineSpy:
    """Keep the real account repository and replace only the execution boundary."""

    spy = _EngineSpy()
    monkeypatch.setattr(interface_services, "build_auto_trading_engine", spy.build)
    return spy


def _client(user: Any | None = None) -> tuple[APIClient, str]:
    """Use an actual DB-backed session and the real admin CSRF cookie endpoint."""

    client = APIClient(enforce_csrf_checks=True)
    response = client.get(reverse("admin:login"), secure=True, HTTP_ORIGIN="https://testserver")
    assert response.status_code == 200
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    if user is not None:
        client.force_login(user)
    return client, token


def _post(client: APIClient, token: str, payload: dict[str, object]) -> Any:
    response = client.post(
        reverse("api_simulated_trading:auto-trading-run"),
        payload,
        format="json",
        secure=True,
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="https://testserver",
    )
    assert response["Content-Type"].startswith("application/json")
    return response


def test_scope_http_default_only_reaches_current_owner_simulated_accounts(
    accounts: _Accounts, engine: _EngineSpy
) -> None:
    client, token = _client(accounts.owner)
    response = _post(client, token, {"trade_date": "2026-10-16"})
    assert response.status_code == 200
    assert engine.calls == [(date(2026, 10, 16), [accounts.own_simulated.pk])]
    assert SimulatedTradeModel.objects.count() == 0


@pytest.mark.parametrize("mixed", [False, True])
def test_scope_http_foreign_account_rejects_whole_scope_before_engine(
    accounts: _Accounts, engine: _EngineSpy, mixed: bool
) -> None:
    client, token = _client(accounts.owner)
    ids = [accounts.foreign_simulated.pk]
    if mixed:
        ids.insert(0, accounts.own_simulated.pk)
    response = _post(client, token, {"account_ids": ids})
    assert response.status_code == 403
    assert engine.builds == 0 and engine.calls == []
    assert SimulatedTradeModel.objects.count() == 0


@pytest.mark.parametrize("attribute", ["own_real", "own_disabled", "own_inactive"])
def test_scope_http_ineligible_account_never_constructs_engine(
    accounts: _Accounts, engine: _EngineSpy, attribute: str
) -> None:
    client, token = _client(accounts.owner)
    account = getattr(accounts, attribute)
    response = _post(client, token, {"account_ids": [account.pk]})
    assert response.status_code == 400
    assert engine.builds == 0 and engine.calls == []


def test_scope_http_explicit_empty_is_no_work_without_engine(
    accounts: _Accounts, engine: _EngineSpy
) -> None:
    client, token = _client(accounts.owner)
    response = _post(client, token, {"account_ids": []})
    assert response.status_code == 200
    assert response.json()["total_accounts"] == 0
    assert response.json()["outcome"] == "noop"
    assert response.json()["requested"] == response.json()["stored"] == 0
    assert engine.builds == 0 and engine.calls == []


@pytest.mark.parametrize("bad_ids", [[True], [0], [-1], [1, 1]])
def test_scope_http_invalid_ids_stop_before_engine(
    accounts: _Accounts, engine: _EngineSpy, bad_ids: list[object]
) -> None:
    client, token = _client(accounts.owner)
    response = _post(client, token, {"account_ids": bad_ids})
    assert response.status_code == 400
    assert engine.builds == 0 and engine.calls == []


def test_scope_http_anonymous_request_is_unauthorized(engine: _EngineSpy) -> None:
    client, token = _client()
    response = _post(client, token, {})
    assert response.status_code == 403
    assert engine.builds == 0 and engine.calls == []


def test_scope_http_missing_account_stops_before_engine(
    accounts: _Accounts, engine: _EngineSpy
) -> None:
    client, token = _client(accounts.owner)
    missing_id = max(SimulatedAccountModel.objects.values_list("pk", flat=True), default=0) + 1
    response = _post(client, token, {"account_ids": [missing_id]})
    assert response.status_code == 404
    assert engine.builds == 0 and engine.calls == []


def test_scope_http_engine_setup_failure_is_safe_and_does_not_enter_run(
    accounts: _Accounts, engine: _EngineSpy
) -> None:
    engine.build_error = RuntimeError("private connection details must stay out of JSON")
    client, token = _client(accounts.owner)
    response = _post(client, token, {"account_ids": [accounts.own_simulated.pk]})
    assert response.status_code == 500
    assert response.json()["stable_error_code"] == "AUTO_TRADING_SETUP_FAILED"
    assert response.json()["success"] is False
    assert "private connection details" not in response.content.decode()
    assert engine.builds == 1 and engine.calls == []


def test_scope_http_session_mutation_requires_csrf(accounts: _Accounts, engine: _EngineSpy) -> None:
    client, _ = _client(accounts.owner)
    response = client.post(
        reverse("api_simulated_trading:auto-trading-run"),
        {},
        format="json",
        secure=True,
        HTTP_ORIGIN="https://testserver",
    )
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert engine.builds == 0 and engine.calls == []


def test_scope_http_admin_omitted_scope_is_still_only_own_accounts(
    accounts: _Accounts, engine: _EngineSpy
) -> None:
    client, token = _client(accounts.admin)
    response = _post(client, token, {})
    assert response.status_code == 200
    assert engine.calls[0][1] == [accounts.admin_simulated.pk]


def test_scope_http_admin_explicit_managed_simulated_account_is_allowed(
    accounts: _Accounts, engine: _EngineSpy
) -> None:
    client, token = _client(accounts.admin)
    response = _post(client, token, {"account_ids": [accounts.foreign_simulated.pk]})
    assert response.status_code == 200
    assert engine.calls[0][1] == [accounts.foreign_simulated.pk]


@pytest.mark.parametrize(
    ("kind", "outcome", "confirmed", "stored", "succeeded"),
    [
        ("success", "success", 1, 1, 1),
        ("noop", "noop", 0, 0, 1),
        ("partial", "partial", 1, 1, 0),
        ("blocked", "blocked", 0, 0, 0),
        ("failed", "failed", 0, 0, 0),
        ("unknown", "failed", 0, None, 0),
        ("missing", "failed", 0, None, 0),
        ("old_shape", "failed", 0, None, 0),
        ("extra", "partial", 1, None, 0),
        ("engine_error", "failed", 0, None, 0),
    ],
)
def test_actual_http_preserves_typed_business_outcome_after_scope_preflight(
    accounts: _Accounts,
    engine: _EngineSpy,
    kind: str,
    outcome: str,
    confirmed: int,
    stored: int | None,
    succeeded: int,
) -> None:
    """Session/CSRF and ownership precede a typed, explicitly scoped result."""

    account_id = accounts.own_simulated.pk
    issue = AutoTradingIssue(
        kind=AutoTradingIssueKind.BLOCKED if kind == "blocked" else AutoTradingIssueKind.FAILED,
        stage="local_fixture",
        code="LOCAL_OUTCOME_UNAVAILABLE",
        effects_indeterminate=kind == "unknown",
    )
    issues = (issue,) if kind in {"partial", "blocked", "failed", "unknown"} else ()
    engine.result_override = {
        account_id: AccountAutoTradingOutcome(account_id, confirmed, 0, issues)
    }
    if kind == "missing":
        engine.result_override = {}
    elif kind == "old_shape":
        engine.result_override = {account_id: {"buy_count": 1, "sell_count": 0}}
    elif kind == "extra":
        engine.result_override = {
            account_id: AccountAutoTradingOutcome(account_id, 1, 0),
            accounts.foreign_simulated.pk: AccountAutoTradingOutcome(
                accounts.foreign_simulated.pk, 2, 0
            ),
        }
    elif kind == "engine_error":
        engine.error = RuntimeError("private database diagnostic must stay out of JSON")

    client, token = _client(accounts.owner)
    response = _post(client, token, {"trade_date": "2026-10-16", "account_ids": [account_id]})
    payload = response.json()

    assert response.status_code == 200
    assert payload["outcome"] == outcome
    assert payload["success"] is (outcome in {"success", "partial", "noop"})
    assert payload["requested"] == payload["total_accounts"] == 1
    assert payload["succeeded"] == succeeded
    assert payload["failed"] == 1 - succeeded
    assert payload["stored"] == stored
    assert payload["counts_unavailable"] is (stored is None)
    assert payload["count_unit"] == "account"
    assert payload["stored_count_unit"] == "trade"
    if outcome in {"partial", "blocked", "failed"}:
        assert isinstance(payload["stable_error_code"], str) and payload["stable_error_code"]
    assert payload["summary"]["total_buy_count"] == confirmed
    assert payload["summary"]["total_sell_count"] == 0
    assert set(payload["results"]) == {str(account_id)}
    assert payload["results"][str(account_id)]["confirmed_trade_count"] == confirmed
    assert engine.calls == [(date(2026, 10, 16), [account_id])]
    assert engine.builds == 1
    assert "private database diagnostic" not in response.content.decode()
    assert SimulatedTradeModel.objects.count() == 0
