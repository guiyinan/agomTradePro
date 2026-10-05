"""Real PostgreSQL concurrency contracts for publication fact fences."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from time import monotonic
from urllib.parse import unquote, urlsplit

import pytest
from django.db import DatabaseError, close_old_connections, connections, transaction

from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.publication_fact_write_lock import (
    acquire_publication_fact_activation_locks,
    publication_fact_write_lock,
)

_POSTGRES_FLAG = "AGOM_EVID06_POSTGRES_TEST"
_POSTGRES_URL = "AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"
_DATABASE_NAME = "agom_release_rehearsal_ci"
_ALIASES = ("publication_fact_lock_a", "publication_fact_lock_b")
_CONTENDED_LOCK_TIMEOUT = "250ms"
_FAST_PATH_SECONDS = 1.0
_FAIL_CLOSED_SECONDS = 2.0


def _database_settings() -> dict[str, object]:
    """Build a loopback-only connection from the explicit CI fixture URL."""

    if os.environ.get(_POSTGRES_FLAG, "").strip() != "1":
        pytest.skip(f"{_POSTGRES_FLAG}=1 is required for the PostgreSQL lock proof")
    raw_url = os.environ.get(_POSTGRES_URL, "").strip()
    if not raw_url:
        pytest.fail(f"{_POSTGRES_URL} is required")
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail("publication fact lock URL must use PostgreSQL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("publication fact lock proof requires a loopback host")
    if unquote(parsed.path.removeprefix("/")) != _DATABASE_NAME:
        pytest.fail("publication fact lock database identity mismatch")
    if not parsed.username or parsed.query or parsed.fragment:
        pytest.fail("publication fact lock URL has unsupported credentials or query data")
    settings = deepcopy(connections["default"].settings_dict)
    settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=_DATABASE_NAME,
        USER=unquote(parsed.username),
        PASSWORD=unquote(parsed.password or ""),
        HOST=parsed.hostname,
        PORT=str(parsed.port or 5432),
        CONN_MAX_AGE=0,
        OPTIONS={
            "connect_timeout": 10,
            "sslmode": "disable",
            "gssencmode": "disable",
        },
    )
    return settings


@pytest.fixture()
def publication_fact_lock_aliases(django_db_blocker) -> Iterator[tuple[str, str]]:
    """Register two connections to the dedicated disposable PostgreSQL DB."""

    settings = _database_settings()
    registered: list[str] = []
    with django_db_blocker.unblock():
        try:
            for alias in _ALIASES:
                if alias in connections.databases:
                    raise RuntimeError(f"database alias is already registered: {alias}")
                connections.databases[alias] = deepcopy(settings)
                registered.append(alias)
            for alias in _ALIASES:
                with connections[alias].cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    row = cursor.fetchone()
                assert row == (_DATABASE_NAME,)
            yield _ALIASES
        finally:
            for alias in reversed(registered):
                connections[alias].close()
                connections.databases.pop(alias, None)


def _hold_writer(*, alias: str, token: str, acquired: Event, release: Event) -> None:
    """Hold one writer fence until the coordinating test releases it."""

    close_old_connections()
    try:
        with transaction.atomic(using=alias):
            with publication_fact_write_lock(
                QuoteSnapshotModel,
                natural_key_tokens=(token,),
                using=alias,
            ):
                acquired.set()
                if not release.wait(timeout=10):
                    raise AssertionError("publication fact writer release timed out")
    finally:
        connections[alias].close()


def _start_held_writer(
    executor: ThreadPoolExecutor, *, alias: str, token: str
) -> tuple[Future[None], Event]:
    """Start one writer and return its bounded release handle."""

    acquired = Event()
    release = Event()
    future = executor.submit(
        _hold_writer,
        alias=alias,
        token=token,
        acquired=acquired,
        release=release,
    )
    if not acquired.wait(timeout=10):
        release.set()
        future.result(timeout=10)
        raise AssertionError("publication fact writer did not acquire its fence")
    return future, release


def test_disjoint_fact_writers_share_table_fence_with_bounded_query_count(
    publication_fact_lock_aliases: tuple[str, str],
) -> None:
    """A routine decision write cannot block a disjoint full-market batch."""

    first_alias, second_alias = publication_fact_lock_aliases
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="publication-fact") as executor:
        future, release = _start_held_writer(executor, alias=first_alias, token="decision:000300")
        statements: list[str] = []

        def capture(execute, sql, params, many, context):
            statements.append(str(sql))
            return execute(sql, params, many, context)

        started = monotonic()
        try:
            with connections[second_alias].execute_wrapper(capture):
                with transaction.atomic(using=second_alias):
                    with publication_fact_write_lock(
                        QuoteSnapshotModel,
                        natural_key_tokens=("full-market:600000",),
                        using=second_alias,
                    ):
                        pass
        finally:
            release.set()
        assert monotonic() - started < _FAST_PATH_SECONDS
        future.result(timeout=10)

    assert len(statements) == 5
    assert any("pg_advisory_xact_lock_shared" in statement for statement in statements)
    assert all("LOCK TABLE" not in statement.upper() for statement in statements)


def test_activation_excludes_writer_and_then_recovers_after_release(
    publication_fact_lock_aliases: tuple[str, str],
) -> None:
    """Activation fails closed while a writer runs and succeeds after commit."""

    first_alias, second_alias = publication_fact_lock_aliases
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="publication-fact") as executor:
        future, release = _start_held_writer(executor, alias=first_alias, token="decision:510300")
        started = monotonic()
        try:
            with pytest.raises(DatabaseError), transaction.atomic(using=second_alias):
                with connections[second_alias].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = %s", [_CONTENDED_LOCK_TIMEOUT])
                acquire_publication_fact_activation_locks(
                    (QuoteSnapshotModel,),
                    using=second_alias,
                )
        finally:
            release.set()
        assert monotonic() - started < _FAIL_CLOSED_SECONDS
        future.result(timeout=10)

    with transaction.atomic(using=second_alias):
        assert acquire_publication_fact_activation_locks(
            (QuoteSnapshotModel,),
            using=second_alias,
        ) == (QuoteSnapshotModel._meta.db_table,)


def test_matching_natural_key_writers_remain_serialized(
    publication_fact_lock_aliases: tuple[str, str],
) -> None:
    """Shared table fences do not permit an absent-key insert race."""

    first_alias, second_alias = publication_fact_lock_aliases
    token = "same-source-natural-key"
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="publication-fact") as executor:
        future, release = _start_held_writer(executor, alias=first_alias, token=token)
        started = monotonic()
        try:
            with pytest.raises(DatabaseError), transaction.atomic(using=second_alias):
                with connections[second_alias].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = %s", [_CONTENDED_LOCK_TIMEOUT])
                with publication_fact_write_lock(
                    QuoteSnapshotModel,
                    natural_key_tokens=(token,),
                    using=second_alias,
                ):
                    raise AssertionError("matching natural-key lock unexpectedly acquired")
        finally:
            release.set()
        assert monotonic() - started < _FAIL_CLOSED_SECONDS
        future.result(timeout=10)

    with transaction.atomic(using=second_alias):
        with publication_fact_write_lock(
            QuoteSnapshotModel,
            natural_key_tokens=(token,),
            using=second_alias,
        ):
            pass
