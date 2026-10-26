from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application.unified_position_service import UnifiedPositionService
from apps.simulated_trading.domain.entities import Position, SimulatedTrade
from core.exceptions import BusinessLogicError

pytestmark = pytest.mark.django_db


@dataclass
class _PositionRecord(Position):
    """Domain Position with the repository test row's local identifier."""

    id: int = 0


def _position_snapshot_matches(
    current: _PositionRecord | None,
    expected: Position | None,
    *,
    account_id: int,
    asset_code: str,
) -> bool:
    """Check actual Position snapshot fields before a fake repository write."""

    if expected is None:
        return current is None
    if current is None:
        return False
    return (
        expected.account_id == account_id
        and expected.asset_code == asset_code
        and current.account_id == expected.account_id
        and current.asset_code == expected.asset_code
        and current.asset_name == expected.asset_name
        and current.asset_type == expected.asset_type
        and current.quantity == expected.quantity
        and current.available_quantity == expected.available_quantity
        and current.avg_cost == expected.avg_cost
        and current.total_cost == expected.total_cost
        and current.current_price == expected.current_price
        and current.market_value == expected.market_value
        and current.unrealized_pnl == expected.unrealized_pnl
        and current.unrealized_pnl_pct == expected.unrealized_pnl_pct
        and current.first_buy_date == expected.first_buy_date
        and current.last_update_date == expected.last_update_date
        and current.available_quantity_known is expected.available_quantity_known
        and current.first_buy_date_known is expected.first_buy_date_known
        and current.valuation_known is expected.valuation_known
        and current.cost_basis_known == expected.cost_basis_known
        and current.signal_id == expected.signal_id
        and current.entry_reason == expected.entry_reason
        and current.invalidation_rule_json == expected.invalidation_rule_json
        and current.invalidation_description == expected.invalidation_description
        and current.is_invalidated is expected.is_invalidated
        and current.invalidation_reason == expected.invalidation_reason
        and current.invalidation_checked_at == expected.invalidation_checked_at
    )


class _FakePositionRepository:
    def __init__(self):
        self._records: dict[tuple[int, str], _PositionRecord] = {}
        self._next_id = 1

    def get_by_account(self, account_id: int) -> list[_PositionRecord]:
        return [record for (acc_id, _), record in self._records.items() if acc_id == account_id]

    def get_position_by_id(self, position_id: int) -> _PositionRecord | None:
        for record in self._records.values():
            if record.id == position_id:
                return record
        return None

    def get_position(self, account_id: int, asset_code: str) -> _PositionRecord | None:
        return self._records.get((account_id, asset_code))

    def save_position_record(
        self,
        *,
        account_id: int,
        asset_code: str,
        defaults: dict[str, object],
        expected_position: Position | None = None,
    ) -> _PositionRecord:
        key = (account_id, asset_code)
        record = self._records.get(key)
        if not _position_snapshot_matches(
            record,
            expected_position,
            account_id=account_id,
            asset_code=asset_code,
        ):
            raise BusinessLogicError(
                "Position changed during test mutation",
                code="POSITION_CHANGED_RETRY_REQUIRED",
            )
        if record is None:
            record = _PositionRecord(
                id=self._next_id,
                account_id=account_id,
                asset_code=asset_code,
                asset_name="",
                asset_type="equity",
                quantity=0.0,
                available_quantity=0.0,
                avg_cost=0.0,
                total_cost=0.0,
                current_price=0.0,
                market_value=0.0,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
                first_buy_date=date.min,
                last_update_date=date.min,
            )
            self._next_id += 1
        for field, value in defaults.items():
            setattr(record, field, value)
        self._records[key] = record
        return record

    def delete(self, account_id: int, asset_code: str) -> bool:
        return self._records.pop((account_id, asset_code), None) is not None


class _FakeTradeRepository:
    def __init__(self):
        self.created_records: list[dict[str, object]] = []
        self.saved_entities: list[SimulatedTrade] = []

    def create_trade_record(self, **payload: object) -> SimpleNamespace:
        self.created_records.append(payload)
        return SimpleNamespace(id=len(self.created_records), **payload)

    def save(self, trade: SimulatedTrade) -> int:
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
        position_defaults: dict[str, object],
        trade_payload: dict[str, object],
        expected_position: Position | None = None,
    ) -> _PositionRecord:
        record = self._position_repo.save_position_record(
            account_id=account_id,
            asset_code=asset_code,
            defaults=position_defaults,
            expected_position=expected_position,
        )
        self._trade_repo.create_trade_record(**trade_payload)
        return record

    def close_position_with_sell_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        remaining_position_defaults: dict[str, object] | None,
        expected_position: Position,
        trade: SimulatedTrade,
    ) -> None:
        if not _position_snapshot_matches(
            self._position_repo.get_position(account_id, asset_code),
            expected_position,
            account_id=account_id,
            asset_code=asset_code,
        ):
            raise BusinessLogicError(
                "Position changed during test close",
                code="POSITION_CHANGED_RETRY_REQUIRED",
            )
        self._trade_repo.save(trade)
        if remaining_position_defaults is None:
            self._position_repo.delete(account_id, asset_code)
            return

        self._position_repo.save_position_record(
            account_id=account_id,
            asset_code=asset_code,
            defaults=remaining_position_defaults,
            expected_position=expected_position,
        )


def _make_service(
    position_repo=None, trade_repo=None, mutation_repo=None
) -> UnifiedPositionService:
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
    assert updated.cost_basis_known is None


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
            "cost_basis_known": True,
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
            "invalidation_checked_at": datetime.now(UTC),
        },
    )

    result = service.close_position(account_id=4, asset_code="600000.SH")

    assert result is None
    assert position_repo.get_position(4, "600000.SH") is None


def test_close_position_normalizes_float_backed_domain_quantity_for_partial_close():
    position_repo = _FakePositionRepository()
    trade_repo = _FakeTradeRepository()
    service = _make_service(position_repo=position_repo, trade_repo=trade_repo)

    position_repo.save_position_record(
        account_id=5,
        asset_code="000001.SZ",
        defaults={
            "asset_name": "Ping An Bank",
            "asset_type": "equity",
            "quantity": 100.0,
            "available_quantity": 100.0,
            "avg_cost": 10.0,
            "total_cost": 1000.0,
            "current_price": 11.0,
            "market_value": 1100.0,
            "unrealized_pnl": 100.0,
            "unrealized_pnl_pct": 10.0,
            "first_buy_date": date(2026, 1, 2),
            "last_update_date": date(2026, 1, 2),
            "signal_id": None,
            "entry_reason": "initial",
            "invalidation_rule_json": None,
            "invalidation_description": "",
            "is_invalidated": False,
            "invalidation_reason": "",
            "invalidation_checked_at": None,
        },
    )

    result = service.close_position(
        account_id=5,
        asset_code="000001.SZ",
        close_shares=40,
    )

    assert result.quantity == Decimal("60.000000")
    assert trade_repo.saved_entities[0].quantity == Decimal("40.000000")
    assert trade_repo.saved_entities[0].amount == 440.0


def test_close_position_rejects_quantity_above_position_without_mutation():
    position_repo = _FakePositionRepository()
    trade_repo = _FakeTradeRepository()
    service = _make_service(position_repo=position_repo, trade_repo=trade_repo)
    position_repo.save_position_record(
        account_id=6,
        asset_code="000001.SZ",
        defaults={"quantity": Decimal("10.000000")},
    )

    with pytest.raises(ValueError, match="close_shares_exceeds_position"):
        service.close_position(
            account_id=6,
            asset_code="000001.SZ",
            close_shares=Decimal("10.000001"),
        )

    assert position_repo.get_position(6, "000001.SZ").quantity == Decimal("10.000000")
    assert trade_repo.saved_entities == []


def _position_defaults_for_sellability_test(
    *,
    quantity: Decimal,
    available_quantity: Decimal,
    available_quantity_known: bool,
) -> dict[str, object]:
    """Build one complete in-memory record for availability lifecycle tests."""

    return {
        "asset_name": "Sellability fixture",
        "asset_type": "equity",
        "quantity": quantity,
        "available_quantity": available_quantity,
        "available_quantity_known": available_quantity_known,
        "avg_cost": Decimal("10.0000"),
        "total_cost": Decimal("1000.00"),
        "current_price": Decimal("10.0000"),
        "market_value": Decimal("1000.00"),
        "unrealized_pnl": Decimal("0.00"),
        "unrealized_pnl_pct": 0.0,
        "first_buy_date": date(2026, 10, 1),
        "last_update_date": date(2026, 10, 1),
        "signal_id": None,
        "entry_reason": "sellability fixture",
        "invalidation_rule_json": None,
        "invalidation_description": "",
        "is_invalidated": False,
        "invalidation_reason": "",
        "invalidation_checked_at": None,
    }


def test_close_position_rejects_unknown_available_quantity_without_writes():
    position_repo = _FakePositionRepository()
    trade_repo = _FakeTradeRepository()
    service = _make_service(position_repo=position_repo, trade_repo=trade_repo)
    position = position_repo.save_position_record(
        account_id=7,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("100"),
            available_quantity_known=False,
        ),
    )

    with pytest.raises(BusinessLogicError):
        service.close_position(
            account_id=7,
            asset_code="600000.SH",
            close_shares=Decimal("50"),
            close_price=Decimal("10"),
        )

    assert position.quantity == Decimal("100")
    assert position.available_quantity == Decimal("100")
    assert position.available_quantity_known is False
    assert trade_repo.saved_entities == []


def test_close_position_rejects_sell_larger_than_known_available_quantity():
    position_repo = _FakePositionRepository()
    trade_repo = _FakeTradeRepository()
    service = _make_service(position_repo=position_repo, trade_repo=trade_repo)
    position = position_repo.save_position_record(
        account_id=8,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("40"),
            available_quantity_known=True,
        ),
    )

    with pytest.raises(BusinessLogicError):
        service.close_position(
            account_id=8,
            asset_code="600000.SH",
            close_shares=Decimal("50"),
            close_price=Decimal("10"),
        )

    assert position.quantity == Decimal("100")
    assert position.available_quantity == Decimal("40")
    assert position.available_quantity_known is True
    assert trade_repo.saved_entities == []


def test_create_position_merge_does_not_upgrade_unknown_available_quantity():
    position_repo = _FakePositionRepository()
    service = _make_service(position_repo=position_repo)
    existing = position_repo.save_position_record(
        account_id=9,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("40"),
            available_quantity_known=False,
        ),
    )

    merged = service.create_position(
        account_id=9,
        asset_code="600000.SH",
        shares=10,
        price=10,
    )

    assert merged.id == existing.id
    assert merged.available_quantity_known is False


def test_update_position_does_not_upgrade_unknown_available_quantity():
    position_repo = _FakePositionRepository()
    service = _make_service(position_repo=position_repo)
    existing = position_repo.save_position_record(
        account_id=10,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("40"),
            available_quantity_known=False,
        ),
    )

    updated = service.update_position(
        account_id=10,
        asset_code="600000.SH",
        shares=120,
        avg_cost=10,
        current_price=10,
    )

    assert updated is not None
    assert updated.available_quantity_known is False
    assert existing.available_quantity_known is False


def test_price_update_preserves_known_partial_sellable_balance() -> None:
    """A valuation change supplies no evidence that pending shares became sellable."""
    repository = _FakePositionRepository()
    repository.save_position_record(
        account_id=11,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("40"),
            available_quantity_known=True,
        ),
    )

    result = _make_service(position_repo=repository).update_position(
        account_id=11,
        asset_code="600000.SH",
        current_price=11,
    )

    assert result is not None
    assert result.available_quantity == Decimal("40")
    assert result.available_quantity_known is True


def test_total_quantity_calibration_does_not_certify_sellability() -> None:
    """Changing only total shares does not establish the broker's available shares."""
    repository = _FakePositionRepository()
    repository.save_position_record(
        account_id=12,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("40"),
            available_quantity_known=True,
        ),
    )

    result = _make_service(position_repo=repository).update_position(
        account_id=12,
        asset_code="600000.SH",
        shares=120,
    )

    assert result is not None
    assert result.quantity == Decimal("120")
    assert result.available_quantity_known is False


def test_partial_close_subtracts_from_known_available_balance() -> None:
    """Selling part of the available balance cannot release the remaining pending shares."""
    repository = _FakePositionRepository()
    repository.save_position_record(
        account_id=13,
        asset_code="600000.SH",
        defaults=_position_defaults_for_sellability_test(
            quantity=Decimal("100"),
            available_quantity=Decimal("40"),
            available_quantity_known=True,
        ),
    )

    result = _make_service(position_repo=repository).close_position(
        account_id=13,
        asset_code="600000.SH",
        close_shares=30,
        close_price=10,
    )

    assert result is not None
    assert result.quantity == Decimal("70")
    assert result.available_quantity == Decimal("10")
    assert result.available_quantity_known is True
