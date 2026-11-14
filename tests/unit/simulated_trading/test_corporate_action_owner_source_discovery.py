"""Source discovery does not spend the current window on financial reconstruction."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from apps.data_center.domain.security_disclosure_event import PersistedSecurityDisclosureEvent
from apps.simulated_trading import corporate_action_owner_workflow_readback as readback
from core.exceptions import AuthorizationError
from tests.unit.simulated_trading.test_corporate_action_owner_event_composition import (
    _AS_OF,
    _event,
)


@pytest.mark.parametrize("has_event", (False, True))
def test_discovery_preserves_original_source_clock_and_unknown_balances(monkeypatch, has_event):
    account = SimpleNamespace(account_id=17, owner_user_id=23, asset_codes=("000001.SZ",))

    class OwnedRow:
        def using(self, *args):
            return self

        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            assert kwargs == {
                "pk": 17,
                "user_id": 23,
                "account_type": "simulated",
                "is_active": True,
            }
            return self

        def first(self):
            return account

    monkeypatch.setattr(
        readback, "SimulatedAccountModel", SimpleNamespace(_base_manager=OwnedRow())
    )
    monkeypatch.setattr(readback.transaction, "atomic", lambda **kwargs: nullcontext())
    monkeypatch.setattr(readback.timezone, "now", lambda: _AS_OF)
    records = (PersistedSecurityDisclosureEvent(_event(), recorded_at=_AS_OF),) if has_event else ()
    monkeypatch.setattr(readback, "read_owner_workflow_events", lambda *args, **kwargs: records)
    monkeypatch.setattr(
        readback,
        "read_locked_owner_corporate_action_posting_state",
        lambda **kwargs: pytest.fail("source discovery cannot rebuild original financial rows"),
    )
    monkeypatch.setattr(
        readback,
        "read_locked_owner_corporate_action_balance",
        lambda **kwargs: pytest.fail("source discovery cannot rebuild tax and NAV"),
    )
    payload = readback.read_owner_workflow_source_payload(account)
    assert payload["outcome"] == "success"
    assert payload["must_not_use_for_decision"] is True
    assert payload["freshness_status"] == "not_qualified"
    assert payload["source_observed_at"] == (
        records[0].event.first_seen_at.isoformat() if records else None
    )
    assert all(
        payload[key] is None
        for key in (
            "book_cash",
            "spendable_cash",
            "net_asset_value",
            "dividend_receivable",
            "tax_payable",
        )
    )
    assert payload["audit_receipts"] == []


def test_discovery_rechecks_current_owner_before_event_disclosure(monkeypatch):
    class MissingOwner:
        def using(self, *args):
            return self

        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            return self

        def first(self):
            return None

    monkeypatch.setattr(
        readback, "SimulatedAccountModel", SimpleNamespace(_base_manager=MissingOwner())
    )
    monkeypatch.setattr(readback.transaction, "atomic", lambda **kwargs: nullcontext())
    monkeypatch.setattr(
        readback,
        "read_owner_workflow_events",
        lambda *args, **kwargs: pytest.fail("foreign event read"),
    )
    with pytest.raises(AuthorizationError):
        readback.read_owner_workflow_source_payload(
            SimpleNamespace(account_id=17, owner_user_id=23)
        )
