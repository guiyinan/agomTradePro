"""Viewing retained owner history does not require an operable current signing key."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.simulated_trading import corporate_action_owner_account_composition as account
from core.exceptions import AuthorizationError
from tests.unit.simulated_trading.test_corporate_action_current_official_window import _NOW


@pytest.mark.parametrize(
    "user,account_id",
    [
        (SimpleNamespace(pk=23, is_authenticated=False, is_active=True), 41),
        (SimpleNamespace(pk=23, is_authenticated=True, is_active=False), 41),
        (SimpleNamespace(pk=True, is_authenticated=True, is_active=True), 41),
        (SimpleNamespace(pk=23, is_authenticated=True, is_active=True), True),
    ],
)
def test_confirmation_preflight_rejects_invalid_session_before_database(
    user, account_id, monkeypatch
):
    monkeypatch.setattr(account, "connections", {})
    with pytest.raises(AuthorizationError):
        account.read_owner_corporate_action_confirmation_owner(
            SimpleNamespace(user=user), account_id=account_id
        )


@pytest.mark.parametrize("owned", (None, 41))
def test_confirmation_preflight_requires_locked_actual_owner_row(monkeypatch, owned):
    calls = []

    class Query:
        def using(self, alias):
            assert alias == "default"
            return self

        def select_for_update(self):
            calls.append("lock")
            return self

        def filter(self, **kwargs):
            calls.append(kwargs)
            return self

        def values_list(self, *args, **kwargs):
            return self

        def first(self):
            return owned

    monkeypatch.setattr(account, "connections", {"default": SimpleNamespace(vendor="postgresql")})
    monkeypatch.setattr(account.transaction, "atomic", lambda **kwargs: nullcontext())
    monkeypatch.setattr(account, "SimulatedAccountModel", SimpleNamespace(_base_manager=Query()))
    request = SimpleNamespace(user=SimpleNamespace(pk=23, is_authenticated=True, is_active=True))
    if owned is None:
        with pytest.raises(AuthorizationError):
            account.read_owner_corporate_action_confirmation_owner(request, account_id=41)
    else:
        assert account.read_owner_corporate_action_confirmation_owner(request, account_id=41) == 23
    assert calls == [
        "lock",
        {"pk": 41, "user_id": 23, "account_type": "simulated", "is_active": True},
    ]


@pytest.mark.parametrize("writing", (False, True))
def test_current_grant_unavailability_blocks_writes_but_not_historical_owner_reads(
    monkeypatch, writing
):
    def unavailable(**kwargs):
        raise SimulatedCorporateActionWriteGrantUnavailable("current seal key rotated")

    monkeypatch.setattr(account, "read_current_simulated_action_consent_metadata", unavailable)
    kwargs = {
        "canonical_account_id": "owned-canonical",
        "owner_user_id": 23,
        "as_of": _NOW,
        "using": "default",
        "required_capability": Capability.CASH_STAGE_WRITE if writing else None,
    }
    if writing:
        with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
            account._read_owner_grant_metadata(**kwargs)
    else:
        assert account._read_owner_grant_metadata(**kwargs) == (None, True)
