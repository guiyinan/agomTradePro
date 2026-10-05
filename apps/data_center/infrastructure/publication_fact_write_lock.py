"""Coordinate publication-safe fact writers with atomic activation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Final

from django.db import connections, models
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.utils import CursorWrapper
from django.db.transaction import TransactionManagementError

from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    canonicalize_scoped_advisory_lock_keys,
    derive_scoped_advisory_lock_id,
)

_DEFAULT_ALIAS: Final[str] = "default"
_LOCK_TIMEOUT_MILLISECONDS: Final[int] = 5_000
_TABLE_LOCK_DOMAIN: Final[str] = "data-center.publication-fact-table"
_NATURAL_KEY_LOCK_DOMAIN: Final[str] = "data-center.publication-fact-natural-key"


@contextmanager
def publication_fact_write_lock(
    model: type[models.Model],
    *,
    natural_key_tokens: Iterable[str],
    using: str = _DEFAULT_ALIAS,
) -> Iterator[None]:
    """Share the table fence and serialize only matching natural-key writers.

    The transaction-scoped shared table fence lets disjoint ingestion batches
    proceed concurrently. Per-key exclusive locks retain absent-key insert
    serialization. Atomic activation takes the matching exclusive table fence
    before it locks pointers or fact rows.
    """

    connection = connections[using]
    _require_atomic(connection, using=using)
    previous_timeout: int | None = None
    if connection.vendor == "postgresql":
        table_key = _table_lock_key(model)
        natural_key_plan = canonicalize_scoped_advisory_lock_keys(
            _natural_key_lock_key(model, token) for token in natural_key_tokens
        )
        previous_timeout = _bounded_lock_timeout(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock_shared(%s)",
                [derive_scoped_advisory_lock_id(table_key)],
            )
            _acquire_exclusive_plan(cursor, natural_key_plan)
    completed = False
    try:
        yield
        completed = True
    finally:
        if completed:
            _restore_lock_timeout(connection, previous_timeout)


def acquire_publication_fact_activation_locks(
    fact_models: Iterable[type[models.Model]],
    *,
    using: str = _DEFAULT_ALIAS,
) -> tuple[str, ...]:
    """Fence all governed writers before activation locks publication state."""

    connection = connections[using]
    _require_atomic(connection, using=using)
    model_by_table = {model._meta.db_table: model for model in fact_models}
    if not model_by_table:
        raise ValueError("Publication activation requires at least one fact model")
    table_names = tuple(sorted(model_by_table))
    if connection.vendor != "postgresql":
        return table_names
    plan = canonicalize_scoped_advisory_lock_keys(
        _table_lock_key(model_by_table[table_name]) for table_name in table_names
    )
    previous_timeout = _bounded_lock_timeout(connection)
    with connection.cursor() as cursor:
        _acquire_exclusive_plan(cursor, plan)
    _restore_lock_timeout(connection, previous_timeout)
    return table_names


def _require_atomic(connection: BaseDatabaseWrapper, *, using: str) -> None:
    """Reject lock acquisition outside the exact transaction boundary."""

    if connection.alias != using or not connection.in_atomic_block or connection.get_autocommit():
        raise TransactionManagementError(
            "Publication fact locking requires an active matching transaction"
        )


def _bounded_lock_timeout(connection: BaseDatabaseWrapper) -> int | None:
    """Apply the existing five-second ceiling and return the prior value."""

    if connection.vendor != "postgresql":
        return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT setting::bigint FROM pg_settings WHERE name = 'lock_timeout'")
        row = cursor.fetchone()
        if row is None or len(row) != 1:
            raise TransactionManagementError("PostgreSQL lock_timeout is unavailable")
        previous_timeout = int(row[0])
        timeout = (
            min(previous_timeout, _LOCK_TIMEOUT_MILLISECONDS)
            if previous_timeout > 0
            else _LOCK_TIMEOUT_MILLISECONDS
        )
        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [str(timeout)])
    return previous_timeout


def _restore_lock_timeout(connection: BaseDatabaseWrapper, previous_timeout: int | None) -> None:
    """Restore the transaction-local timeout after the bounded lock section."""

    if previous_timeout is None:
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [str(previous_timeout)])


def _table_lock_key(model: type[models.Model]) -> ScopedAdvisoryLockKey:
    """Return the stable table-level publication fence key."""

    return ScopedAdvisoryLockKey(
        domain=_TABLE_LOCK_DOMAIN,
        components=(model._meta.db_table,),
    )


def _natural_key_lock_key(
    model: type[models.Model], natural_key_token: str
) -> ScopedAdvisoryLockKey:
    """Return a bounded stable key for one source natural-key identity."""

    if (
        type(natural_key_token) is not str
        or not natural_key_token
        or natural_key_token.strip() != natural_key_token
    ):
        raise ValueError("Publication fact natural-key lock token is invalid")
    digest = hashlib.sha256(natural_key_token.encode("utf-8")).hexdigest()
    return ScopedAdvisoryLockKey(
        domain=_NATURAL_KEY_LOCK_DOMAIN,
        components=(model._meta.db_table, digest),
    )


def _acquire_exclusive_plan(cursor: CursorWrapper, plan: Iterable[ScopedAdvisoryLockKey]) -> None:
    """Acquire one deterministic advisory plan in a single database round trip."""

    lock_ids = [derive_scoped_advisory_lock_id(key) for key in plan]
    if not lock_ids:
        return
    cursor.execute(
        """
        WITH lock_plan AS MATERIALIZED (
            SELECT unnest(%s::bigint[]) AS lock_id
            ORDER BY lock_id
        )
        SELECT pg_advisory_xact_lock(lock_id)
        FROM lock_plan
        """,
        [lock_ids],
    )


__all__ = [
    "acquire_publication_fact_activation_locks",
    "publication_fact_write_lock",
]
