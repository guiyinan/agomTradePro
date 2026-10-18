"""Native historical-row and reverse-safety checks for migration 0033."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, connections
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import StateApps
from django.db.models import Model

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)
_BEFORE = ("simulated_trading", "0032_cash_knowledge")
_AFTER = ("simulated_trading", "0033_cost_basis_knowledge")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


@dataclass(frozen=True, slots=True)
class _PositionFacts:
    """Economic, availability, valuation, and clock fields present at 0032."""

    position_id: int
    account_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    quantity: Decimal
    available_quantity: Decimal
    available_quantity_known: bool
    avg_cost: Decimal
    total_cost: Decimal
    current_price: Decimal
    market_value: Decimal
    valuation_known: bool
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float
    first_buy_date: date
    first_buy_date_known: bool
    last_update_date: date
    invalidation_rule: tuple[tuple[str, str], ...]
    is_invalidated: bool
    invalidation_reason: str
    invalidation_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class _TradeFacts:
    """Economic, execution, and audit fields present at 0032."""

    trade_id: int
    account_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    action: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    commission: Decimal
    transfer_fee: Decimal | None
    stamp_duty: Decimal | None
    slippage: Decimal
    total_cost: Decimal
    realized_pnl: Decimal | None
    realized_pnl_pct: float | None
    reason: str
    order_date: date
    execution_date: date
    execution_time: datetime
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _LegacyRows:
    """IDs and full captured facts for the rows created at migration 0032."""

    account_id: int
    position_id: int
    trade_id: int
    position_facts: _PositionFacts
    trade_facts: _TradeFacts


@dataclass
class _MigrationCleanupState:
    """Remember the original graph leaf and fixture-owned account rows."""

    leaf_nodes: list[tuple[str, str]]
    account_ids: list[int] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(transactional_db: None) -> Iterator[None]:
    """Balance pytest app scopes while exposing migration dependencies."""

    del transactional_db
    expected_partial_names = tuple(sorted(_PARTIAL_APP_NAMES))
    popped_layers: list[tuple[str, ...]] = []
    try:
        for _ in range(4):
            current_names = tuple(sorted(config.name for config in django_apps.get_app_configs()))
            assert current_names == expected_partial_names
            django_apps.unset_available_apps()
            popped_layers.append(current_names)
            if django_apps.is_installed("apps.strategy"):
                break
        assert django_apps.is_installed("apps.strategy")
        yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


@pytest.fixture
def _restore_migration_graph(
    _full_app_registry_for_migration_loader: None,
) -> Iterator[_MigrationCleanupState]:
    """Delete only local fixture rows and restore the pre-test migration leaf."""

    del _full_app_registry_for_migration_loader
    state = _MigrationCleanupState(
        leaf_nodes=list(MigrationExecutor(connection).loader.graph.leaf_nodes())
    )
    try:
        yield state
    finally:
        applied = MigrationRecorder(connection).applied_migrations()
        current_target = _AFTER if _AFTER in applied else _BEFORE
        if state.account_ids:
            current_apps = MigrationExecutor(connection).loader.project_state([current_target]).apps
            if _AFTER in applied:
                position_model = cast(
                    type[Model],
                    current_apps.get_model("simulated_trading", "PositionModel"),
                )
                trade_model = cast(
                    type[Model],
                    current_apps.get_model("simulated_trading", "SimulatedTradeModel"),
                )
                position_model._base_manager.using(connection.alias).filter(
                    account_id__in=state.account_ids
                ).update(cost_basis_known=True)
                trade_model._base_manager.using(connection.alias).filter(
                    account_id__in=state.account_ids
                ).update(cost_basis_known=True, fee_amounts_known=True)
            account_model = cast(
                type[Model],
                current_apps.get_model("simulated_trading", "SimulatedAccountModel"),
            )
            account_model._base_manager.using(connection.alias).filter(
                pk__in=state.account_ids
            ).delete()
        MigrationExecutor(connection).migrate(state.leaf_nodes)


def _require_native_migration_database(django_db_use_migrations: bool) -> None:
    """Require the migrations-enabled native PostgreSQL lane for reverse proof."""

    if not django_db_use_migrations:
        pytest.skip("Cost knowledge migration proof requires migrations-enabled database")
    if connection.vendor != "postgresql":
        pytest.skip("Cost knowledge reverse guard requires native PostgreSQL")
    assert settings.AUTH_USER_MODEL == "auth.User"


def _create_legacy_rows(apps: StateApps, state: _MigrationCleanupState) -> _LegacyRows:
    """Create an account, position, and sell using only the historical 0032 state."""

    suffix = uuid4().hex[:12]
    account_model = cast(type[Model], apps.get_model("simulated_trading", "SimulatedAccountModel"))
    position_model = cast(type[Model], apps.get_model("simulated_trading", "PositionModel"))
    trade_model = cast(type[Model], apps.get_model("simulated_trading", "SimulatedTradeModel"))
    account = cast(
        Model,
        account_model._default_manager.using(connection.alias).create(
            user=None,
            account_name=f"cost-migration-{suffix}",
            account_type="simulated",
            cash_known=True,
            cash_reconciliation_status="simulated_ledger",
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("99000.00"),
            current_market_value=Decimal("1000.00"),
            total_value=Decimal("100000.00"),
        ),
    )
    account_id = cast(int, account.pk)
    state.account_ids.append(account_id)
    position = cast(
        Model,
        position_model._default_manager.using(connection.alias).create(
            account_id=account_id,
            asset_code=f"CM{suffix}",
            asset_name="Cost knowledge migration position",
            asset_type="equity",
            quantity=Decimal("100.123456"),
            available_quantity=Decimal("40.654321"),
            available_quantity_known=False,
            avg_cost=Decimal("10.1234"),
            total_cost=Decimal("1013.58"),
            current_price=Decimal("10.5678"),
            market_value=Decimal("1058.47"),
            valuation_known=False,
            unrealized_pnl=Decimal("44.89"),
            unrealized_pnl_pct=4.43,
            first_buy_date=date(2026, 10, 16),
            first_buy_date_known=False,
            entry_reason="cost knowledge migration fixture",
            invalidation_rule_json={"source": "migration-fixture"},
            invalidation_description="Preserve historical position evidence.",
            is_invalidated=True,
            invalidation_reason="fixture invalidation evidence",
            invalidation_checked_at=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
        ),
    )
    trade = cast(
        Model,
        trade_model._default_manager.using(connection.alias).create(
            account_id=account_id,
            asset_code=f"CM{suffix}",
            asset_name="Cost knowledge migration sell",
            asset_type="equity",
            action="sell",
            quantity=Decimal("40.000000"),
            price=Decimal("11.1000"),
            amount=Decimal("444.00"),
            commission=Decimal("1.11"),
            transfer_fee=Decimal("0.02"),
            stamp_duty=Decimal("0.44"),
            slippage=Decimal("0.50"),
            total_cost=Decimal("446.07"),
            realized_pnl=Decimal("32.50"),
            realized_pnl_pct=8.11,
            reason="cost knowledge migration fixture",
            order_date=date(2026, 10, 15),
            execution_date=date(2026, 10, 16),
            execution_time=datetime(2026, 10, 16, 2, 30, tzinfo=UTC),
            status="executed",
        ),
    )
    return _LegacyRows(
        account_id=account_id,
        position_id=cast(int, position.pk),
        trade_id=cast(int, trade.pk),
        position_facts=_position_facts(position),
        trade_facts=_trade_facts(trade),
    )


def _position_facts(position: Model) -> _PositionFacts:
    """Read position dates and audit clocks using distinct concrete types."""

    first_buy_date = cast(date, position.first_buy_date)
    last_update_date = cast(date, position.last_update_date)
    checked_at = cast(datetime | None, position.invalidation_checked_at)
    created_at = cast(datetime, position.created_at)
    updated_at = cast(datetime, position.updated_at)
    assert type(first_buy_date) is date
    assert type(last_update_date) is date
    for timestamp in (checked_at, created_at, updated_at):
        if timestamp is not None:
            assert timestamp.tzinfo is not None
            assert timestamp.utcoffset() is not None
    raw_rule = cast(object, position.invalidation_rule_json)
    assert isinstance(raw_rule, dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in raw_rule.items())
    rule_facts = tuple(sorted(cast(dict[str, str], raw_rule).items()))
    return _PositionFacts(
        position_id=cast(int, position.pk),
        account_id=cast(int, position.account_id),
        asset_code=cast(str, position.asset_code),
        asset_name=cast(str, position.asset_name),
        asset_type=cast(str, position.asset_type),
        quantity=cast(Decimal, position.quantity),
        available_quantity=cast(Decimal, position.available_quantity),
        available_quantity_known=cast(bool, position.available_quantity_known),
        avg_cost=cast(Decimal, position.avg_cost),
        total_cost=cast(Decimal, position.total_cost),
        current_price=cast(Decimal, position.current_price),
        market_value=cast(Decimal, position.market_value),
        valuation_known=cast(bool, position.valuation_known),
        unrealized_pnl=cast(Decimal, position.unrealized_pnl),
        unrealized_pnl_pct=cast(float, position.unrealized_pnl_pct),
        first_buy_date=first_buy_date,
        first_buy_date_known=cast(bool, position.first_buy_date_known),
        last_update_date=last_update_date,
        invalidation_rule=rule_facts,
        is_invalidated=cast(bool, position.is_invalidated),
        invalidation_reason=cast(str, position.invalidation_reason),
        invalidation_checked_at=checked_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _trade_facts(trade: Model) -> _TradeFacts:
    """Read trade date fields and aware execution/audit timestamps."""

    order_date = cast(date, trade.order_date)
    execution_date = cast(date, trade.execution_date)
    execution_time = cast(datetime, trade.execution_time)
    created_at = cast(datetime, trade.created_at)
    assert type(order_date) is date
    assert type(execution_date) is date
    for timestamp in (execution_time, created_at):
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() is not None
    return _TradeFacts(
        trade_id=cast(int, trade.pk),
        account_id=cast(int, trade.account_id),
        asset_code=cast(str, trade.asset_code),
        asset_name=cast(str, trade.asset_name),
        asset_type=cast(str, trade.asset_type),
        action=cast(str, trade.action),
        quantity=cast(Decimal, trade.quantity),
        price=cast(Decimal, trade.price),
        amount=cast(Decimal, trade.amount),
        commission=cast(Decimal, trade.commission),
        transfer_fee=cast(Decimal | None, trade.transfer_fee),
        stamp_duty=cast(Decimal | None, trade.stamp_duty),
        slippage=cast(Decimal, trade.slippage),
        total_cost=cast(Decimal, trade.total_cost),
        realized_pnl=cast(Decimal | None, trade.realized_pnl),
        realized_pnl_pct=cast(float | None, trade.realized_pnl_pct),
        reason=cast(str, trade.reason),
        order_date=order_date,
        execution_date=execution_date,
        execution_time=execution_time,
        status=cast(str, trade.status),
        created_at=created_at,
    )


def _read_legacy_rows(
    apps: StateApps,
    rows: _LegacyRows,
    alias: str,
) -> tuple[_PositionFacts, _TradeFacts, Model, Model]:
    """Read both target rows from a specified historical app registry."""

    position_model = cast(type[Model], apps.get_model("simulated_trading", "PositionModel"))
    trade_model = cast(type[Model], apps.get_model("simulated_trading", "SimulatedTradeModel"))
    position = cast(
        Model,
        position_model._default_manager.using(alias).get(pk=rows.position_id),
    )
    trade = cast(
        Model,
        trade_model._default_manager.using(alias).get(pk=rows.trade_id),
    )
    return _position_facts(position), _trade_facts(trade), position, trade


def _table_columns(apps: StateApps, alias: str, model_name: str) -> set[str]:
    """Return physical columns for one historical simulated-trading model."""

    model = cast(type[Model], apps.get_model("simulated_trading", model_name))
    database_connection = connections[alias]
    with database_connection.cursor() as cursor:
        description = database_connection.introspection.get_table_description(
            cursor,
            model._meta.db_table,
        )
    return {cast(str, column.name) for column in description}


def _cost_knowledge_columns(apps: StateApps, alias: str) -> tuple[set[str], set[str]]:
    """Return current physical position and trade columns for the new flags."""

    return (
        _table_columns(apps, alias, "PositionModel"),
        _table_columns(apps, alias, "SimulatedTradeModel"),
    )


def test_0033_adds_nullable_flags_without_changing_legacy_facts_or_clocks(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Forward migration keeps every captured 0032 value and starts flags unknown."""

    _require_native_migration_database(django_db_use_migrations)
    state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    rows = _create_legacy_rows(before_apps, state)
    before_position_fields = {
        field.name
        for field in cast(
            type[Model], before_apps.get_model("simulated_trading", "PositionModel")
        )._meta.get_fields()
    }
    before_trade_fields = {
        field.name
        for field in cast(
            type[Model],
            before_apps.get_model("simulated_trading", "SimulatedTradeModel"),
        )._meta.get_fields()
    }
    assert "cost_basis_known" not in before_position_fields
    assert "cost_basis_known" not in before_trade_fields
    assert "fee_amounts_known" not in before_trade_fields

    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    position_facts, trade_facts, position, trade = _read_legacy_rows(after_apps, rows, alias)
    assert position_facts == rows.position_facts
    assert trade_facts == rows.trade_facts
    assert position.cost_basis_known is None
    assert trade.cost_basis_known is None
    assert trade.fee_amounts_known is None
    position_columns, trade_columns = _cost_knowledge_columns(after_apps, alias)
    assert "cost_basis_known" in position_columns
    assert {"cost_basis_known", "fee_amounts_known"} <= trade_columns
    assert _AFTER in MigrationRecorder(connection).applied_migrations()


@pytest.mark.parametrize(
    ("target_table", "target_field", "unknown_value"),
    (
        pytest.param("position", "cost_basis_known", None, id="position-null"),
        pytest.param("position", "cost_basis_known", False, id="position-false"),
        pytest.param("trade", "cost_basis_known", None, id="trade-basis-null"),
        pytest.param("trade", "cost_basis_known", False, id="trade-basis-false"),
        pytest.param("trade", "fee_amounts_known", None, id="trade-fees-null"),
        pytest.param("trade", "fee_amounts_known", False, id="trade-fees-false"),
    ),
)
def test_0033_refuses_reverse_for_any_unknown_or_partial_row_and_retains_schema(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
    target_table: Literal["position", "trade"],
    target_field: Literal["cost_basis_known", "fee_amounts_known"],
    unknown_value: bool | None,
) -> None:
    """A single null or false flag preserves all new columns, facts, and recorder state."""

    _require_native_migration_database(django_db_use_migrations)
    state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    rows = _create_legacy_rows(before_apps, state)
    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    position_model = cast(type[Model], after_apps.get_model("simulated_trading", "PositionModel"))
    trade_model = cast(
        type[Model],
        after_apps.get_model("simulated_trading", "SimulatedTradeModel"),
    )
    position_model._base_manager.using(alias).filter(pk=rows.position_id).update(
        cost_basis_known=True
    )
    trade_model._base_manager.using(alias).filter(pk=rows.trade_id).update(
        cost_basis_known=True,
        fee_amounts_known=True,
    )
    target_model = position_model if target_table == "position" else trade_model
    updated = (
        target_model._base_manager.using(alias)
        .filter(pk=rows.position_id if target_table == "position" else rows.trade_id)
        .update(**{target_field: unknown_value})
    )
    assert updated == 1

    with pytest.raises(
        IrreversibleError,
        match="Cannot remove explicit unknown or partial cost-basis knowledge",
    ):
        MigrationExecutor(connection).migrate([_BEFORE])

    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    position_columns, trade_columns = _cost_knowledge_columns(after_apps, alias)
    assert "cost_basis_known" in position_columns
    assert {"cost_basis_known", "fee_amounts_known"} <= trade_columns
    position_facts, trade_facts, position, trade = _read_legacy_rows(after_apps, rows, alias)
    assert position_facts == rows.position_facts
    assert trade_facts == rows.trade_facts
    if target_table == "position":
        assert position.cost_basis_known is unknown_value
        assert trade.cost_basis_known is True
        assert trade.fee_amounts_known is True
    elif target_field == "cost_basis_known":
        assert position.cost_basis_known is True
        assert trade.cost_basis_known is unknown_value
        assert trade.fee_amounts_known is True
    else:
        assert position.cost_basis_known is True
        assert trade.cost_basis_known is True
        assert trade.fee_amounts_known is unknown_value


@pytest.mark.parametrize("seed_complete_rows", (False, True), ids=("empty", "all-known"))
def test_0033_allows_reverse_and_reforward_for_all_known_or_empty_tables(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
    seed_complete_rows: bool,
) -> None:
    """Reversible states drop only the new flags and retain existing business facts."""

    _require_native_migration_database(django_db_use_migrations)
    state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    rows = _create_legacy_rows(before_apps, state) if seed_complete_rows else None
    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    if rows is not None:
        position_model = cast(
            type[Model],
            after_apps.get_model("simulated_trading", "PositionModel"),
        )
        trade_model = cast(
            type[Model],
            after_apps.get_model("simulated_trading", "SimulatedTradeModel"),
        )
        position_model._base_manager.using(alias).filter(pk=rows.position_id).update(
            cost_basis_known=True
        )
        trade_model._base_manager.using(alias).filter(pk=rows.trade_id).update(
            cost_basis_known=True,
            fee_amounts_known=True,
        )

    MigrationExecutor(connection).migrate([_BEFORE])
    reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    position_fields = {
        field.name
        for field in cast(
            type[Model],
            reversed_apps.get_model("simulated_trading", "PositionModel"),
        )._meta.get_fields()
    }
    trade_fields = {
        field.name
        for field in cast(
            type[Model],
            reversed_apps.get_model("simulated_trading", "SimulatedTradeModel"),
        )._meta.get_fields()
    }
    position_columns, trade_columns = _cost_knowledge_columns(reversed_apps, alias)
    assert "cost_basis_known" not in position_fields
    assert "cost_basis_known" not in trade_fields
    assert "fee_amounts_known" not in trade_fields
    assert "cost_basis_known" not in position_columns
    assert "cost_basis_known" not in trade_columns
    assert "fee_amounts_known" not in trade_columns
    assert _AFTER not in MigrationRecorder(connection).applied_migrations()
    if rows is not None:
        position_facts, trade_facts, _, _ = _read_legacy_rows(reversed_apps, rows, alias)
        assert position_facts == rows.position_facts
        assert trade_facts == rows.trade_facts

    MigrationExecutor(connection).migrate([_AFTER])
    round_trip_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    position_columns, trade_columns = _cost_knowledge_columns(round_trip_apps, alias)
    assert "cost_basis_known" in position_columns
    assert {"cost_basis_known", "fee_amounts_known"} <= trade_columns
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    if rows is not None:
        position_facts, trade_facts, position, trade = _read_legacy_rows(
            round_trip_apps,
            rows,
            alias,
        )
        assert position_facts == rows.position_facts
        assert trade_facts == rows.trade_facts
        assert position.cost_basis_known is None
        assert trade.cost_basis_known is None
        assert trade.fee_amounts_known is None
