"""Private real-ORM tests for fee availability in account-ledger migration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from typing import Any, Literal, Protocol
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import connection, models
from django.db.models import QuerySet

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
from apps.simulated_trading.infrastructure import models as simulated_models
from apps.simulated_trading.management.commands.migrate_account_ledger import (
    Command,
    MigrationStats,
)
from tests.support.isolated_schema import isolated_schema

LedgerMigrationMapModel = simulated_models.LedgerMigrationMapModel
SimulatedPositionModel = simulated_models.PositionModel
SimulatedAccountModel = simulated_models.SimulatedAccountModel
SimulatedTradeModel = simulated_models.SimulatedTradeModel

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
    SimulatedPositionModel,
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
    *,
    account_type: str = "real",
    target_table: str = "simulated_account",
) -> SimulatedAccountModel:
    """Create real target account and portfolio migration-map rows."""

    account = SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=f"migrated {portfolio.pk}",
        account_type=account_type,
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table=target_table,
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


def _new_source_position(
    label: str,
    *,
    owner: User | None = None,
    portfolio: PortfolioModel | None = None,
    asset_code: str = "600000.SH",
    shares: float = 100.0,
    current_price: Decimal | None = Decimal("12.0000"),
) -> tuple[User, PortfolioModel, PositionModel]:
    """Persist one real legacy position with the minimum required source fields."""

    if owner is None:
        owner = _new_user(label)
    if portfolio is None:
        portfolio = PortfolioModel._default_manager.create(
            user=owner,
            name=f"migration position {label}",
        )
    position = PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code=asset_code,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=shares,
        avg_cost=Decimal("10.0000"),
        current_price=current_price,
        market_value=Decimal("1200.00"),
    )
    return owner, portfolio, position


def _migrate_positions(owner_id: int, *, dry_run: bool) -> MigrationStats:
    """Call only the real legacy-position migration phase with actual ORM tables."""

    stats = _empty_stats()
    command = Command(stdout=StringIO())
    command._migrate_positions(user_id=owner_id, dry_run=dry_run, stats=stats)
    return stats


def _link_legacy_position(
    *,
    source: PositionModel,
    account: SimulatedAccountModel,
    target: SimulatedPositionModel,
) -> LedgerMigrationMapModel:
    """Map one legacy position to an existing same-owner target holding."""

    return LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="position",
        source_id=source.pk,
        target_table="simulated_position",
        target_id=target.pk,
        notes=f"account={account.pk}",
    )


def _position_snapshot(position: SimulatedPositionModel) -> tuple[object, ...]:
    """Capture fields the migration must leave intact on conflict or replay."""

    position.refresh_from_db()
    return (
        position.account_id,
        position.asset_code,
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.avg_cost,
        position.total_cost,
        position.cost_basis_known,
        position.current_price,
        position.market_value,
        position.valuation_known,
        position.unrealized_pnl,
        position.unrealized_pnl_pct,
        position.first_buy_date,
        position.first_buy_date_known,
    )


def test_new_position_migration_preserves_total_but_marks_sellability_unknown() -> None:
    """Legacy total shares do not prove how many shares are currently sellable."""

    owner, portfolio, source = _new_source_position("unknown-sellability")
    account = _link_portfolio_to_simulated_account(owner, portfolio)

    dry_stats = _migrate_positions(owner.pk, dry_run=True)

    assert dry_stats["positions_migrated"] == 1
    assert not SimulatedPositionModel._default_manager.exists()
    assert not LedgerMigrationMapModel._default_manager.filter(
        source_table="position", source_id=source.pk
    ).exists()

    apply_stats = _migrate_positions(owner.pk, dry_run=False)

    assert apply_stats == dry_stats
    target_map = LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="position",
        source_id=source.pk,
    )
    target = SimulatedPositionModel._default_manager.get(pk=target_map.target_id)
    assert target.account_id == account.pk
    assert target.asset_code == source.asset_code
    assert target.quantity == Decimal("100.000000")
    assert target.available_quantity == Decimal("0.000000")
    assert target.available_quantity_known is False
    assert target.valuation_known is True
    assert target.first_buy_date == source.opened_at.date()
    assert target.first_buy_date_known is False
    before_replay = _position_snapshot(target)

    replay_dry = _migrate_positions(owner.pk, dry_run=True)
    replay_apply = _migrate_positions(owner.pk, dry_run=False)

    assert replay_dry == replay_apply
    assert replay_apply["positions_migrated"] == 0
    assert replay_apply["positions_skipped"] == 1
    assert replay_apply["errors"] == []
    assert _position_snapshot(target) == before_replay


@pytest.mark.parametrize(
    "source_price",
    [
        pytest.param(None, id="missing"),
        pytest.param(Decimal("0.0000"), id="zero"),
        pytest.param(Decimal("-1.0000"), id="negative"),
    ],
)
def test_invalid_source_price_stays_unknown_and_open_time_is_not_a_buy_date(
    source_price: Decimal | None,
) -> None:
    """Missing or invalid marks and open time do not create decision evidence."""

    owner, portfolio, source = _new_source_position(
        "invalid-position-price",
        current_price=source_price,
    )
    account = _link_portfolio_to_simulated_account(owner, portfolio)

    stats = _migrate_positions(owner.pk, dry_run=False)

    assert stats["positions_migrated"] == 1
    target_map = LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="position",
        source_id=source.pk,
    )
    target = SimulatedPositionModel._default_manager.get(pk=target_map.target_id)
    assert target.account_id == account.pk
    assert target.quantity == Decimal("100.000000")
    assert target.available_quantity == Decimal("0.000000")
    assert target.available_quantity_known is False
    assert target.current_price == Decimal("0.0000")
    assert target.market_value == Decimal("0.00")
    assert target.valuation_known is False
    assert target.unrealized_pnl == Decimal("0.00")
    assert target.first_buy_date == source.opened_at.date()
    assert target.first_buy_date_known is False


def test_unmapped_same_asset_is_not_merged_and_dry_run_matches_apply() -> None:
    """An unmapped target holding blocks import without mutating either position."""

    owner, portfolio, source = _new_source_position("same-asset-conflict")
    account = _link_portfolio_to_simulated_account(owner, portfolio)
    existing = SimulatedPositionModel._default_manager.create(
        account=account,
        asset_code=source.asset_code,
        asset_name="existing holding",
        asset_type="equity",
        quantity=Decimal("55.000000"),
        available_quantity=Decimal("15.000000"),
        available_quantity_known=True,
        avg_cost=Decimal("8.2500"),
        total_cost=Decimal("453.75"),
        cost_basis_known=False,
        current_price=Decimal("9.5000"),
        market_value=Decimal("522.50"),
        valuation_known=True,
        unrealized_pnl=Decimal("68.75"),
        unrealized_pnl_pct=15.1515,
        first_buy_date=TRADED_AT.date(),
        first_buy_date_known=False,
    )
    before = _position_snapshot(existing)

    dry_stats = _migrate_positions(owner.pk, dry_run=True)
    apply_stats = _migrate_positions(owner.pk, dry_run=False)

    assert dry_stats == apply_stats
    assert dry_stats["positions_migrated"] == 0
    assert dry_stats["positions_skipped"] == 1
    assert len(dry_stats["errors"]) == 1
    assert str(source.pk) in dry_stats["errors"][0]
    assert "未映射" in dry_stats["errors"][0]
    assert _position_snapshot(existing) == before
    assert SimulatedPositionModel._default_manager.count() == 1
    assert not LedgerMigrationMapModel._default_manager.filter(
        source_table="position", source_id=source.pk
    ).exists()
    assert not SimulatedTradeModel._default_manager.exists()


def test_existing_valid_position_map_is_idempotent_and_does_not_rewrite_target() -> None:
    """A valid source map makes reruns a no-op for every stored target field."""

    owner, portfolio, source = _new_source_position("position-idempotent")
    account = _link_portfolio_to_simulated_account(owner, portfolio)
    target = SimulatedPositionModel._default_manager.create(
        account=account,
        asset_code=source.asset_code,
        asset_name="already imported",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("0.000000"),
        available_quantity_known=False,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        cost_basis_known=None,
        current_price=Decimal("12.0000"),
        market_value=Decimal("1200.00"),
        valuation_known=True,
        unrealized_pnl=Decimal("200.00"),
        unrealized_pnl_pct=20.0,
        first_buy_date=TRADED_AT.date(),
        first_buy_date_known=False,
    )
    _link_legacy_position(source=source, account=account, target=target)
    before = _position_snapshot(target)

    dry_stats = _migrate_positions(owner.pk, dry_run=True)
    apply_stats = _migrate_positions(owner.pk, dry_run=False)

    assert dry_stats == apply_stats
    assert dry_stats["positions_migrated"] == 0
    assert dry_stats["positions_skipped"] == 1
    assert dry_stats["errors"] == []
    assert _position_snapshot(target) == before
    assert SimulatedPositionModel._default_manager.count() == 1
    assert (
        LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            source_id=source.pk,
            target_table="simulated_position",
            target_id=target.pk,
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    ("invalid_mapping", "account_type", "target_table"),
    [
        pytest.param("wrong-table", "real", "simulated_trade", id="wrong-target-table"),
        pytest.param("wrong-owner", "real", "simulated_account", id="cross-owner-account"),
        pytest.param("wrong-type", "simulated", "simulated_account", id="not-real-account"),
    ],
)
def test_invalid_portfolio_mapping_is_skipped_in_dry_and_apply(
    invalid_mapping: str,
    account_type: str,
    target_table: str,
) -> None:
    """Do not migrate positions through a wrong table, owner, or account kind."""

    owner, portfolio, source = _new_source_position(f"invalid-map-{invalid_mapping}")
    target_owner = _new_user("foreign-map-owner") if invalid_mapping == "wrong-owner" else owner
    account = _link_portfolio_to_simulated_account(
        target_owner,
        portfolio,
        account_type=account_type,
        target_table=target_table,
    )

    dry_stats = _migrate_positions(owner.pk, dry_run=True)
    apply_stats = _migrate_positions(owner.pk, dry_run=False)

    assert dry_stats == apply_stats
    assert dry_stats["positions_migrated"] == 0
    assert dry_stats["positions_skipped"] == 1
    assert len(dry_stats["errors"]) == 1
    assert str(source.pk) in dry_stats["errors"][0]
    assert SimulatedAccountModel._default_manager.get(pk=account.pk).user_id == target_owner.pk
    assert not SimulatedPositionModel._default_manager.exists()
    assert not LedgerMigrationMapModel._default_manager.filter(
        source_table="position", source_id=source.pk
    ).exists()
    assert not SimulatedTradeModel._default_manager.exists()


def test_duplicate_legacy_asset_is_not_combined_and_dry_run_matches_apply() -> None:
    """Dry-run accounts for a same-run import before classifying duplicate assets."""

    owner, portfolio, first_source = _new_source_position(
        "duplicate-legacy-asset-first",
        shares=100.0,
    )
    _, _, second_source = _new_source_position(
        "duplicate-legacy-asset-second",
        owner=owner,
        portfolio=portfolio,
        shares=200.0,
    )
    account = _link_portfolio_to_simulated_account(owner, portfolio)

    dry_stats = _migrate_positions(owner.pk, dry_run=True)
    apply_stats = _migrate_positions(owner.pk, dry_run=False)

    assert dry_stats == apply_stats
    assert dry_stats["positions_migrated"] == 1
    assert dry_stats["positions_skipped"] == 1
    assert len(dry_stats["errors"]) == 1
    migrated_maps = list(
        LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            target_table="simulated_position",
        )
    )
    assert len(migrated_maps) == 1
    assert migrated_maps[0].source_id in {first_source.pk, second_source.pk}
    target = SimulatedPositionModel._default_manager.get(pk=migrated_maps[0].target_id)
    assert target.account_id == account.pk
    assert target.quantity in {Decimal("100.000000"), Decimal("200.000000")}
    assert target.available_quantity == Decimal("0.000000")
    assert target.available_quantity_known is False


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("closed", id="closed-after-iterator-snapshot"),
        pytest.param("owner", id="owner-changed-after-iterator-snapshot"),
        pytest.param("portfolio", id="portfolio-changed-after-iterator-snapshot"),
    ],
)
@pytest.mark.parametrize(
    "dry_run", [pytest.param(True, id="dry-run"), pytest.param(False, id="apply")]
)
def test_source_position_is_locked_and_refreshed_before_migration(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    dry_run: bool,
) -> None:
    """The iterator's stale position snapshot cannot override changed source state."""

    owner, portfolio, source = _new_source_position(f"stale-source-{mutation}")
    _link_portfolio_to_simulated_account(owner, portfolio)
    foreign_owner = _new_user("changed-position-owner")
    replacement_portfolio = None
    if mutation == "portfolio":
        replacement_portfolio = PortfolioModel._default_manager.create(
            user=owner,
            name="replacement position portfolio",
        )

    original_iterator = QuerySet.iterator
    mutation_applied = False

    def iterator_with_source_change(
        queryset: QuerySet[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[Any]:
        nonlocal mutation_applied
        rows = list(original_iterator(queryset, *args, **kwargs))
        if queryset.model is PositionModel and not mutation_applied:
            mutation_applied = True
            if mutation == "closed":
                PositionModel._default_manager.filter(pk=source.pk).update(is_closed=True)
            elif mutation == "owner":
                PortfolioModel._default_manager.filter(pk=portfolio.pk).update(
                    user_id=foreign_owner.pk
                )
            else:
                assert replacement_portfolio is not None
                PositionModel._default_manager.filter(pk=source.pk).update(
                    portfolio_id=replacement_portfolio.pk
                )
        yield from rows

    monkeypatch.setattr(QuerySet, "iterator", iterator_with_source_change)

    stats = _migrate_positions(owner.pk, dry_run=dry_run)

    assert mutation_applied is True
    assert stats["positions_migrated"] == 0
    assert stats["positions_skipped"] == 1
    if mutation == "closed":
        assert stats["errors"] == []
    else:
        assert len(stats["errors"]) == 1
    assert not SimulatedPositionModel._default_manager.exists()
    assert not LedgerMigrationMapModel._default_manager.filter(
        source_app="account",
        source_table="position",
        source_id=source.pk,
    ).exists()
    assert not SimulatedTradeModel._default_manager.exists()


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
