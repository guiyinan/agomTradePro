"""Test caller-key deduplication at the simulated auto-run HTTP boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.domain.auto_trading_outcomes import AccountAutoTradingOutcome
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)

AUTO_RUN_PATH = "/api/simulated-trading/auto-trading/run/"
TRADE_DATE = date(2026, 10, 19)


@dataclass
class _EngineSpy:
    """Record engine entry without exercising portfolio or T+1 eligibility."""

    fail_first_run: bool = False
    build_count: int = 0
    calls: list[tuple[date, tuple[int, ...]]] = field(default_factory=list)

    def build(self, *, invocation_id: UUID, expected_owner_id: int | None = None) -> _EngineSpy:
        """Count engine construction and return this deterministic spy."""

        self.build_count += 1
        return self

    def run_daily_trading(
        self,
        trade_date: date,
        account_ids: list[int] | None = None,
    ) -> dict[int, AccountAutoTradingOutcome]:
        """Record one engine entry, optionally returning an indeterminate failure."""

        if account_ids is None:
            raise AssertionError("the API must pass its resolved account scope")
        ordered_ids = tuple(account_ids)
        self.calls.append((trade_date, ordered_ids))
        if self.fail_first_run and len(self.calls) == 1:
            raise RuntimeError("simulated unknown engine result after start")
        return {
            account_id: AccountAutoTradingOutcome(account_id, 0, 0) for account_id in ordered_ids
        }


def _create_owner_and_client() -> tuple[AbstractBaseUser, APIClient]:
    """Create one authenticated owner through the ordinary API request path."""

    user_model = get_user_model()
    owner = user_model.objects.create_user(
        username=f"auto-run-idem-{uuid4().hex}",
        password="unused-test-password",
    )
    client = APIClient()
    client.force_authenticate(user=owner)
    return owner, client


def _create_account(owner: AbstractBaseUser, label: str) -> SimulatedAccountModel:
    """Create one eligible, owner-scoped simulated account."""

    return SimulatedAccountModel.objects.create(
        user=owner,
        account_name=f"auto-run-{label}-{uuid4().hex[:8]}",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
        auto_trading_enabled=True,
    )


def _post_run(
    client: APIClient,
    *,
    idempotency_key: str,
    trade_date: date,
    account_ids: list[int],
) -> Response:
    """Post one explicit owner-authorized HTTP run with a stable caller key."""

    return client.post(
        AUTO_RUN_PATH,
        {
            "trade_date": trade_date.isoformat(),
            "account_ids": account_ids,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _install_engine_spy(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_first_run: bool = False,
) -> _EngineSpy:
    """Replace only Engine construction while preserving the real HTTP scope path."""

    spy = _EngineSpy(fail_first_run=fail_first_run)
    monkeypatch.setattr(interface_services, "build_auto_trading_engine", spy.build)
    return spy


def _assert_json(response: Response, *, status_code: int) -> None:
    """Assert the API's status and JSON media type contract."""

    assert response.status_code == status_code, response.data
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db(transaction=True)
def test_same_owner_key_and_exact_input_replays_one_noop_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op retry has no trade row to deduplicate, so it must reuse the run record."""

    owner, client = _create_owner_and_client()
    account = _create_account(owner, "replay")
    spy = _install_engine_spy(monkeypatch)
    key = "auto-run-replay-20261019"

    first = _post_run(
        client,
        idempotency_key=key,
        trade_date=TRADE_DATE,
        account_ids=[account.pk],
    )
    replay = _post_run(
        client,
        idempotency_key=key,
        trade_date=TRADE_DATE,
        account_ids=[account.pk],
    )

    _assert_json(first, status_code=200)
    _assert_json(replay, status_code=200)
    first_payload = first.json()
    replay_payload = replay.json()
    for field_name in (
        "outcome",
        "success",
        "requested",
        "succeeded",
        "failed",
        "stored",
        "counts_unavailable",
        "trade_date",
        "accounts",
        "summary",
    ):
        assert replay_payload[field_name] == first_payload[field_name]
    assert first_payload["outcome"] == "noop"
    assert first_payload["stored"] == 0
    assert spy.build_count == 1
    assert spy.calls == [(TRADE_DATE, (account.pk,))]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("changed_field", ["scope", "trade_date"])
def test_same_owner_key_with_changed_scope_or_date_conflicts_before_engine_reentry(
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    """A run key cannot be rebound to another account scope or market date."""

    owner, client = _create_owner_and_client()
    first_account = _create_account(owner, "first")
    second_account = _create_account(owner, "second")
    spy = _install_engine_spy(monkeypatch)
    key = "auto-run-conflict-20261019"

    first = _post_run(
        client,
        idempotency_key=key,
        trade_date=TRADE_DATE,
        account_ids=[first_account.pk],
    )
    changed_scope = [second_account.pk] if changed_field == "scope" else [first_account.pk]
    changed_date = TRADE_DATE + timedelta(days=1) if changed_field == "trade_date" else TRADE_DATE
    conflict = _post_run(
        client,
        idempotency_key=key,
        trade_date=changed_date,
        account_ids=changed_scope,
    )

    _assert_json(first, status_code=200)
    _assert_json(conflict, status_code=409)
    conflict_payload = conflict.json()
    assert conflict_payload["success"] is False
    assert conflict_payload["code"] == "AUTO_TRADING_RUN_IDEMPOTENCY_CONFLICT"
    assert spy.build_count == 1
    assert spy.calls == [(TRADE_DATE, (first_account.pk,))]


@pytest.mark.django_db(transaction=True)
def test_retry_after_indeterminate_started_run_does_not_enter_engine_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the run starts, an unknown result is not permission to repeat the engine."""

    owner, client = _create_owner_and_client()
    account = _create_account(owner, "indeterminate")
    spy = _install_engine_spy(monkeypatch, fail_first_run=True)
    key = "auto-run-indeterminate-20261019"

    first = _post_run(
        client,
        idempotency_key=key,
        trade_date=TRADE_DATE,
        account_ids=[account.pk],
    )
    retry = _post_run(
        client,
        idempotency_key=key,
        trade_date=TRADE_DATE,
        account_ids=[account.pk],
    )

    _assert_json(first, status_code=200)
    _assert_json(retry, status_code=200)
    first_payload = first.json()
    retry_payload = retry.json()
    for payload in (first_payload, retry_payload):
        assert payload["outcome"] == "failed"
        assert payload["stored"] is None
        assert payload["counts_unavailable"] is True
        assert payload["stable_error_code"] == "EXECUTION_OUTCOME_UNKNOWN"
        assert payload["accounts"][0]["issues"][0]["effects_indeterminate"] is True
    assert retry_payload["accounts"] == first_payload["accounts"]
    assert spy.build_count == 1
    assert spy.calls == [(TRADE_DATE, (account.pk,))]
