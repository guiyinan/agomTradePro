"""Native checks for the position knowledge flags migration."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast

import pytest
from django.apps import apps as django_apps
from django.db import connection
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
_BEFORE = ("simulated_trading", "0029_current_reference_plan_binding")
_AFTER = ("simulated_trading", "0030_position_knowledge_flags")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


@dataclass(frozen=True)
class _PositionBusinessFacts:
    """Typed snapshot of every persisted PositionModel field before the flags."""

    position_id: int
    account_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    quantity: Decimal
    available_quantity: Decimal
    avg_cost: Decimal
    total_cost: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float
    first_buy_date: date
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
    """Remember fixture rows and the graph leaf for local teardown only."""

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
    """Reset fixture data safely, then return the database to its original leaf."""

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
                    # Restore a safe local state only after the rejection assertions have run.
                    positions.update(
                        available_quantity_known=True,
                        first_buy_date_known=True,
                    )
                positions.delete()
            if state.account_id is not None:
                account_model._base_manager.using(connection.alias).filter(
                    pk=state.account_id
                ).delete()
        MigrationExecutor(connection).migrate(state.leaf_nodes)


def _create_legacy_position(
    apps: StateApps,
    cleanup_state: _MigrationCleanupState,
) -> tuple[int, _PositionBusinessFacts]:
    """Create and snapshot one row using the real historical 0029 model state."""

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
            account_name="position-knowledge-migration-fixture",
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
            asset_code="600000.SH",
            asset_name="Position migration fixture",
            asset_type="equity",
            quantity=Decimal("100.000000"),
            available_quantity=Decimal("40.000000"),
            avg_cost=Decimal("10.0000"),
            total_cost=Decimal("1000.00"),
            current_price=Decimal("10.5000"),
            market_value=Decimal("1050.00"),
            unrealized_pnl=Decimal("50.00"),
            unrealized_pnl_pct=5.0,
            first_buy_date=date(2026, 10, 16),
            signal_id=314,
            entry_reason="position knowledge migration fixture",
            invalidation_rule_json={"schema": "position-knowledge-migration-fixture"},
            invalidation_description="Retain historical evidence across migration steps.",
            is_invalidated=False,
            invalidation_reason="not invalidated",
            invalidation_checked_at=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
        ),
    )
    position_id = cast(int, position.pk)
    cleanup_state.position_id = position_id
    return position_id, _position_business_facts(position)


def _position_business_facts(position: Model) -> _PositionBusinessFacts:
    """Read complete persisted business facts with date and datetime types distinct."""

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
        avg_cost=cast(Decimal, position.avg_cost),
        total_cost=cast(Decimal, position.total_cost),
        current_price=cast(Decimal, position.current_price),
        market_value=cast(Decimal, position.market_value),
        unrealized_pnl=cast(Decimal, position.unrealized_pnl),
        unrealized_pnl_pct=cast(float, position.unrealized_pnl_pct),
        first_buy_date=first_buy_date,
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
    """Fetch one historical PositionModel row and return its full facts and state model."""

    position_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "PositionModel"),
    )
    position = cast(
        Model,
        position_model._default_manager.using(alias).get(pk=position_id),
    )
    return _position_business_facts(position), position


@pytest.mark.parametrize(
    ("unknown_field", "expected_flags"),
    (
        ("available_quantity_known", (False, True)),
        ("first_buy_date_known", (True, False)),
    ),
)
def test_0030_preserves_legacy_position_facts_and_guards_unknown_rows(
    _restore_migration_graph: _MigrationCleanupState,
    unknown_field: Literal["available_quantity_known", "first_buy_date_known"],
    expected_flags: tuple[bool, bool],
) -> None:
    """Round-trip real migration nodes and reject dropping either unknown flag."""

    cleanup_state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    position_id, original_facts = _create_legacy_position(before_apps, cleanup_state)

    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    after_facts, migrated_position = _read_position_facts(after_apps, position_id, alias)
    assert after_facts == original_facts
    assert migrated_position.available_quantity_known is True
    assert migrated_position.first_buy_date_known is True

    MigrationExecutor(connection).migrate([_BEFORE])
    reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    reversed_facts, reversed_position = _read_position_facts(reversed_apps, position_id, alias)
    assert reversed_facts == original_facts
    reversed_field_names = {field.name for field in reversed_position._meta.get_fields()}
    assert "available_quantity_known" not in reversed_field_names
    assert "first_buy_date_known" not in reversed_field_names

    MigrationExecutor(connection).migrate([_AFTER])
    current_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    current_facts, current_position = _read_position_facts(current_apps, position_id, alias)
    assert current_facts == original_facts
    assert current_position.available_quantity_known is True
    assert current_position.first_buy_date_known is True

    position_model = cast(
        type[Model],
        current_apps.get_model("simulated_trading", "PositionModel"),
    )
    updated_rows = (
        position_model._base_manager.using(alias)
        .filter(pk=position_id)
        .update(**{unknown_field: False})
    )
    assert updated_rows == 1
    with pytest.raises(IrreversibleError, match="unknown rows remain"):
        MigrationExecutor(connection).migrate([_BEFORE])

    preserved_facts, preserved_position = _read_position_facts(current_apps, position_id, alias)
    assert preserved_facts == original_facts
    assert (
        preserved_position.available_quantity_known,
        preserved_position.first_buy_date_known,
    ) == expected_flags
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
