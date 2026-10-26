"""Fail-closed contract for the snapshot-less Position compatibility writer."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from datetime import date
from typing import NoReturn

import pytest

from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure import position_repository
from apps.simulated_trading.infrastructure.position_repository import DjangoPositionRepository
from core.exceptions import BusinessLogicError


def _position() -> Position:
    """Return a complete entity that could otherwise overwrite persisted costs."""

    return Position(
        account_id=41,
        asset_code="600000.SH",
        asset_name="Position repository fixture",
        asset_type="equity",
        quantity=100.0,
        available_quantity=100.0,
        avg_cost=10.0,
        total_cost=1000.0,
        current_price=10.0,
        market_value=1000.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 25),
        last_update_date=date(2026, 10, 25),
    )


def test_save_requires_expected_snapshot_before_transaction_or_orm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare stale entity is rejected before starting a transaction or locking rows."""

    calls: list[str] = []

    def atomic(*, using: str) -> AbstractContextManager[None]:
        calls.append(f"atomic:{using}")
        return nullcontext()

    def lock_account(account_id: int) -> NoReturn:
        calls.append(f"lock:{account_id}")
        raise RuntimeError("position save attempted ORM access before the guard")

    monkeypatch.setattr(position_repository.transaction, "atomic", atomic)
    monkeypatch.setattr(position_repository, "_lock_account_for_order_guard", lock_account)

    with pytest.raises(BusinessLogicError) as rejected:
        DjangoPositionRepository().save(_position())

    assert rejected.value.code == "SIMULATED_POSITION_ATOMIC_WRITE_REQUIRED"
    assert "预期快照" in rejected.value.message
    assert calls == []
