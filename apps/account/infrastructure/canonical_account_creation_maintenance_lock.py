"""Database-scoped transaction locks for canonical account-creation maintenance."""

from __future__ import annotations

import hashlib

from django.db import connections


class CanonicalAccountCreationMaintenanceLockUnavailable(RuntimeError):
    """Raised when a required maintenance lock cannot be acquired safely."""


_LOCK_NAMESPACE = b"agomtradepro:account:canonical-creation-consumption:v1"
_LOCK_KEY = int.from_bytes(
    hashlib.sha256(_LOCK_NAMESPACE).digest()[:8], byteorder="big", signed=True
)


def acquire_canonical_account_creation_writer_lock(*, using: str) -> None:
    """Acquire the shared writer lock for the current database transaction.

    PostgreSQL holds this lock until the surrounding transaction ends. SQLite is
    deliberately a local/test degradation: its database write lock remains the
    only serialization mechanism and must not be treated as production evidence.
    """

    connection = connections[using]
    if connection.vendor == "sqlite":
        return
    if connection.vendor != "postgresql":
        raise CanonicalAccountCreationMaintenanceLockUnavailable(
            f"canonical account-creation writer lock is unsupported by {connection.vendor}"
        )
    _require_transaction(using=using, in_atomic_block=connection.in_atomic_block)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [_LOCK_KEY])


def acquire_canonical_account_creation_maintenance_lock(
    *, using: str, allow_sqlite_test_degradation: bool = False
) -> None:
    """Acquire the exclusive maintenance lock for the current transaction.

    Production maintenance writes are PostgreSQL-only. A caller may explicitly
    permit SQLite solely for isolated component tests; that degraded execution is
    not deployment or migration-readiness evidence.
    """

    connection = connections[using]
    if connection.vendor == "sqlite" and allow_sqlite_test_degradation is True:
        return
    if connection.vendor != "postgresql":
        raise CanonicalAccountCreationMaintenanceLockUnavailable(
            "canonical account-creation maintenance writes require PostgreSQL"
        )
    _require_transaction(using=using, in_atomic_block=connection.in_atomic_block)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])


def _require_transaction(*, using: str, in_atomic_block: bool) -> None:
    if in_atomic_block is not True:
        raise CanonicalAccountCreationMaintenanceLockUnavailable(
            f"canonical account-creation lock on {using!r} requires an active transaction"
        )


__all__ = [
    "CanonicalAccountCreationMaintenanceLockUnavailable",
    "acquire_canonical_account_creation_maintenance_lock",
    "acquire_canonical_account_creation_writer_lock",
]
