"""Account-level fee-correction currency continuity contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.simulated_trading.domain.fee_correction import (
    CorrectableFeeComponents,
    calculate_fee_correction_delta,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_history import (
    account_ledger_currency_from_events,
    correction_event_payload_hash,
    require_account_ledger_currency,
    validate_event_chains,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
    fee_correction_account_prefix_sha256,
)
from apps.simulated_trading.infrastructure.fee_correction_repository_support import (
    _authority_snapshot_sha256,
    validate_authority_snapshot_event,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError


def _utc_text(value: datetime) -> str:
    """Serialize one fixture timestamp using the persisted UTC snapshot form."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _account() -> SimulatedAccountModel:
    """Return an unsaved simulated account with an explicit owner identity."""

    return SimulatedAccountModel(
        pk=501,
        user_id=77,
        account_name="currency-continuity-unit-fixture",
        account_type="simulated",
        initial_capital=Decimal("1000.00"),
        current_cash=Decimal("900.00"),
        current_market_value=Decimal("100.00"),
        total_value=Decimal("1000.00"),
        is_active=True,
    )


def _trade(trade_id: int, execution_time: datetime) -> SimulatedTradeModel:
    """Return one unsaved, exact-fee Trade for the persisted-history validator."""

    return SimulatedTradeModel(
        pk=trade_id,
        account_id=501,
        asset_code=f"60000{trade_id}.SH",
        action="buy",
        execution_time=execution_time,
        commission=Decimal("0.05"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        fee_amounts_known=True,
        slippage=Decimal("0.01"),
    )


def _event(
    *,
    event_id: int,
    account_revision: int,
    currency: str,
    trade: SimulatedTradeModel,
    predecessor_hash: str,
    posted_at: datetime,
) -> SimulatedFeeCorrectionEventModel:
    """Build a self-consistent synthetic event bound to one policy currency."""

    previous = CorrectableFeeComponents(
        commission=Decimal("0.05"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    revised = CorrectableFeeComponents(
        commission=Decimal("0.04"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    delta = calculate_fee_correction_delta(previous, revised)
    observed_at = datetime(2026, 10, 24, 1, tzinfo=UTC)
    verified_at = datetime(2026, 10, 24, 2, tzinfo=UTC)
    authority_hash = hashlib.sha256(f"policy:{currency}".encode()).hexdigest()
    revision = 1
    authority_snapshot: dict[str, object] = {
        "policy_version": 1 if currency == "CNY" else 2,
        "policy_sha256": authority_hash,
        "policy_enabled": True,
        "policy_allows_operator_attested_upload": True,
        "policy_ledger_currency": currency,
        "policy_valid_from": None,
        "policy_valid_until": None,
        "policy_updated_by_id": 77,
        "principal_enabled": True,
        "authorization_scope": "simulated_fee_correction:operator_attested_upload",
    }
    event = SimulatedFeeCorrectionEventModel(
        pk=event_id,
        account_id=501,
        trade_id=trade.pk,
        actor_user_id=77,
        revision=revision,
        account_revision=account_revision,
        account_predecessor_hash=predecessor_hash,
        account_prefix_hash="0" * 64,
        previous_event_id=None,
        idempotency_key=f"currency-fixture-{event_id}",
        trade_snapshot_hash=hashlib.sha256(f"trade:{trade.pk}".encode()).hexdigest(),
        receipt_snapshot_hash=None,
        source_namespace="operator_attested_upload",
        source_record_id=f"binding:{event_id}",
        verifier_identity="unit-fixture-verifier",
        source_evidence_hash=hashlib.sha256(f"evidence:{event_id}".encode()).hexdigest(),
        source_payload_hash=hashlib.sha256(f"payload:{event_id}".encode()).hexdigest(),
        source_observed_at=observed_at,
        evidence_verified_at=verified_at,
        authority_identity="owner-policy",
        authority_record_id=f"policy:501:{authority_snapshot['policy_version']}",
        authority_hash=authority_hash,
        authority_snapshot_json=authority_snapshot,
        authority_snapshot_sha256="0" * 64,
        previous_commission=previous.commission,
        previous_transfer_fee=previous.transfer_fee,
        previous_stamp_duty=previous.stamp_duty,
        revised_commission=revised.commission,
        revised_transfer_fee=revised.transfer_fee,
        revised_stamp_duty=revised.stamp_duty,
        original_slippage=Decimal("0.01"),
        commission_delta=delta.commission,
        transfer_fee_delta=delta.transfer_fee,
        stamp_duty_delta=delta.stamp_duty,
        total_fee_delta=delta.total_fee_delta,
        cash_delta=delta.cash_delta,
        posted_at=posted_at,
        posting_date=timezone.localdate(posted_at),
    )
    event.request_payload_hash = correction_event_payload_hash(event)
    snapshot = {
        "schema": "simulated-fee-correction-authority-event.v1",
        "account_id": 501,
        "account_owner_user_id": 77,
        "account_type": "simulated",
        "account_active": True,
        "actor_user_id": 77,
        "actor_authenticated": True,
        "principal_enabled": True,
        "authority_identity": event.authority_identity,
        "authority_record_id": event.authority_record_id,
        "authority_sha256": authority_hash,
        "authorization_scope": "simulated_fee_correction:operator_attested_upload",
        **authority_snapshot,
        "trade_id": trade.pk,
        "trade_snapshot_hash": event.trade_snapshot_hash,
        "original_v4_receipt_hash": None,
        "receipt_snapshot_hash": None,
        "source_namespace": event.source_namespace,
        "source_record_id": event.source_record_id,
        "verifier_identity": event.verifier_identity,
        "source_evidence_hash": event.source_evidence_hash,
        "source_payload_hash": event.source_payload_hash,
        "source_observed_at": _utc_text(observed_at),
        "evidence_verified_at": _utc_text(verified_at),
        "request_payload_hash": event.request_payload_hash,
        "idempotency_key": event.idempotency_key,
        "revision": revision,
        "account_revision": account_revision,
        "account_predecessor_hash": predecessor_hash,
        "previous_event_id": None,
        "previous_fees": {
            "commission": "0.05",
            "transfer_fee": "0.00",
            "stamp_duty": "0.00",
        },
        "revised_fees": {
            "commission": "0.04",
            "transfer_fee": "0.00",
            "stamp_duty": "0.00",
        },
        "original_slippage": "0.01",
        "posting_time": _utc_text(posted_at),
        "posting_date": event.posting_date.isoformat(),
    }
    event.authority_snapshot_json = snapshot
    event.authority_snapshot_sha256 = _authority_snapshot_sha256(snapshot)
    event.account_prefix_hash = fee_correction_account_prefix_sha256(
        account_id=event.account_id,
        account_revision=account_revision,
        predecessor_sha256=predecessor_hash,
        request_payload_sha256=event.request_payload_hash,
        cash_delta=event.cash_delta,
        authority_snapshot_sha256=event.authority_snapshot_sha256,
        posted_at=posted_at,
        posting_date=event.posting_date,
    )
    return event


def _history(
    currencies: tuple[str, ...],
) -> tuple[
    SimulatedAccountModel,
    tuple[SimulatedTradeModel, ...],
    tuple[SimulatedFeeCorrectionEventModel, ...],
]:
    """Build an internally sealed synthetic account history for currency cases."""

    account = _account()
    base_time = datetime(2026, 10, 24, 1, tzinfo=UTC)
    trades = tuple(_trade(701 + index, base_time) for index in range(len(currencies)))
    predecessor_hash = fee_correction_account_genesis_sha256(account.pk)
    events: list[SimulatedFeeCorrectionEventModel] = []
    for index, (currency, trade) in enumerate(zip(currencies, trades, strict=True)):
        event = _event(
            event_id=801 + index,
            account_revision=index + 1,
            currency=currency,
            trade=trade,
            predecessor_hash=predecessor_hash,
            posted_at=datetime(2026, 10, 24, 3 + index, tzinfo=UTC),
        )
        events.append(event)
        predecessor_hash = event.account_prefix_hash
    return account, trades, tuple(events)


def _validate_history(
    account: SimulatedAccountModel,
    trades: tuple[SimulatedTradeModel, ...],
    events: tuple[SimulatedFeeCorrectionEventModel, ...],
) -> dict[int, tuple[SimulatedFeeCorrectionEventModel, ...]]:
    """Run the actual pure history chain validator over the synthetic rows."""

    return validate_event_chains(
        account=account,
        trade_rows=trades,
        event_rows=events,
        receipt_by_trade={},
        fingerprint_by_trade={event.trade_id: event.trade_snapshot_hash for event in events},
    )


def test_history_rejects_individually_valid_events_with_mixed_ledger_currency() -> None:
    """Two valid local snapshots in different currencies must not share one cash ledger."""

    account, trades, events = _history(("CNY", "USD"))
    for event in events:
        assert validate_authority_snapshot_event(event, original_v4_receipt_hash=None)

    with pytest.raises(BusinessLogicError) as error:
        _validate_history(account, trades, events)

    assert error.value.code == "FEE_CORRECTION_CURRENCY_MISMATCH"


def test_same_currency_history_remains_valid_and_establishes_account_currency() -> None:
    """Consistent event snapshots establish the account's existing currency."""

    account, trades, events = _history(("CNY", "CNY"))

    validated = _validate_history(account, trades, events)

    assert set(validated) == {trade.pk for trade in trades}
    assert account_ledger_currency_from_events(events) == "CNY"
    assert (
        require_account_ledger_currency(
            event_rows=events,
            authorization_currency="CNY",
        )
        == "CNY"
    )


def test_first_event_currency_comes_from_explicit_authorized_policy() -> None:
    """An empty history has no inferred currency until current policy supplies it."""

    assert (
        require_account_ledger_currency(
            event_rows=(),
            authorization_currency="USD",
        )
        == "USD"
    )


def test_new_correction_cannot_switch_an_established_account_currency() -> None:
    """A valid but different current policy currency is refused before a new write."""

    _, _, events = _history(("CNY",))

    with pytest.raises(BusinessLogicError) as error:
        require_account_ledger_currency(
            event_rows=events,
            authorization_currency="USD",
        )

    assert error.value.code == "FEE_CORRECTION_CURRENCY_MISMATCH"


def test_history_without_currency_snapshot_is_unknown() -> None:
    """Missing currency is not treated as a default for old event history."""

    account, trades, events = _history(("CNY",))
    del events[0].authority_snapshot_json["policy_ledger_currency"]

    with pytest.raises(BusinessLogicError) as error:
        _validate_history(account, trades, events)

    assert error.value.code == "FEE_CORRECTION_HISTORY_INVALID"
