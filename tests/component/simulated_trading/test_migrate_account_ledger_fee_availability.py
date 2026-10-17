"""Private real-ORM tests for fee availability in account-ledger migration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from typing import Literal, Protocol
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import connection, models

from apps.account.infrastructure.classification_models import (
    AssetCategoryModel,
    CurrencyModel,
)
from apps.account.infrastructure.portfolio_models import (
    BrokerTradeImportBatchModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.management.commands.migrate_account_ledger import (
    Command,
    MigrationStats,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=["django.contrib.auth", "django.contrib.contenttypes"],
)

FeeAmounts = tuple[Decimal, Decimal, Decimal, Decimal]
FeeStates = tuple[bool | None, bool | None, bool | None, bool | None]
TradeAction = Literal["buy", "sell"]
TRADED_AT = datetime(2026, 4, 7, 10, 15, tzinfo=UTC)
_SCHEMA_MODELS: tuple[type[models.Model], ...] = (
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PositionModel,
    BrokerTradeImportBatchModel,
    TransactionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
    LedgerMigrationMapModel,
)


class _DjangoDbBlocker(Protocol):
    def unblock(self) -> AbstractContextManager[None]:
        """Allow the fixture to create and clean only its isolated model tables."""


@pytest.fixture(autouse=True)
def _schema(
    django_db_setup: object,
    django_db_blocker: _DjangoDbBlocker,
) -> Iterator[None]:
    """Reuse migrated tables or create and clean only the source and target tables."""

    del django_db_setup
    with django_db_blocker.unblock():
        with isolated_schema(_SCHEMA_MODELS):
            yield


def _new_user(label: str) -> User:
    """Create a real auth owner without unrelated user-provisioning signals."""

    username = f"ledger-fee-{label}-{uuid4().hex}"
    User._default_manager.bulk_create([User(username=username, is_active=True)])
    return User._default_manager.get(username=username)


def _new_source_transaction(
    label: str,
    *,
    action: TradeAction = "buy",
    fees: FeeAmounts = (
        Decimal("12.34"),
        Decimal("2.35"),
        Decimal("3.46"),
        Decimal("1.78"),
    ),
    known: FeeStates = (True, True, True, True),
    shares: float = 100.0,
    price: Decimal = Decimal("10.0000"),
    notional: Decimal = Decimal("1000.00"),
) -> tuple[User, PortfolioModel, TransactionModel]:
    """Persist one actual account transaction and its actual owning portfolio."""

    owner = _new_user(label)
    portfolio = PortfolioModel._default_manager.create(
        user=owner,
        name=f"migration fee {label}",
    )
    row = TransactionModel._default_manager.create(
        portfolio=portfolio,
        action=action,
        asset_code="600000.SH",
        shares=shares,
        price=price,
        notional=notional,
        commission=fees[0],
        slippage=fees[1],
        stamp_duty=fees[2],
        transfer_fee=fees[3],
        commission_known=known[0],
        slippage_known=known[1],
        stamp_duty_known=known[2],
        transfer_fee_known=known[3],
        traded_at=TRADED_AT,
        notes=f"migration fixture {label}",
    )
    return owner, portfolio, row


def _link_portfolio_to_simulated_account(
    owner: User,
    portfolio: PortfolioModel,
) -> SimulatedAccountModel:
    """Create real target account and portfolio migration-map rows."""

    account = SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=f"migrated {portfolio.pk}",
        account_type="real",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table="simulated_account",
        target_id=account.pk,
    )
    return account


def _empty_stats() -> MigrationStats:
    """Return every counter required by the actual migration command."""

    return {
        "portfolios_skipped": 0,
        "portfolios_migrated": 0,
        "positions_skipped": 0,
        "positions_migrated": 0,
        "transactions_skipped": 0,
        "transactions_skipped_unknown_costs": 0,
        "transactions_migrated": 0,
        "errors": [],
    }


def _migrate_transactions(owner_id: int, *, dry_run: bool) -> MigrationStats:
    """Call only the actual transaction migration phase with real ORM tables."""

    stats = _empty_stats()
    command = Command(stdout=StringIO())
    command._migrate_transactions(user_id=owner_id, dry_run=dry_run, stats=stats)
    return stats


@pytest.mark.parametrize(
    ("fee_state_field", "unknown_state"),
    [
        pytest.param("commission_known", False, id="commission-false"),
        pytest.param("commission_known", None, id="commission-null"),
        pytest.param("slippage_known", False, id="slippage-false"),
        pytest.param("slippage_known", None, id="slippage-null"),
        pytest.param("stamp_duty_known", False, id="stamp-duty-false"),
        pytest.param("stamp_duty_known", None, id="stamp-duty-null"),
        pytest.param("transfer_fee_known", False, id="transfer-fee-false"),
        pytest.param("transfer_fee_known", None, id="transfer-fee-null"),
    ],
)
def test_any_unknown_fee_is_skipped_before_portfolio_map_in_dry_and_apply(
    fee_state_field: str,
    unknown_state: bool | None,
) -> None:
    """Unknown fees count consistently and create neither trade nor map."""

    owner, _, row = _new_source_transaction("unknown-fees")
    setattr(row, fee_state_field, unknown_state)
    row.save(update_fields=[fee_state_field])

    assert not LedgerMigrationMapModel._default_manager.exists()

    dry_stats = _migrate_transactions(owner.pk, dry_run=True)
    apply_stats = _migrate_transactions(owner.pk, dry_run=False)

    assert dry_stats == apply_stats
    for stats in (dry_stats, apply_stats):
        assert stats["transactions_skipped_unknown_costs"] == 1
        assert stats["transactions_skipped"] == 1
        assert stats["transactions_migrated"] == 0
        assert stats["errors"] == []
    assert not SimulatedTradeModel._default_manager.exists()
    assert not LedgerMigrationMapModel._default_manager.exists()


@pytest.mark.parametrize(
    ("action", "expected_total_cost"),
    [
        pytest.param("buy", Decimal("1019.93"), id="buy-includes-principal-and-fees"),
        pytest.param("sell", Decimal("19.93"), id="sell-total-is-fees-only"),
    ],
)
def test_known_transaction_migrates_all_fees_and_source_execution_time(
    action: TradeAction,
    expected_total_cost: Decimal,
) -> None:
    """Store all known costs and copy traded_at over the auto-now target field."""

    owner, portfolio, source = _new_source_transaction("known-fees", action=action)
    _link_portfolio_to_simulated_account(owner, portfolio)

    stats = _migrate_transactions(owner.pk, dry_run=False)

    assert stats["transactions_migrated"] == 1
    assert stats["transactions_skipped_unknown_costs"] == 0
    transaction_map = LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="transaction",
        source_id=source.pk,
    )
    trade = SimulatedTradeModel._default_manager.get(pk=transaction_map.target_id)
    assert (
        trade.commission,
        trade.slippage,
        trade.stamp_duty,
        trade.transfer_fee,
    ) == (
        Decimal("12.34"),
        Decimal("2.35"),
        Decimal("3.46"),
        Decimal("1.78"),
    )
    assert trade.amount == Decimal("1000.00")
    assert trade.total_cost == expected_total_cost
    assert trade.total_cost == (
        trade.amount + Decimal("19.93") if action == "buy" else Decimal("19.93")
    )
    assert trade.execution_time == TRADED_AT


def test_existing_transaction_map_makes_a_second_apply_idempotent() -> None:
    """A source transaction already mapped to a trade is not duplicated."""

    owner, portfolio, source = _new_source_transaction("idempotent")
    _link_portfolio_to_simulated_account(owner, portfolio)

    first_stats = _migrate_transactions(owner.pk, dry_run=False)
    first_map = LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="transaction",
        source_id=source.pk,
    )
    second_stats = _migrate_transactions(owner.pk, dry_run=False)

    assert first_stats["transactions_migrated"] == 1
    assert second_stats["transactions_migrated"] == 0
    assert second_stats["transactions_skipped"] == 1
    assert SimulatedTradeModel._default_manager.count() == 1
    assert (
        LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="transaction",
            source_id=source.pk,
            target_id=first_map.target_id,
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    ("case", "shares", "price", "notional", "postgres_only"),
    [
        pytest.param(
            "nan",
            float("nan"),
            Decimal("10.0000"),
            Decimal("1000.00"),
            True,
            id="nan-pg-source",
        ),
        pytest.param(
            "infinity",
            float("inf"),
            Decimal("10.0000"),
            Decimal("1000.00"),
            False,
            id="infinity-pg-source",
        ),
        pytest.param(
            "negative",
            -1.0,
            Decimal("10.0000"),
            Decimal("10.00"),
            False,
            id="negative",
        ),
        pytest.param("zero", 0.0, Decimal("10.0000"), Decimal("0.00"), False, id="zero"),
        pytest.param(
            "rounds-to-zero",
            0.00000001,
            Decimal("10.0000"),
            Decimal("0.00"),
            False,
            id="positive-quantizes-to-zero",
        ),
        pytest.param(
            "quantity-overflow",
            100000000000000.0,
            Decimal("0.0001"),
            Decimal("10000000000.00"),
            False,
            id="quantity-overflow-20-6",
        ),
    ],
)
def test_invalid_source_quantity_is_explicitly_skipped_in_dry_and_apply(
    case: str,
    shares: float,
    price: Decimal,
    notional: Decimal,
    postgres_only: bool,
) -> None:
    """Reject invalid or unrepresentable source quantities before creating a trade/map."""

    if postgres_only and connection.vendor != "postgresql":
        pytest.skip("Non-finite FloatField cases require PostgreSQL source storage")

    owner, portfolio, source = _new_source_transaction(
        f"invalid-quantity-{case}",
        shares=shares,
        price=price,
        notional=notional,
    )
    _link_portfolio_to_simulated_account(owner, portfolio)

    dry_stats = _migrate_transactions(owner.pk, dry_run=True)
    apply_stats = _migrate_transactions(owner.pk, dry_run=False)

    assert dry_stats == apply_stats
    for stats in (dry_stats, apply_stats):
        assert stats["transactions_skipped"] == 1
        assert stats["transactions_skipped_unknown_costs"] == 0
        assert stats["transactions_migrated"] == 0
        assert len(stats["errors"]) == 1
        reason = stats["errors"][0]
        assert f"交易 {source.pk}" in reason
        assert "数量" in reason or "范围" in reason
    assert not SimulatedTradeModel._default_manager.exists()
    assert not LedgerMigrationMapModel._default_manager.filter(
        source_app="account",
        source_table="transaction",
        source_id=source.pk,
    ).exists()


def test_large_target_legal_decimal_amount_and_buy_total_are_exact() -> None:
    """Preserve an exact source Decimal amount within target numeric limits."""

    owner, portfolio, source = _new_source_transaction(
        "large-legal-decimal",
        shares=100000000.01,
        price=Decimal("12345.6789"),
        notional=Decimal("1234567890123.46"),
    )
    _link_portfolio_to_simulated_account(owner, portfolio)

    stats = _migrate_transactions(owner.pk, dry_run=False)

    assert stats["transactions_migrated"] == 1
    transaction_map = LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="transaction",
        source_id=source.pk,
    )
    trade = SimulatedTradeModel._default_manager.get(pk=transaction_map.target_id)
    # 12345.6789 * 100000000.01 = 1234567890123.456789, rounded to cents.
    assert trade.price == Decimal("12345.6789")
    assert trade.quantity == Decimal("100000000.010000")
    assert trade.amount == Decimal("1234567890123.46")
    assert trade.total_cost == Decimal("1234567890143.39")
    assert trade.total_cost == trade.amount + Decimal("19.93")
