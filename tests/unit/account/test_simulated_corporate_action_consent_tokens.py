"""Preparation tokens never authenticate owners or survive terms/scope substitution."""

from datetime import timedelta

import pytest

from apps.account import simulated_corporate_action_consent_composition as tokens
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    SimulatedCorporateActionGrantConsent,
)
from tests.unit.account.test_simulated_corporate_action_write_grant import _AT, _grant
from tests.unit.account.test_simulated_corporate_action_write_grant_seal import _key


def _command():
    grant = _grant()
    return SimulatedCorporateActionGrantConsent(
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        physical_account_id=41,
        expected_binding=grant.binding,
        valid_until=_AT + timedelta(minutes=5),
        consent=True,
    )


def test_displayed_consent_terms_roundtrip_only_with_explicit_owner_confirmation(monkeypatch):
    _key(monkeypatch)
    command = _command()
    token = tokens.prepare_simulated_action_consent_token(command, as_of=_AT)
    restored = tokens.restore_simulated_action_consent_token(
        token,
        owner_user_id=command.expected_binding.owner_user_id,
        physical_account_id=41,
        confirmed=True,
        as_of=_AT + timedelta(seconds=1),
    )
    assert restored == command


@pytest.mark.parametrize(
    "mutation", ["owner", "account", "unconfirmed", "expired", "future", "seal"]
)
def test_consent_preparation_cannot_be_promoted_across_owner_scope_or_clock(monkeypatch, mutation):
    _key(monkeypatch)
    command = _command()
    token = tokens.prepare_simulated_action_consent_token(command, as_of=_AT)
    kwargs = {
        "owner_user_id": command.expected_binding.owner_user_id,
        "physical_account_id": 41,
        "confirmed": True,
        "as_of": _AT,
    }
    if mutation == "owner":
        kwargs["owner_user_id"] += 1
    elif mutation == "account":
        kwargs["physical_account_id"] += 1
    elif mutation == "unconfirmed":
        kwargs["confirmed"] = False
    elif mutation == "expired":
        kwargs["as_of"] = command.valid_until
    elif mutation == "future":
        kwargs["as_of"] = _AT - timedelta(seconds=1)
    else:
        token = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(token, **kwargs)


def test_withdrawal_locator_is_distinct_and_keeps_exact_historical_target(monkeypatch):
    _key(monkeypatch)
    grant = _grant()
    token = tokens.prepare_simulated_action_withdrawal_token(grant, physical_account_id=41)
    assert (
        tokens.restore_simulated_action_withdrawal_token(
            token, owner_user_id=grant.binding.owner_user_id, physical_account_id=41
        )
        == grant.selector
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=grant.binding.owner_user_id,
            physical_account_id=41,
            confirmed=True,
            as_of=_AT,
        )


def test_rotating_the_server_key_invalidates_a_preparation_token(monkeypatch):
    _key(monkeypatch)
    token = tokens.prepare_simulated_action_consent_token(_command(), as_of=_AT)
    _key(monkeypatch, b"b" * 32)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=_command().expected_binding.owner_user_id,
            physical_account_id=41,
            confirmed=True,
            as_of=_AT,
        )
