"""Typed PostgreSQL transaction-scoped advisory lock primitives.

This module owns only the database mechanics.  Business modules provide their
own domain and selector values through :class:`ScopedAdvisoryLockKey`; no app
package is imported here.  PostgreSQL keeps transaction-scoped advisory locks
until the surrounding transaction commits or rolls back, so callers must use
the returned plan only inside that same transaction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from django.db import DatabaseError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from core.exceptions import AgomTradeProException

SCOPED_ADVISORY_LOCK_NAMESPACE: Final[str] = "agomtradepro.scoped-advisory-lock"
SCOPED_ADVISORY_LOCK_VERSION: Final[str] = "v1"
_MAX_TOKEN_LENGTH: Final[int] = 192


class ScopedAdvisoryLockError(AgomTradeProException):
    """Base class for typed scoped advisory lock failures."""

    default_message = "scoped advisory lock failed"
    default_code = "SCOPED_ADVISORY_LOCK_ERROR"
    default_status_code = 503


class ScopedAdvisoryLockConfigurationError(ScopedAdvisoryLockError):
    """Raised when a lock key or namespace input is invalid."""

    default_message = "scoped advisory lock configuration is invalid"
    default_code = "SCOPED_ADVISORY_LOCK_CONFIGURATION_ERROR"
    default_status_code = 500


class ScopedAdvisoryLockTransactionError(ScopedAdvisoryLockError):
    """Raised when a lock is attempted outside its required transaction."""

    default_message = "scoped advisory lock requires an active PostgreSQL transaction"
    default_code = "SCOPED_ADVISORY_LOCK_TRANSACTION_ERROR"


class ScopedAdvisoryLockUnavailableError(ScopedAdvisoryLockError):
    """Raised when a non-blocking advisory lock cannot be acquired."""

    default_message = "scoped advisory lock is unavailable"
    default_code = "SCOPED_ADVISORY_LOCK_UNAVAILABLE"

    def __init__(self, *, using: str, key: ScopedAdvisoryLockKey) -> None:
        """Record the database alias and canonical key that contended."""

        self.using = using
        self.key = key
        super().__init__()


class ScopedAdvisoryLockDatabaseError(ScopedAdvisoryLockError):
    """Raised when PostgreSQL cannot evaluate an advisory lock request."""

    default_message = "scoped advisory lock database operation failed"
    default_code = "SCOPED_ADVISORY_LOCK_DATABASE_ERROR"


@dataclass(frozen=True, slots=True, order=True)
class ScopedAdvisoryLockKey:
    """Describe one namespaced resource lock without embedding SQL semantics."""

    domain: str
    components: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous values before they can enter a lock namespace."""

        if type(self.components) is not tuple or not self.components:
            raise ScopedAdvisoryLockConfigurationError(
                "scoped advisory lock components must be a non-empty tuple"
            )
        _validate_token(self.domain, "domain")
        for index, component in enumerate(self.components):
            _validate_token(component, f"components[{index}]")


def derive_scoped_advisory_lock_id(key: ScopedAdvisoryLockKey) -> int:
    """Derive a deterministic signed PostgreSQL ``bigint`` lock identifier."""

    if not isinstance(key, ScopedAdvisoryLockKey):
        raise ScopedAdvisoryLockConfigurationError(
            "scoped advisory lock key must be a ScopedAdvisoryLockKey"
        )
    payload = json.dumps(
        {
            "components": key.components,
            "domain": key.domain,
            "namespace": SCOPED_ADVISORY_LOCK_NAMESPACE,
            "version": SCOPED_ADVISORY_LOCK_VERSION,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], byteorder="big", signed=True)


def canonicalize_scoped_advisory_lock_keys(
    keys: Iterable[ScopedAdvisoryLockKey],
) -> tuple[ScopedAdvisoryLockKey, ...]:
    """Return one deterministic, derived-id ordered and deduplicated plan."""

    try:
        materialized = tuple(keys)
    except TypeError as error:
        raise ScopedAdvisoryLockConfigurationError(
            "scoped advisory lock keys must be iterable"
        ) from error
    if not materialized:
        raise ScopedAdvisoryLockConfigurationError(
            "scoped advisory lock plan must contain at least one key"
        )
    if any(not isinstance(key, ScopedAdvisoryLockKey) for key in materialized):
        raise ScopedAdvisoryLockConfigurationError(
            "scoped advisory lock plan contains an invalid key"
        )
    return tuple(
        sorted(
            set(materialized),
            key=lambda key: (derive_scoped_advisory_lock_id(key), key),
        )
    )


def try_acquire_scoped_advisory_shared(
    *, using: str, keys: Iterable[ScopedAdvisoryLockKey]
) -> tuple[ScopedAdvisoryLockKey, ...]:
    """Try to acquire every key in shared mode without waiting."""

    return _try_acquire_scoped_advisory_locks(using=using, keys=keys, shared=True)


def try_acquire_scoped_advisory_exclusive(
    *, using: str, keys: Iterable[ScopedAdvisoryLockKey]
) -> tuple[ScopedAdvisoryLockKey, ...]:
    """Try to acquire every key in exclusive mode without waiting."""

    return _try_acquire_scoped_advisory_locks(using=using, keys=keys, shared=False)


def _try_acquire_scoped_advisory_locks(
    *, using: str, keys: Iterable[ScopedAdvisoryLockKey], shared: bool
) -> tuple[ScopedAdvisoryLockKey, ...]:
    """Run one non-blocking plan inside a savepoint-protected transaction scope.

    A false result or driver error rolls back the nested savepoint so partial
    acquisitions from this plan do not escape to the caller's outer
    transaction.  Successful transaction-level locks remain held by that outer
    transaction until it commits or rolls back.
    """

    plan = canonicalize_scoped_advisory_lock_keys(keys)
    connection = _validated_connection(using)
    function = "pg_try_advisory_xact_lock_shared" if shared else "pg_try_advisory_xact_lock"
    statement = f"SELECT {function}(%s)"
    try:
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                for key in plan:
                    cursor.execute(statement, [derive_scoped_advisory_lock_id(key)])
                    row = cursor.fetchone()
                    if row is None or len(row) != 1 or type(row[0]) is not bool:
                        raise ScopedAdvisoryLockDatabaseError(
                            "PostgreSQL returned an invalid advisory lock result"
                        )
                    if row[0] is not True:
                        raise ScopedAdvisoryLockUnavailableError(using=using, key=key)
    except ScopedAdvisoryLockError:
        raise
    except DatabaseError as error:
        raise ScopedAdvisoryLockDatabaseError(
            "PostgreSQL advisory lock operation is unavailable"
        ) from error
    return plan


def _validated_connection(using: str) -> BaseDatabaseWrapper:
    """Return the exact PostgreSQL connection bound to one active transaction."""

    if type(using) is not str or not using or using.strip() != using:
        raise ScopedAdvisoryLockConfigurationError("database alias is invalid")
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
        raise ScopedAdvisoryLockTransactionError("database alias is unavailable") from error
    try:
        connection_alias = getattr(connection, "alias", None)
        vendor = connection.vendor
        in_atomic_block = connection.in_atomic_block
        autocommit = connection.get_autocommit()
    except DatabaseError as error:
        raise ScopedAdvisoryLockTransactionError(
            "database transaction state is unavailable"
        ) from error
    if connection_alias != using:
        raise ScopedAdvisoryLockTransactionError("database alias does not match its connection")
    if vendor != "postgresql":
        raise ScopedAdvisoryLockTransactionError("scoped advisory locks require PostgreSQL")
    if not in_atomic_block or autocommit:
        raise ScopedAdvisoryLockTransactionError(
            "scoped advisory locks require an active non-autocommit transaction"
        )
    return connection


def _validate_token(value: object, name: str) -> None:
    """Validate one canonical namespace component."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        or len(value) > _MAX_TOKEN_LENGTH
    ):
        raise ScopedAdvisoryLockConfigurationError(f"scoped advisory lock {name} is invalid")


__all__ = [
    "SCOPED_ADVISORY_LOCK_NAMESPACE",
    "SCOPED_ADVISORY_LOCK_VERSION",
    "ScopedAdvisoryLockConfigurationError",
    "ScopedAdvisoryLockDatabaseError",
    "ScopedAdvisoryLockError",
    "ScopedAdvisoryLockKey",
    "ScopedAdvisoryLockTransactionError",
    "ScopedAdvisoryLockUnavailableError",
    "canonicalize_scoped_advisory_lock_keys",
    "derive_scoped_advisory_lock_id",
    "try_acquire_scoped_advisory_exclusive",
    "try_acquire_scoped_advisory_shared",
]
