"""Cash reconstruction merges persisted Trade and correction posting times."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.infrastructure.fee_correction_history import (
    _reconstruct_cash_by_posting_time,
)
from core.exceptions import BusinessLogicError


def _trade(trade_id: int, *, created_at: datetime, amount: str) -> SimpleNamespace:
    """Return a fully evidenced BUY cash row with an explicit persisted time."""

    money = Decimal(amount)
    return SimpleNamespace(
        pk=trade_id,
        account_id=41,
        status="executed",
        action="buy",
        created_at=created_at,
        amount=money,
        total_cost=money,
        commission=Decimal("0.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.00"),
        fee_amounts_known=True,
    )


def _time(hour: int) -> datetime:
    """Build one aware fixture posting time."""

    return datetime(2026, 10, 24, hour, tzinfo=UTC)


def test_fee_refund_is_posted_before_a_later_buy_in_cash_replay() -> None:
    """A booked refund can fund a later BUY without rewriting the original Trade."""

    original_buy = _trade(1, created_at=_time(9), amount="90.00")
    refund = SimpleNamespace(
        trade_id=1,
        posted_at=_time(10),
        cash_delta=Decimal("50.00"),
    )
    later_buy = _trade(2, created_at=_time(11), amount="55.00")

    ending_cash = _reconstruct_cash_by_posting_time(
        initial_cash=Decimal("100.00"),
        trade_rows=(original_buy, later_buy),
        event_rows=(refund,),
    )

    assert original_buy.total_cost == Decimal("90.00")
    assert refund.cash_delta == Decimal("50.00")
    assert ending_cash == Decimal("5.00")


def test_cash_history_rejects_a_buy_that_precedes_the_refund_and_overdraws() -> None:
    """A later refund cannot conceal a proven earlier negative cash balance."""

    original_buy = _trade(1, created_at=_time(9), amount="90.00")
    overdrawing_buy = _trade(2, created_at=_time(10), amount="20.00")
    later_refund = SimpleNamespace(
        trade_id=1,
        posted_at=_time(11),
        cash_delta=Decimal("50.00"),
    )

    with pytest.raises(BusinessLogicError) as error:
        _reconstruct_cash_by_posting_time(
            initial_cash=Decimal("100.00"),
            trade_rows=(original_buy, overdrawing_buy),
            event_rows=(later_refund,),
        )

    assert error.value.code == "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED"


def test_same_time_refund_and_debit_require_a_safe_worst_case_order() -> None:
    """Equal timestamps are accepted only when debits-first remains solvent."""

    original_buy = _trade(1, created_at=_time(9), amount="90.00")
    same_time_refund = SimpleNamespace(
        trade_id=1,
        posted_at=_time(10),
        cash_delta=Decimal("50.00"),
    )
    same_time_buy = _trade(2, created_at=_time(10), amount="20.00")

    with pytest.raises(BusinessLogicError) as error:
        _reconstruct_cash_by_posting_time(
            initial_cash=Decimal("100.00"),
            trade_rows=(original_buy, same_time_buy),
            event_rows=(same_time_refund,),
        )

    assert error.value.code == "FEE_CORRECTION_CASH_HISTORY_ORDER_UNKNOWN"
