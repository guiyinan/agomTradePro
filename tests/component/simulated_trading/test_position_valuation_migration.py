"""Native historical-row fidelity and reverse-safety tests for migration 0031."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
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
_BEFORE = ("simulated_trading", "0030_position_knowledge_flags")
_AFTER = ("simulated_trading", "0031_position_valuation_knowledge")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


@dataclass(frozen=True, slots=True)
class _PositionBusinessFacts:
    """Typed snapshot of every persisted PositionModel field before 0031."""

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
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float
    first_buy_date: date
    first_buy_date_known: bool
    last_update_date: date
    signal_id: int | None
    entry_reason: str
    invalidation_rule_json: tuple[tuple[str, str], ...]
    invalidation_description: str
    is_invalidated: bool
    invalidation_reason: str
    invalidation_checked_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass
class _MigrationCleanupState:
    """Remember local fixtures and the original migration graph leaf."""

    leaf_nodes: list[tuple[str, str]]
    account_id: int | None = None
    position_id: int | None = None


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
    """Safely remove local fixture rows and restore the original graph leaf."""

    del _full_app_registry_for_migration_loader
    state = _MigrationCleanupState(
        leaf_nodes=list(MigrationExecutor(connection).loader.graph.leaf_nodes())
    )
    try:
        yield state
    finally:
        applied_migrations = MigrationRecorder(connection).applied_migrations()
        current_target = _AFTER if _AFTER in applied_migrations else _BEFORE
        if state.position_id is not None or state.account_id is not None:
            current_apps = MigrationExecutor(connection).loader.project_state([current_target]).apps
            position_model = cast(
                type[Model],
                current_apps.get_model("simulated_trading", "PositionModel"),
            )
            account_model = cast(
                type[Model],
                current_apps.get_model("simulated_trading", "SimulatedAccountModel"),
            )
            if state.position_id is not None:
                positions = position_model._base_manager.using(connection.alias).filter(
                    pk=state.position_id
                )
                if _AFTER in applied_migrations:
                    # Restore only this fixture after the rejection assertions complete.
                    positions.update(valuation_known=True)
                positions.delete()
            if state.account_id is not None:
                account_model._base_manager.using(connection.alias).filter(
                    pk=state.account_id
                ).delete()
        MigrationExecutor(connection).migrate(state.leaf_nodes)


def _require_native_migration_database(django_db_use_migrations: bool) -> None:
    """Limit this proof to a migrations-enabled native PostgreSQL database."""

    if not django_db_use_migrations:
        pytest.skip("Position valuation migration proof requires migrations-enabled database")
    if connection.vendor != "postgresql":
        pytest.skip("Position valuation reverse guard requires native PostgreSQL")
    assert settings.AUTH_USER_MODEL == "auth.User"


def _create_position_at_0030(
    apps: StateApps,
    cleanup_state: _MigrationCleanupState,
) -> tuple[int, _PositionBusinessFacts]:
    """Seed a 0030 historical row with economics, flags, and audit clocks."""

    suffix = uuid4().hex[:12]
    account_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "SimulatedAccountModel"),
    )
    position_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "PositionModel"),
    )
    account = cast(
        Model,
        account_model._default_manager.create(
            user=None,
            account_name=f"valuation-migration-{suffix}",
            account_type="simulated",
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("99000.00"),
            current_market_value=Decimal("1000.00"),
            total_value=Decimal("100000.00"),
        ),
    )
    account_id = cast(int, account.pk)
    cleanup_state.account_id = account_id
    position = cast(
        Model,
        position_model._default_manager.create(
            account_id=account_id,
            asset_code=f"PV{suffix}",
            asset_name="Position valuation migration fixture",
            asset_type="equity",
            quantity=Decimal("100.123456"),
            available_quantity=Decimal("40.654321"),
            available_quantity_known=False,
            avg_cost=Decimal("10.1234"),
            total_cost=Decimal("1013.58"),
            current_price=Decimal("10.5678"),
            market_value=Decimal("1058.47"),
            unrealized_pnl=Decimal("44.89"),
            unrealized_pnl_pct=4.43,
            first_buy_date=date(2026, 10, 16),
            first_buy_date_known=True,
            signal_id=314,
            entry_reason="position valuation migration fixture",
            invalidation_rule_json={"schema": "valuation-migration-fixture"},
            invalidation_description="Retain prior position evidence across migration steps.",
            is_invalidated=True,
            invalidation_reason="fixture invalidation evidence",
            invalidation_checked_at=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
        ),
    )
    position_id = cast(int, position.pk)
    cleanup_state.position_id = position_id
    return position_id, _position_business_facts(position)


def _position_business_facts(position: Model) -> _PositionBusinessFacts:
    """Read position facts with date fields distinct from aware clock fields."""

    first_buy_date = cast(date, position.first_buy_date)
    last_update_date = cast(date, position.last_update_date)
    invalidation_checked_at = cast(datetime, position.invalidation_checked_at)
    created_at = cast(datetime, position.created_at)
    updated_at = cast(datetime, position.updated_at)
    assert type(first_buy_date) is date
    assert type(last_update_date) is date
    for timestamp in (invalidation_checked_at, created_at, updated_at):
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() is not None

    raw_rule = cast(object, position.invalidation_rule_json)
    assert isinstance(raw_rule, dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in raw_rule.items())
    rule_facts = tuple(sorted(cast(dict[str, str], raw_rule).items()))

    return _PositionBusinessFacts(
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
        unrealized_pnl=cast(Decimal, position.unrealized_pnl),
        unrealized_pnl_pct=cast(float, position.unrealized_pnl_pct),
        first_buy_date=first_buy_date,
        first_buy_date_known=cast(bool, position.first_buy_date_known),
        last_update_date=last_update_date,
        signal_id=cast(int | None, position.signal_id),
        entry_reason=cast(str, position.entry_reason),
        invalidation_rule_json=rule_facts,
        invalidation_description=cast(str, position.invalidation_description),
        is_invalidated=cast(bool, position.is_invalidated),
        invalidation_reason=cast(str, position.invalidation_reason),
        invalidation_checked_at=invalidation_checked_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _read_position_facts(
    apps: StateApps,
    position_id: int,
    alias: str,
) -> tuple[_PositionBusinessFacts, Model]:
    """Read one row through the supplied historical migration state."""

    position_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "PositionModel"),
    )
    position = cast(
        Model,
        position_model._default_manager.using(alias).get(pk=position_id),
    )
    return _position_business_facts(position), position


def _position_column_names(apps: StateApps, alias: str) -> set[str]:
    """Return physical database columns for the historical position table."""

    position_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "PositionModel"),
    )
    database_connection = connections[alias]
    with database_connection.cursor() as cursor:
        description = database_connection.introspection.get_table_description(
            cursor,
            position_model._meta.db_table,
        )
    return {cast(str, column.name) for column in description}


def test_0031_defaults_valuation_known_and_round_trips_all_position_facts(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Round-trip the real 0030/0031 nodes without rewriting position facts."""

    _require_native_migration_database(django_db_use_migrations)
    cleanup_state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    position_id, original_facts = _create_position_at_0030(before_apps, cleanup_state)

    before_position_fields = {
        field.name
        for field in cast(
            type[Model],
            before_apps.get_model("simulated_trading", "PositionModel"),
        )._meta.get_fields()
    }
    assert "valuation_known" not in before_position_fields

    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    after_facts, migrated_position = _read_position_facts(after_apps, position_id, alias)
    assert after_facts == original_facts
    assert migrated_position.valuation_known is True
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert "valuation_known" in _position_column_names(after_apps, alias)

    MigrationExecutor(connection).migrate([_BEFORE])
    reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    reversed_facts, reversed_position = _read_position_facts(reversed_apps, position_id, alias)
    assert reversed_facts == original_facts
    reversed_field_names = {field.name for field in reversed_position._meta.get_fields()}
    assert "valuation_known" not in reversed_field_names
    assert "valuation_known" not in _position_column_names(reversed_apps, alias)
    assert _AFTER not in MigrationRecorder(connection).applied_migrations()

    MigrationExecutor(connection).migrate([_AFTER])
    round_trip_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    round_trip_facts, round_trip_position = _read_position_facts(
        round_trip_apps,
        position_id,
        alias,
    )
    assert round_trip_facts == original_facts
    assert round_trip_position.valuation_known is True
    assert _AFTER in MigrationRecorder(connection).applied_migrations()


def test_0031_refuses_reverse_when_valuation_is_unknown_and_retains_schema(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Preserve an unknown valuation flag, schema column, and recorder entry."""

    _require_native_migration_database(django_db_use_migrations)
    cleanup_state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    position_id, original_facts = _create_position_at_0030(before_apps, cleanup_state)

    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    position_model = cast(
        type[Model],
        after_apps.get_model("simulated_trading", "PositionModel"),
    )
    updated_rows = (
        position_model._base_manager.using(alias)
        .filter(pk=position_id)
        .update(valuation_known=False)
    )
    assert updated_rows == 1

    with pytest.raises(
        IrreversibleError,
        match="Cannot remove position valuation knowledge flag while unknown rows remain",
    ):
        MigrationExecutor(connection).migrate([_BEFORE])

    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert "valuation_known" in _position_column_names(after_apps, alias)
    preserved_facts, preserved_position = _read_position_facts(
        after_apps,
        position_id,
        alias,
    )
    assert preserved_facts == original_facts
    assert preserved_position.valuation_known is False
