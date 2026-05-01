from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application.unified_position_service import UnifiedPositionService

pytestmark = pytest.mark.django_db


class _FakePositionRepository:
    def __init__(self):
        self._records: dict[tuple[int, str], SimpleNamespace] = {}
        self._next_id = 1

    def get_by_account(self, account_id: int):
        return [record for (acc_id, _), record in self._records.items() if acc_id == account_id]

    def get_position_by_id(self, position_id: int):
        for record in self._records.values():
            if record.id == position_id:
                return record
        return None

    def get_position(self, account_id: int, asset_code: str):
        return self._records.get((account_id, asset_code))

    def save_position_record(self, *, account_id: int, asset_code: str, defaults: dict):
        key = (account_id, asset_code)
        record = self._records.get(key)
        if record is None:
            record = SimpleNamespace(id=self._next_id, account_id=account_id, asset_code=asset_code)
            self._next_id += 1
        for field, value in defaults.items():
            setattr(record, field, value)
        self._records[key] = record
        return record

    def delete(self, account_id: int, asset_code: str) -> bool:
        return self._records.pop((account_id, asset_code), None) is not None


class _FakeTradeRepository:
    def __init__(self):
        self.created_records: list[dict] = []
        self.saved_entities: list[object] = []

    def create_trade_record(self, **payload):
        self.created_records.append(payload)
        return SimpleNamespace(id=len(self.created_records), **payload)

    def save(self, trade):
        self.saved_entities.append(trade)
        return len(self.saved_entities)


class _FakePositionMutationRepository:
    def __init__(self, position_repo: _FakePositionRepository, trade_repo: _FakeTradeRepository):
        self._position_repo = position_repo
        self._trade_repo = trade_repo

    def create_or_merge_position_with_buy_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        position_defaults: dict,
        trade_payload: dict,
    ):
        record = self._position_repo.save_position_record(
            account_id=account_id,
            asset_code=asset_code,
            defaults=position_defaults,
        )
        self._trade_repo.create_trade_record(**trade_payload)
        return record

    def close_position_with_sell_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        remaining_position_defaults: dict | None,
        trade,
    ) -> None:
        self._trade_repo.save(trade)
        if remaining_position_defaults is None:
            self._position_repo.delete(account_id, asset_code)
            return

        self._position_repo.save_position_record(
            account_id=account_id,
            asset_code=asset_code,
            defaults=remaining_position_defaults,
        )


def _make_service(position_repo=None, trade_repo=None, mutation_repo=None) -> UnifiedPositionService:
    position_repo = position_repo or _FakePositionRepository()
    trade_repo = trade_repo or _FakeTradeRepository()
    return UnifiedPositionService(
        account_repo=SimpleNamespace(),
        position_repo=position_repo,
        trade_repo=trade_repo,
        mutation_repo=mutation_repo or _FakePositionMutationRepository(position_repo, trade_repo),
    )


def test_create_position_merges_existing_position_and_records_buy_trade():
    position_repo = _FakePositionRepository()
    trade_repo = _FakeTradeRepository()
    service = _make_service(position_repo=position_repo, trade_repo=trade_repo)

    existing = position_repo.save_position_record(
        account_id=1,
        asset_code="000001.SH",
        defaults={
            "asset_name": "Ping An",
            "asset_type": "equity",
            "quantity": Decimal("10.000000"),
            "available_quantity": Decimal("10.000000"),
            "avg_cost": Decimal("10.0000"),
            "total_cost": Decimal("100.00"),
            "current_price": Decimal("10.0000"),
            "market_value": Decimal("100.00"),
            "unrealized_pnl": Decimal("0.00"),
            "unrealized_pnl_pct": 0.0,
            "first_buy_date": date(2026, 4, 1),
            "last_update_date": date(2026, 4, 1),
            "signal_id": 7,
            "entry_reason": "initial",
            "invalidation_rule_json": None,
            "invalidation_description": "",
            "is_invalidated": False,
            "invalidation_reason": "",
            "invalidation_checked_at": None,
        },
    )

    updated = service.create_position(
        account_id=1,
        asset_code="000001.SH",
        shares=5,
        price=20,
        current_price=22,
        asset_name="Ping An",
    )

    assert updated.id == existing.id
    assert updated.quantity == Decimal("15.000000")
    assert updated.avg_cost == Decimal("13.3333")
    assert updated.current_price == Decimal("22.0000")
    assert updated.market_value == Decimal("330.00")
    assert len(trade_repo.created_records) == 1
    assert trade_repo.created_records[0]["action"] == "buy"


def test_update_position_recalculates_derived_fields():
    position_repo = _FakePositionRepository()
    service = _make_service(position_repo=position_repo)

    position_repo.save_position_record(
        account_id=2,
        asset_code="510300.SH",
        defaults={
            "asset_name": "CSI300 ETF",
            "asset_type": "fund",
            "quantity": Decimal("100.000000"),
            "available_quantity": Decimal("100.000000"),
            "avg_cost": Decimal("4.0000"),
            "total_cost": Decimal("400.00"),
            "current_price": Decimal("4.0000"),
            "market_value": Decimal("400.00"),
            "unrealized_pnl": Decimal("0.00"),
            "unrealized_pnl_pct": 0.0,
            "first_buy_date": date(2026, 4, 1),
            "last_update_date": date(2026, 4, 1),
            "signal_id": None,
            "entry_reason": "initial",
            "invalidation_rule_json": None,
            "invalidation_description": "",
            "is_invalidated": False,
            "invalidation_reason": "",
            "invalidation_checked_at": None,
        },
    )

    updated = service.update_position(
        account_id=2,
        asset_code="510300.SH",
        shares=120,
        avg_cost=4.5,
        current_price=5,
    )

    assert updated.quantity == Decimal("120.000000")
    assert updated.total_cost == Decimal("540.00")
    assert updated.market_value == Decimal("600.00")
    assert updated.unrealized_pnl == Decimal("60.00")
    assert updated.unrealized_pnl_pct == 11.11111111111111


def test_close_position_partially_updates_remaining_position_and_records_sell_trade():
    position_repo = _FakePositionRepository()
    trade_repo = _FakeTradeRepository()
    service = _make_service(position_repo=position_repo, trade_repo=trade_repo)

    position_repo.save_position_record(
        account_id=3,
        asset_code="159915.SZ",
        defaults={
            "asset_name": "创业板 ETF",
            "asset_type": "fund",
            "quantity": Decimal("10.000000"),
            "available_quantity": Decimal("10.000000"),
            "avg_cost": Decimal("10.0000"),
            "total_cost": Decimal("100.00"),
            "current_price": Decimal("12.0000"),
            "market_value": Decimal("120.00"),
            "unrealized_pnl": Decimal("20.00"),
            "unrealized_pnl_pct": 20.0,
            "first_buy_date": date(2026, 4, 1),
            "last_update_date": date(2026, 4, 1),
            "signal_id": 9,
            "entry_reason": "initial",
            "invalidation_rule_json": None,
            "invalidation_description": "",
            "is_invalidated": False,
            "invalidation_reason": "",
            "invalidation_checked_at": None,
        },
    )

    remaining = service.close_position(
        account_id=3,
        asset_code="159915.SZ",
        close_shares=4,
        close_price=12,
        reason="take profit",
    )

    assert remaining.quantity == Decimal("6.000000")
    assert remaining.market_value == Decimal("72.00")
    assert remaining.unrealized_pnl == Decimal("12.00")
    assert len(trade_repo.saved_entities) == 1
    assert trade_repo.saved_entities[0].action.value == "sell"
    assert trade_repo.saved_entities[0].realized_pnl == 8.0


def test_close_position_fully_deletes_position():
    position_repo = _FakePositionRepository()
    service = _make_service(position_repo=position_repo, trade_repo=_FakeTradeRepository())

    position_repo.save_position_record(
        account_id=4,
        asset_code="600000.SH",
        defaults={
            "asset_name": "浦发银行",
            "asset_type": "equity",
            "quantity": Decimal("3.000000"),
            "available_quantity": Decimal("3.000000"),
            "avg_cost": Decimal("8.0000"),
            "total_cost": Decimal("24.00"),
            "current_price": Decimal("8.5000"),
            "market_value": Decimal("25.50"),
            "unrealized_pnl": Decimal("1.50"),
            "unrealized_pnl_pct": 6.25,
            "first_buy_date": date(2026, 4, 1),
            "last_update_date": date(2026, 4, 1),
            "signal_id": None,
            "entry_reason": "initial",
            "invalidation_rule_json": None,
            "invalidation_description": "",
            "is_invalidated": False,
            "invalidation_reason": "",
            "invalidation_checked_at": datetime.now(timezone.utc),
        },
    )

    result = service.close_position(account_id=4, asset_code="600000.SH")

    assert result is None
    assert position_repo.get_position(4, "600000.SH") is None
