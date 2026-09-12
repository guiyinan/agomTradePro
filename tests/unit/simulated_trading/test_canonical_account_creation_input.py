"""Identity-free creation input preserves the existing account-type behavior."""

from dataclasses import fields

import pytest

from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.simulated_trading.application.canonical_account_creation_input import (
    CanonicalAccountCreationInput,
)
from apps.simulated_trading.application.canonical_account_creation_request import (
    CanonicalAccountCreationRequestInvalid,
)
from apps.simulated_trading.domain.entities import AccountType


def _input(account_type: AccountType = AccountType.SIMULATED) -> CanonicalAccountCreationInput:
    return CanonicalAccountCreationInput(
        request_key="request-1",
        account_name="account",
        account_type=account_type,
        initial_capital=100000.0,
        max_position_pct=20.0,
        stop_loss_pct=None,
        commission_rate=0.0003,
        slippage_rate=0.001,
    )


@pytest.mark.parametrize("account_type", [AccountType.REAL, AccountType.SIMULATED])
def test_bind_uses_only_server_identity_and_existing_auto_trading_rule(
    account_type: AccountType,
) -> None:
    parameters = _input(account_type)
    assert not {"actor_id", "user_id", "auto_trading_enabled"} & {
        field.name for field in fields(parameters)
    }
    bound = parameters.bind(CanonicalAccountCreationRequester(actor_id="django-user:2", user_id=2))
    assert (bound.actor_id, bound.user_id) == ("django-user:2", 2)
    assert bound.auto_trading_enabled is (account_type is AccountType.SIMULATED)
    assert bound.request_key == parameters.request_key


def test_bind_validates_input_before_any_creation_stage() -> None:
    from dataclasses import replace

    malformed = replace(_input(), initial_capital=float("nan"))
    with pytest.raises(CanonicalAccountCreationRequestInvalid):
        malformed.bind(CanonicalAccountCreationRequester(actor_id="django-user:2", user_id=2))


def test_binding_identity_changes_request_identity() -> None:
    parameters = _input()
    first = parameters.bind(CanonicalAccountCreationRequester(actor_id="django-user:1", user_id=1))
    second = parameters.bind(CanonicalAccountCreationRequester(actor_id="django-user:2", user_id=2))
    assert first.identity_hash != second.identity_hash
