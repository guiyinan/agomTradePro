"""Explicit simulation date conventions never establish real custody dates."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.simulated_tax_date_convention import (
    SimulatedDividendTaxDateConvention,
    derive_simulated_dividend_tax_date,
)
from tests.unit.simulated_trading.test_execution_settlement_uow import _calendar

AT = datetime(2026, 10, 16, 7, tzinfo=UTC)


def _rule(**changes):
    return replace(
        SimulatedDividendTaxDateConvention(
            convention_id="explicit-simulation-date-rule",
            version="1",
            physical_account_id=41,
            canonical_account_id="simulated-41",
            owner_user_id=7,
            exchange="SH",
            purchase_open_session_offset=1,
            sale_open_session_offset=0,
            trade_window_start=date(2026, 10, 16),
            trade_window_end=date(2026, 10, 19),
            valid_from=AT - timedelta(days=1),
            valid_until=AT + timedelta(days=7),
            known_at=AT - timedelta(hours=2),
            approval_ref="owner-20261112-simulated-tax-dates",
        ),
        **changes,
    )


def _map(**changes):
    args = {
        "convention": _rule(),
        "calendar": _calendar(as_of=AT),
        "account_kind": "simulated",
        "physical_account_id": 41,
        "canonical_account_id": "simulated-41",
        "owner_user_id": 7,
        "trade_id": "fill-1",
        "trade_payload_sha256": "a" * 64,
        "side": "buy",
        "trade_occurred_at": AT - timedelta(hours=1),
        "trade_observed_at": AT - timedelta(minutes=30),
        "as_of": AT,
    }
    args.update(changes)
    return derive_simulated_dividend_tax_date(**args)


@pytest.mark.parametrize(
    ("side", "expected"), [("buy", date(2026, 10, 19)), ("sell", date(2026, 10, 16))]
)
def test_explicit_separate_offsets_use_published_open_sessions(side, expected):
    result = _map(side=side)
    assert result.trade_session == date(2026, 10, 16)
    assert result.modeled_tax_date == expected
    assert result.must_not_use_as_real_custody_proof is True
    assert result.basis == "simulated_open_session_offset"
    assert result.convention_sha256 == _rule().semantic_sha256
    assert result.trade_occurred_at == AT - timedelta(hours=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"account_kind": "real"},
        {"account_kind": "paper"},
        {"physical_account_id": 42},
        {"physical_account_id": True},
        {"canonical_account_id": "simulated-42"},
        {"owner_user_id": 8},
        {"side": "BUY"},
        {"side": True},
        {"trade_payload_sha256": "unknown"},
        {"trade_id": ""},
        {"trade_occurred_at": datetime(2026, 10, 16, 6)},
        {"trade_observed_at": AT + timedelta(seconds=1)},
        {"trade_occurred_at": AT + timedelta(seconds=1)},
        {"trade_observed_at": AT - timedelta(hours=2)},
    ],
)
def test_real_or_mismatched_scope_and_invalid_original_clocks_are_rejected(changes):
    with pytest.raises(DeferredDividendTaxValidationError):
        _map(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"purchase_open_session_offset": True},
        {"sale_open_session_offset": -1},
        {"trade_window_start": datetime(2026, 10, 16)},
        {"trade_window_end": date(2026, 10, 15)},
        {"valid_until": AT - timedelta(days=2)},
        {"known_at": datetime(2026, 10, 16, 5)},
        {"approval_ref": ""},
    ],
)
def test_configuration_requires_explicit_typed_scope_window_offsets_and_approval(changes):
    with pytest.raises(DeferredDividendTaxValidationError):
        _rule(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_until": AT},
        {"known_at": AT + timedelta(seconds=1)},
        {"valid_from": AT + timedelta(seconds=1)},
        {"exchange": "SZ"},
        {"trade_window_start": date(2026, 10, 17)},
        {"purchase_open_session_offset": 2},
    ],
)
def test_inactive_unseen_wrong_exchange_or_uncovered_dates_fail_closed(changes):
    with pytest.raises(DeferredDividendTaxValidationError):
        _map(convention=_rule(**changes))


def test_reference_only_calendar_cannot_supply_a_modeled_tax_date():
    with pytest.raises(DeferredDividendTaxValidationError):
        _map(calendar=_calendar(as_of=AT, published=False))


def test_closed_trade_day_is_rejected_instead_of_shifted_to_a_weekday():
    later = AT + timedelta(days=1)
    with pytest.raises(DeferredDividendTaxValidationError):
        _map(
            calendar=_calendar(as_of=later),
            trade_occurred_at=later - timedelta(hours=1),
            trade_observed_at=later - timedelta(minutes=30),
            as_of=later,
        )


def test_trade_date_uses_the_calendar_timezone_instead_of_utc_date():
    result = _map(trade_occurred_at=datetime(2026, 10, 15, 16, tzinfo=UTC))
    assert result.trade_session == date(2026, 10, 16)


def test_read_refresh_changes_observation_hash_but_not_modeled_semantics():
    first = _map()
    later = _map(as_of=AT + timedelta(minutes=1))
    assert first.semantic_sha256 == later.semantic_sha256
    assert first.observation_sha256 != later.observation_sha256
    changed = _map(convention=_rule(version="2", purchase_open_session_offset=0))
    assert first.semantic_sha256 != changed.semantic_sha256


def test_same_original_instant_with_another_offset_keeps_semantic_identity():
    first = _map()
    shifted = _map(
        trade_occurred_at=first.trade_occurred_at.astimezone(timezone(timedelta(hours=8)))
    )
    assert first.semantic_sha256 == shifted.semantic_sha256


@pytest.mark.parametrize(
    "changes",
    [
        {"must_not_use_as_real_custody_proof": False},
        {"side": []},
        {"read_at": AT + timedelta(seconds=1)},
    ],
)
def test_result_cannot_drop_the_simulation_boundary(changes):
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_map(), **changes)
