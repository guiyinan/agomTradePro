"""Exercise the actual migrations forwards and backwards on a private in-memory SQLite alias."""

from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import connections
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import ProjectState
from django.db.utils import ConnectionHandler

_NAMES = (
    "0029_policy_benchmark_daily_valuation",
    "0030_benchmark_execution_approval",
    "0031_benchmark_statement_revocation",
)


@pytest.fixture
def benchmark_migration_db(django_db_blocker):
    alias = f"portfolio_rollback_{uuid4().hex}"
    config = ConnectionHandler(
        {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
    ).databases["default"]
    db = DatabaseWrapper(config, alias=alias)
    connections[alias] = db
    try:
        with django_db_blocker.unblock():
            yield db
    finally:
        if db.connection is not None:
            db.connection.close()
        del connections[alias]


def _apply(db, versions):
    state = ProjectState()
    transitions = []
    for name in _NAMES[:versions]:
        migration = import_module(f"apps.portfolio.migrations.{name}").Migration(name, "portfolio")
        before = state.clone()
        with db.schema_editor() as editor:
            state = migration.apply(state, editor)
        transitions.append((migration, before))
    return state.apps, transitions


def test_empty_benchmark_migrations_can_reverse(benchmark_migration_db):
    db = benchmark_migration_db
    _, transitions = _apply(db, versions=3)
    assert len(db.introspection.table_names()) == 4
    for migration, before in reversed(transitions):
        with db.schema_editor() as editor:
            migration.unapply(before, editor)
    assert db.introspection.table_names() == []


@pytest.mark.parametrize(
    ("version", "ledger"), ((1, "epoch"), (1, "day"), (2, "approval"), (3, "revocation"))
)
def test_nonempty_benchmark_migration_refuses_before_ddl(benchmark_migration_db, version, ledger):
    db = benchmark_migration_db
    apps, transitions = _apply(db, versions=version)
    now = datetime.now(UTC)
    epoch = (
        apps.get_model("portfolio", "PortfolioBenchmarkValuationEpochModel")
        .objects.using(db.alias)
        .create(owner_user_id=1, sequence=1, started_at=now)
    )
    if ledger == "epoch":
        model = type(epoch)
    elif ledger == "approval":
        model = apps.get_model("portfolio", "BenchmarkApprovalEventModel")
        model.objects.using(db.alias).create(
            action="submitted",
            sequence=1,
            request_id=uuid4(),
            owner_user_id=1,
            valuation_id=epoch.pk,
            valuation_version=1,
            actor_user_id=1,
            recorded_at=now,
            valid_until=now,
        )
    else:
        day = (
            apps.get_model("portfolio", "PortfolioBenchmarkDailyValuationModel")
            .objects.using(db.alias)
            .create(
                epoch_id=epoch.pk,
                version=1,
                observation_date=now.date(),
                observed_at=now,
                recorded_at=now,
                valid_until=now,
                snapshot_id=1,
                original_statement=b"test",
                balance={},
            )
        )
        model = type(day)
        if ledger == "revocation":
            model = apps.get_model("portfolio", "BenchmarkStatementRevocationModel")
            model.objects.using(db.alias).create(day_id=day.pk, owner_user_id=1, recorded_at=now)
    tables = db.introspection.table_names()
    migration, before = transitions[-1]
    with pytest.raises(IrreversibleError, match=model._meta.db_table), db.schema_editor() as editor:
        migration.unapply(before, editor)
    assert db.introspection.table_names() == tables
    assert model.objects.using(db.alias).count() == 1
