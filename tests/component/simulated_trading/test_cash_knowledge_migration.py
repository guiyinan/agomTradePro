"""Native historical-row fidelity and reverse-safety tests for migration 0032."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
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
_BEFORE = ("simulated_trading", "0031_position_valuation_knowledge")
_AFTER = ("simulated_trading", "0032_cash_knowledge")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


@dataclass
class _MigrationCleanupState:
    """Remember the graph leaf and historical account rows created by each test."""

    leaf_nodes: list[tuple[str, str]]
    account_ids: list[int] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(transactional_db: None) -> Iterator[None]:
    """Expose migration dependencies while balancing pytest's partial app registry."""

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
    """Delete test rows and restore the migration graph even after a reverse refusal."""

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
            account_model = cast(
                type[Model],
                current_apps.get_model("simulated_trading", "SimulatedAccountModel"),
            )
            account_model._base_manager.using(connection.alias).filter(
                pk__in=state.account_ids
            ).delete()
        MigrationExecutor(connection).migrate(state.leaf_nodes)


def _require_native_migration_database(django_db_use_migrations: bool) -> None:
    """Limit migration reversal evidence to a migrations-enabled native PostgreSQL DB."""

    if not django_db_use_migrations:
        pytest.skip("Cash knowledge migration proof requires migrations-enabled database")
    if connection.vendor != "postgresql":
        pytest.skip("Cash knowledge reverse guard requires native PostgreSQL")
    assert settings.AUTH_USER_MODEL == "auth.User"


def _create_account_at_0031(
    apps: StateApps,
    cleanup_state: _MigrationCleanupState,
    *,
    account_type: str,
) -> tuple[int, Decimal, Decimal, object, object]:
    """Seed one 0031 account with economic values and both persisted clocks."""

    account_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "SimulatedAccountModel"),
    )
    suffix = uuid4().hex[:12]
    account = cast(
        Model,
        account_model._default_manager.using(connection.alias).create(
            user=None,
            account_name=f"cash-knowledge-{suffix}",
            account_type=account_type,
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("12345.67"),
            current_market_value=Decimal("67890.12"),
            total_value=Decimal("80235.79"),
        ),
    )
    account_id = cast(int, account.pk)
    cleanup_state.account_ids.append(account_id)
    return (
        account_id,
        cast(Decimal, account.current_cash),
        cast(Decimal, account.total_value),
        account.created_at,
        account.updated_at,
    )


def _account_columns(apps: StateApps, alias: str) -> set[str]:
    """Read account table columns from the migration state's model."""

    account_model = cast(
        type[Model],
        apps.get_model("simulated_trading", "SimulatedAccountModel"),
    )
    database_connection = connections[alias]
    with database_connection.cursor() as cursor:
        description = database_connection.introspection.get_table_description(
            cursor,
            account_model._meta.db_table,
        )
    return {cast(str, column.name) for column in description}


def test_0032_classifies_real_rows_without_rewriting_economics_or_clocks(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Preserve stored amounts and timestamps while marking old real cash unverified."""

    _require_native_migration_database(django_db_use_migrations)
    cleanup_state = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    real_facts = _create_account_at_0031(
        before_apps,
        cleanup_state,
        account_type="real",
    )
    simulated_facts = _create_account_at_0031(
        before_apps,
        cleanup_state,
        account_type="simulated",
    )
    before_columns = _account_columns(before_apps, alias)
    assert "cash_known" not in before_columns
    assert "cash_reconciliation_status" not in before_columns

    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    account_model = cast(
        type[Model],
        after_apps.get_model("simulated_trading", "SimulatedAccountModel"),
    )
    real = account_model._base_manager.using(alias).get(pk=real_facts[0])
    simulated = account_model._base_manager.using(alias).get(pk=simulated_facts[0])

    assert (real.current_cash, real.total_value, real.created_at, real.updated_at) == real_facts[1:]
    assert real.cash_known is False
    assert real.cash_reconciliation_status == "unverified"
    assert (
        simulated.current_cash,
        simulated.total_value,
        simulated.created_at,
        simulated.updated_at,
    ) == simulated_facts[1:]
    assert simulated.cash_known is True
    assert simulated.cash_reconciliation_status == "simulated_ledger"
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert {"cash_known", "cash_reconciliation_status"} <= _account_columns(after_apps, alias)


def test_0032_refuses_reverse_when_real_cash_knowledge_would_be_lost(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Retain the new state, schema, and recorder entry when unknown real rows exist."""

    _require_native_migration_database(django_db_use_migrations)
    cleanup_state = _restore_migration_graph
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    account_facts = _create_account_at_0031(
        before_apps,
        cleanup_state,
        account_type="real",
    )
    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps

    with pytest.raises(
        IrreversibleError,
        match="Cannot remove cash knowledge while real or unknown cash rows remain",
    ):
        MigrationExecutor(connection).migrate([_BEFORE])

    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert {"cash_known", "cash_reconciliation_status"} <= _account_columns(
        after_apps,
        connection.alias,
    )
    account_model = cast(
        type[Model],
        after_apps.get_model("simulated_trading", "SimulatedAccountModel"),
    )
    preserved = account_model._base_manager.using(connection.alias).get(pk=account_facts[0])
    assert preserved.cash_known is False
    assert preserved.cash_reconciliation_status == "unverified"
    assert (preserved.current_cash, preserved.total_value) == account_facts[1:3]


def test_0032_allows_reverse_when_only_simulated_ledger_rows_remain(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Allow a reversible schema round-trip when no unknown cash state is discarded."""

    _require_native_migration_database(django_db_use_migrations)
    cleanup_state = _restore_migration_graph
    MigrationExecutor(connection).migrate([_BEFORE])
    before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    account_facts = _create_account_at_0031(
        before_apps,
        cleanup_state,
        account_type="simulated",
    )
    MigrationExecutor(connection).migrate([_AFTER])

    MigrationExecutor(connection).migrate([_BEFORE])
    reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
    account_model = cast(
        type[Model],
        reversed_apps.get_model("simulated_trading", "SimulatedAccountModel"),
    )
    reversed = account_model._base_manager.using(connection.alias).get(pk=account_facts[0])
    assert (reversed.current_cash, reversed.total_value) == account_facts[1:3]
    assert "cash_known" not in _account_columns(reversed_apps, connection.alias)
    assert _AFTER not in MigrationRecorder(connection).applied_migrations()
