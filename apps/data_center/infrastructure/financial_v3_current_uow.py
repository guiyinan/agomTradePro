"""Strict E1 v3 CURRENT transaction boundary for canonical fact operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction

from core.exceptions import DataValidationError


class FinancialV3CurrentUowBlocked(DataValidationError):
    """Raised when a current E1 v3 operation lacks its exact PostgreSQL UOW."""

    default_message = "Current financial E1 verification requires one PostgreSQL UOW."
    default_code = "FINANCIAL_V3_CURRENT_UOW_INVALID"


@contextmanager
def financial_v3_current_operation_uow(*, using: str = DEFAULT_DB_ALIAS) -> Iterator[None]:
    """Create one default-alias RC UOW or join an existing single outer UOW.

    E1 write/read callers may omit a transaction or already own exactly one
    transaction. In the first case this boundary opens the unique outer UOW;
    in the second it joins without adding a savepoint. Publication remains a
    caller-owned operation and must not use this helper.
    """

    if type(using) is not str or using != DEFAULT_DB_ALIAS:
        raise FinancialV3CurrentUowBlocked("Current E1 v3 requires the default database alias.")
    connection = connections[using]
    if connection.in_atomic_block:
        _require_one_default_read_committed_uow(using=using)
        yield
        return
    with transaction.atomic(using=using):
        _require_one_default_read_committed_uow(using=using)
        yield


def require_financial_v3_caller_owned_uow(*, using: str = DEFAULT_DB_ALIAS) -> None:
    """Require, but never create, one caller-owned default-alias RC UOW."""

    _require_one_default_read_committed_uow(using=using)


def _require_one_default_read_committed_uow(*, using: str) -> None:
    """Check the exact alias, transaction depth, backend and isolation level."""

    connection = connections[using]
    if (
        using != DEFAULT_DB_ALIAS
        or connection.alias != DEFAULT_DB_ALIAS
        or connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
        or len(connection.atomic_blocks) != 1
    ):
        raise FinancialV3CurrentUowBlocked(
            "Current E1 v3 requires exactly one default-alias PostgreSQL UOW."
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            row = cursor.fetchone()
    except DatabaseError as error:
        raise FinancialV3CurrentUowBlocked(
            "Current E1 v3 cannot verify PostgreSQL transaction isolation."
        ) from error
    if row is None or len(row) != 1 or row[0] != "read committed":
        raise FinancialV3CurrentUowBlocked("Current E1 v3 requires READ COMMITTED isolation.")


__all__ = [
    "FinancialV3CurrentUowBlocked",
    "financial_v3_current_operation_uow",
    "require_financial_v3_caller_owned_uow",
]
