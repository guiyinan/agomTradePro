"""Native migration fidelity and reverse protection for automatic run records."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, connections
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import StateApps
from django.db.models import Model

from tests.support.native_postgres_database import assert_native_postgres_test_database

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)
_BEFORE = ("simulated_trading", "0033_cost_basis_knowledge")
_AFTER = ("simulated_trading", "0034_automatic_trading_invocation")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


class _InvocationRecord(Protocol):
    """Read-only fields needed to assert a historical ORM row without dynamic Any."""

    namespace: str
    invocation_key: str
    request_hash: str
    request_payload: object
    trade_date: date
    account_ids: object
    state: str
    started_at: datetime | None


@dataclass
class _MigrationCleanupState:
    """Remember the original graph leaf and any business run created by a test."""

    leaf_nodes: list[tuple[str, str]]
    invocation_ids: list[UUID] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _full_registry_for_migration_loader(transactional_db: None) -> Iterator[None]:
    """Balance the partial test app scope while migration dependencies are loaded."""

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
    _full_registry_for_migration_loader: None,
) -> Iterator[_MigrationCleanupState]:
    """Remove test run rows before restoring every app's original migration leaf."""

    del _full_registry_for_migration_loader
    state = _MigrationCleanupState(
        leaf_nodes=list(MigrationExecutor(connection).loader.graph.leaf_nodes())
    )
    try:
        yield state
    finally:
        applied = MigrationRecorder(connection).applied_migrations()
        if state.invocation_ids and _AFTER in applied:
            current_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
            invocation_model = cast(
                type[Model],
                current_apps.get_model("simulated_trading", "AutomaticTradingInvocationModel"),
            )
            invocation_model._base_manager.using(connection.alias).filter(
                invocation_id__in=state.invocation_ids
            ).delete()
        MigrationExecutor(connection).migrate(state.leaf_nodes)


def _require_native_migration_database(django_db_use_migrations: bool) -> None:
    """Require an explicit migrations-enabled native PostgreSQL test database."""

    if not django_db_use_migrations:
        pytest.skip("automatic invocation migration proof requires migrations-enabled database")
    if connection.vendor != "postgresql":
        pytest.skip("automatic invocation reverse guard requires native PostgreSQL")
    assert settings.AUTH_USER_MODEL == "auth.User"
    assert_native_postgres_test_database()


def _columns(apps: StateApps, alias: str) -> set[str]:
    """Read the actual invocation-table schema for one historical migration state."""

    model = cast(
        type[Model],
        apps.get_model("simulated_trading", "AutomaticTradingInvocationModel"),
    )
    database = connections[alias]
    with database.cursor() as cursor:
        description = database.introspection.get_table_description(cursor, model._meta.db_table)
    return {cast(str, column.name) for column in description}


def _create_started_run(apps: StateApps, cleanup: _MigrationCleanupState) -> tuple[UUID, str]:
    """Create a complete in-flight run row whose retry identity must survive reversal."""

    model = cast(
        type[Model],
        apps.get_model("simulated_trading", "AutomaticTradingInvocationModel"),
    )
    invocation_id = uuid4()
    claim_token = uuid4()
    request_payload = {
        "schema": "simulated_auto_invocation_request.v1",
        "trade_date": None,
        "account_ids": None,
    }
    model._default_manager.using(connection.alias).create(
        invocation_id=invocation_id,
        namespace="migration-owner:73",
        invocation_key="migration-run-20261019",
        request_hash="a" * 64,
        request_payload=request_payload,
        trade_date=datetime(2026, 10, 19, tzinfo=UTC).date(),
        account_ids=[73, 41],
        state="started",
        claim_token=claim_token,
        started_at=datetime(2026, 10, 19, 2, 0, tzinfo=UTC),
    )
    cleanup.invocation_ids.append(invocation_id)
    return invocation_id, "a" * 64


def test_0034_refuses_reverse_and_preserves_started_run_identity(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Do not remove retry identity, frozen scope, or run state while a row exists."""

    _require_native_migration_database(django_db_use_migrations)
    cleanup = _restore_migration_graph
    alias = connection.alias
    MigrationExecutor(connection).migrate([_BEFORE])
    assert "simulated_auto_trading_invocation" not in connection.introspection.table_names()

    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    invocation_id, request_hash = _create_started_run(after_apps, cleanup)
    columns = _columns(after_apps, alias)
    assert {
        "invocation_id",
        "namespace",
        "invocation_key",
        "request_hash",
        "request_payload",
        "trade_date",
        "account_ids",
        "state",
        "claim_token",
        "started_at",
    } <= columns

    with pytest.raises(
        IrreversibleError,
        match="Cannot drop automatic invocation records",
    ):
        MigrationExecutor(connection).migrate([_BEFORE])

    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert columns <= _columns(after_apps, alias)
    stored = cast(
        _InvocationRecord,
        after_apps.get_model("simulated_trading", "AutomaticTradingInvocationModel")
        ._base_manager.using(alias)
        .get(invocation_id=invocation_id),
    )
    assert stored.request_hash == request_hash
    assert stored.namespace == "migration-owner:73"
    assert stored.invocation_key == "migration-run-20261019"
    assert stored.request_payload == {
        "schema": "simulated_auto_invocation_request.v1",
        "trade_date": None,
        "account_ids": None,
    }
    assert stored.trade_date.isoformat() == "2026-10-19"
    assert stored.account_ids == [73, 41]
    assert stored.state == "started"
    assert stored.started_at == datetime(2026, 10, 19, 2, 0, tzinfo=UTC)


def test_0034_empty_table_allows_a_schema_round_trip(
    _restore_migration_graph: _MigrationCleanupState,
    django_db_use_migrations: bool,
) -> None:
    """Permit reversal only when no persisted idempotency record would be discarded."""

    _require_native_migration_database(django_db_use_migrations)
    MigrationExecutor(connection).migrate([_BEFORE])
    MigrationExecutor(connection).migrate([_AFTER])
    after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    invocation_model = cast(
        type[Model],
        after_apps.get_model("simulated_trading", "AutomaticTradingInvocationModel"),
    )
    assert invocation_model._default_manager.using(connection.alias).count() == 0

    MigrationExecutor(connection).migrate([_BEFORE])
    assert _AFTER not in MigrationRecorder(connection).applied_migrations()
    assert "simulated_auto_trading_invocation" not in connection.introspection.table_names()

    MigrationExecutor(connection).migrate([_AFTER])
    reforwarded_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    reforwarded_model = cast(
        type[Model],
        reforwarded_apps.get_model("simulated_trading", "AutomaticTradingInvocationModel"),
    )
    assert reforwarded_model._default_manager.using(connection.alias).count() == 0
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
