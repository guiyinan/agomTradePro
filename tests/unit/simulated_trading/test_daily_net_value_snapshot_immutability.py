"""Daily net-value snapshot idempotency contract."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.infrastructure import daily_net_value_repository as repository_module
from apps.simulated_trading.infrastructure.daily_net_value_repository import (
    DjangoDailyNetValueRepository,
)


class _LockedAccountQuery:
    def using(self, alias: str) -> _LockedAccountQuery:
        assert alias
        return self

    def select_for_update(self) -> _LockedAccountQuery:
        return self

    def filter(self, **kwargs: Any) -> _LockedAccountQuery:
        assert kwargs == {"pk": 17}
        return self

    def first(self) -> object:
        return object()


class _DailyRecordManager:
    def __init__(self) -> None:
        self.get_or_create_calls: list[dict[str, object]] = []

    def using(self, alias: str) -> _DailyRecordManager:
        assert alias
        return self

    def filter(self, **kwargs: object) -> _DailyRecordManager:
        assert kwargs == {"account_id": 17, "record_date": date(2026, 1, 2)}
        return self

    def exists(self) -> bool:
        return True

    def get_or_create(self, **kwargs: object) -> tuple[object, bool]:
        self.get_or_create_calls.append(kwargs)
        return object(), False

    def update_or_create(self, **kwargs: object) -> tuple[object, bool]:
        raise AssertionError("an existing daily snapshot must never be rewritten")


def test_existing_daily_snapshot_is_a_noop_after_parent_snapshot_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimulatedAccount(
        account_id=17,
        account_name="immutable-snapshot",
        account_type=AccountType.SIMULATED,
        initial_capital=100.0,
        current_cash=100.0,
        current_market_value=0.0,
        total_value=100.0,
        start_date=date(2026, 1, 1),
    )
    daily_manager = _DailyRecordManager()
    account_manager = _LockedAccountQuery()
    monkeypatch.setattr(repository_module.transaction, "atomic", lambda **_: nullcontext())
    monkeypatch.setattr(repository_module, "_require_account_snapshot_matches", lambda *_: None)
    monkeypatch.setattr(
        repository_module,
        "SimulatedAccountModel",
        SimpleNamespace(_default_manager=account_manager),
    )
    monkeypatch.setattr(
        repository_module,
        "DailyNetValueModel",
        SimpleNamespace(_default_manager=daily_manager),
    )
    payload = {
        "net_value": 100.0,
        "cash": 100.0,
        "market_value": 0.0,
        "daily_return": 0.0,
        "cumulative_return": 0.0,
        "drawdown": 0.0,
        "total_trades": 0,
        "positions_count": 0,
    }

    created = DjangoDailyNetValueRepository().upsert_daily_record(
        account_id=17,
        record_date=date(2026, 1, 2),
        payload=payload,
        expected_account=account,
    )

    assert created is False
    assert daily_manager.get_or_create_calls == []
