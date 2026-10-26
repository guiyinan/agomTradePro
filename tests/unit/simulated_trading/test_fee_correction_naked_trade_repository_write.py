"""Compatibility guards for direct simulated Trade repository inserts."""

from __future__ import annotations

from typing import Any

import pytest

from apps.simulated_trading.infrastructure import trade_repository
from core.exceptions import BusinessLogicError


class _FakeTradeModel:
    def __init__(self) -> None:
        self.id: int | None = None
        self.save_called = False

    def save(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.save_called = True
        self.id = 712


def test_save_rejects_direct_trade_insert_before_model_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeTradeModel()
    monkeypatch.setattr(trade_repository.SimulatedTradeMapper, "to_model", lambda trade: model)

    with pytest.raises(BusinessLogicError) as exc_info:
        trade_repository.DjangoTradeRepository().save(object())  # type: ignore[arg-type]

    assert exc_info.value.code == "SIMULATED_TRADE_ATOMIC_WRITE_REQUIRED"
    assert model.save_called is False


def test_create_trade_record_rejects_direct_manager_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        trade_repository.SimulatedTradeModel._default_manager,
        "create",
        lambda **payload: calls.append(payload),
    )

    with pytest.raises(BusinessLogicError) as exc_info:
        trade_repository.DjangoTradeRepository().create_trade_record(account_id=1)

    assert exc_info.value.code == "SIMULATED_TRADE_ATOMIC_WRITE_REQUIRED"
    assert calls == []
