"""Creation idempotency seals caller intent independently of server row facts."""

from dataclasses import replace
from datetime import date, datetime
from math import inf, nan

import pytest

from apps.simulated_trading.application.canonical_account_creation_request import (
    CanonicalAccountCreationRequest,
    CanonicalAccountCreationRequestInvalid,
)
from apps.simulated_trading.domain.entities import AccountType


def _request() -> CanonicalAccountCreationRequest:
    return CanonicalAccountCreationRequest(
        actor_id="local-actor",
        user_id=1,
        request_key="request-one",
        account_name="local test",
        account_type=AccountType.SIMULATED,
        initial_capital=1000.0,
        auto_trading_enabled=False,
        max_position_pct=20.0,
        stop_loss_pct=None,
        commission_rate=0.0003,
        slippage_rate=0.001,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_name": "renamed"},
        {"account_type": AccountType.REAL},
        {"initial_capital": 2000.0},
        {"auto_trading_enabled": True},
        {"max_position_pct": 10.0},
        {"stop_loss_pct": 0.0},
        {"commission_rate": 0.001},
        {"slippage_rate": 0.002},
    ],
)
def test_same_key_changed_behavior_preserves_identity_but_changes_fingerprint(changes):
    original = _request()
    changed = replace(original, **changes)
    assert changed.identity_hash == original.identity_hash
    assert changed.binding_id == original.binding_id
    assert changed.allocation_command().allocation_id == original.allocation_command().allocation_id
    assert changed.fingerprint_hash != original.fingerprint_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": "another-actor"},
        {"user_id": 2},
        {"request_key": "request-two"},
    ],
)
def test_caller_or_request_key_change_is_a_distinct_identity(changes):
    original = _request()
    changed = replace(original, **changes)
    assert changed.identity_hash != original.identity_hash
    assert changed.fingerprint_hash != original.fingerprint_hash
    assert changed.binding_id != original.binding_id


def test_normalized_numeric_representations_are_the_same_behavior():
    original = replace(_request(), stop_loss_pct=0.0)
    equivalent = replace(original, initial_capital=1000, stop_loss_pct=-0.0)
    assert equivalent.fingerprint_hash == original.fingerprint_hash


def test_server_date_and_generated_row_id_are_not_request_identity():
    request = _request()
    first = request.to_account(start_date=date(2026, 9, 11))
    retry = request.to_account(start_date=date(2026, 9, 12))
    assert first.account_id == retry.account_id == 0
    assert first.start_date != retry.start_date
    assert first.current_cash == first.total_value == request.initial_capital
    assert first.current_market_value == 0
    assert request.allocation_command().request_fingerprint_hash == request.fingerprint_hash
    assert request == _request()


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": True},
        {"user_id": 0},
        {"actor_id": " "},
        {"request_key": ""},
        {"request_key": "a b"},
        {"request_key": "a" * 193},
        {"account_name": " name"},
        {"account_name": "x" * 101},
        {"account_type": "simulated"},
        {"auto_trading_enabled": 1},
        {"initial_capital": True},
        {"initial_capital": nan},
        {"initial_capital": 10**1000},
        {"commission_rate": inf},
        {"slippage_rate": "0.001"},
        {"stop_loss_pct": False},
        {"max_position_pct": None},
    ],
)
def test_invalid_boundary_values_are_not_sealed(changes):
    with pytest.raises(CanonicalAccountCreationRequestInvalid):
        replace(_request(), **changes)


def test_materialization_requires_date_not_datetime():
    with pytest.raises(CanonicalAccountCreationRequestInvalid):
        _request().to_account(start_date=datetime(2026, 9, 11))
