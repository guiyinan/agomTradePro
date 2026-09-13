"""Consistent read boundaries for canonical publication and fact data."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Final

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connection, transaction
from django.db.backends.utils import CursorWrapper

from core.exceptions import DataFetchError


class PublicationReadSnapshotError(DataFetchError):
    """Raised when the requested database boundary cannot provide a stable read."""

    default_message = "publication read snapshot is unavailable"
    default_code = "PUBLICATION_READ_SNAPSHOT_UNAVAILABLE"


_DATASET_FACT_TABLES: Final[dict[str, str]] = {
    "macro.fact": "data_center_macro_fact",
    "fund.nav": "data_center_fund_nav_fact",
    "equity.price.bar": "data_center_price_bar",
    "equity.quote.snapshot": "data_center_quote_snapshot",
    "equity.financial.fact": "data_center_financial_fact",
    "equity.valuation.fact": "data_center_valuation_fact",
    "sector.membership": "data_center_sector_membership",
    "market.news": "data_center_news_fact",
    "market.capital_flow": "data_center_capital_flow_fact",
}
_DATASET_POLICY_TABLE: Final[str] = "data_center_dataset_publication_policy"
_CANONICAL_PUBLICATION_TABLE: Final[str] = "data_center_canonical_publication"
_PUBLICATION_MEMBER_TABLE: Final[str] = "data_center_publication_member"
_DATASET_CONTRACT_TABLE: Final[str] = "data_center_dataset_contract"
_ASSET_QUERY_DATASETS: Final[frozenset[str]] = frozenset(
    {
        "equity.price.bar",
        "equity.quote.snapshot",
        "equity.financial.fact",
        "equity.valuation.fact",
        "market.news",
        "market.capital_flow",
    }
)
_POSTGRES_VENDORS: Final[frozenset[str]] = frozenset({"postgresql"})
_SQLITE_VENDORS: Final[frozenset[str]] = frozenset({"sqlite"})
_STABLE_ISOLATIONS: Final[frozenset[str]] = frozenset({"repeatable read", "serializable"})
_LOCK_TIMEOUT: Final[str] = "5s"
_LOCK_TIMEOUT_SECONDS: Final[Decimal] = Decimal("5")
_LOCK_TIMEOUT_VALUE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<amount>(?:0|[0-9]+(?:\.[0-9]+)?))\s*" r"(?P<unit>min|ms|us|s|h|d)?"
)
_LOCK_TIMEOUT_UNIT_SECONDS: Final[dict[str, Decimal]] = {
    "us": Decimal("0.000001"),
    "ms": Decimal("0.001"),
    "s": Decimal("1"),
    "min": Decimal("60"),
    "h": Decimal("3600"),
    "d": Decimal("86400"),
}


@contextmanager
def consistent_publication_read(dataset_key: str) -> Iterator[None]:
    """Run publication header, policy, member and fact reads in one stable boundary.

    The helper always uses Django's ``default`` connection and atomic context.
    An outer PostgreSQL transaction is configured as repeatable-read/read-only
    before yielding.  A nested repeatable-read or serializable transaction
    reuses its existing snapshot; a nested writable read-committed transaction
    takes deterministic table locks before the caller performs its reads.
    SQLite keeps Django's atomic behavior without PostgreSQL statements.
    """

    fact_table = _fact_table(dataset_key)
    metadata_tables = _query_metadata_tables(dataset_key.strip())
    _require_default_connection()
    vendor = connection.vendor
    if vendor not in _POSTGRES_VENDORS and vendor not in _SQLITE_VENDORS:
        raise PublicationReadSnapshotError(
            f"unsupported publication read database vendor: {vendor}"
        )

    is_outer_transaction = not connection.in_atomic_block
    if vendor in _POSTGRES_VENDORS and is_outer_transaction and not connection.get_autocommit():
        raise PublicationReadSnapshotError(
            "publication read requires a Django-managed outer PostgreSQL transaction"
        )

    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        if vendor in _SQLITE_VENDORS:
            yield
            return
        try:
            if is_outer_transaction:
                _configure_outer_postgresql_snapshot()
            else:
                _stabilize_nested_postgresql_read(fact_table, metadata_tables)
        except PublicationReadSnapshotError:
            raise
        except DatabaseError as error:
            raise PublicationReadSnapshotError(
                "publication read database boundary is unavailable"
            ) from error
        yield


def _fact_table(dataset_key: str) -> str:
    """Resolve a dataset only through the fixed publication fact whitelist."""

    if not isinstance(dataset_key, str):
        raise ValueError("publication read dataset must be a string")
    normalized_key = dataset_key.strip()
    try:
        return _DATASET_FACT_TABLES[normalized_key]
    except KeyError as error:
        raise ValueError(f"unknown dataset for publication read: {dataset_key!r}") from error


def _require_default_connection() -> None:
    """Reject a connection proxy that is not Django's default alias."""

    if getattr(connection, "alias", None) != DEFAULT_DB_ALIAS:
        raise PublicationReadSnapshotError(
            "publication read requires Django's default database connection"
        )


def _configure_outer_postgresql_snapshot() -> None:
    """Configure the outer transaction before any publication data query."""

    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def _query_metadata_tables(dataset_key: str) -> tuple[str, ...]:
    """Resolve structural query dependencies, including absent-row phantoms."""

    if dataset_key in _ASSET_QUERY_DATASETS:
        return (_DATASET_CONTRACT_TABLE, "data_center_asset_master", "data_center_asset_alias")
    if dataset_key == "macro.fact":
        return (_DATASET_CONTRACT_TABLE, "data_center_indicator_catalog")
    return (_DATASET_CONTRACT_TABLE,)


def _stabilize_nested_postgresql_read(fact_table: str, metadata_tables: tuple[str, ...]) -> None:
    """Reuse a stable transaction or lock its fixed publication tables in order."""

    isolation = _show_transaction_setting("SHOW transaction_isolation", "isolation")
    if isolation in _STABLE_ISOLATIONS:
        return
    if isolation != "read committed":
        raise PublicationReadSnapshotError(
            f"publication read requires READ COMMITTED, REPEATABLE READ, or SERIALIZABLE; got {isolation}"
        )
    read_only = _show_transaction_setting("SHOW transaction_read_only", "read_only")
    if read_only in {"on", "true", "yes", "1"}:
        raise PublicationReadSnapshotError(
            "read-only READ COMMITTED transaction cannot provide a stable publication snapshot"
        )
    if read_only not in {"off", "false", "no", "0"}:
        raise PublicationReadSnapshotError(
            f"publication read transaction_read_only value is invalid: {read_only}"
        )
    _lock_publication_tables(fact_table, metadata_tables)


def _show_transaction_setting(statement: str, setting_name: str) -> str:
    """Read and normalize one PostgreSQL transaction setting."""

    with connection.cursor() as cursor:
        return _show_setting(cursor, statement, setting_name)


def _show_setting(cursor: CursorWrapper, statement: str, setting_name: str) -> str:
    """Read one scalar PostgreSQL setting from a cursor result."""

    cursor.execute(statement)
    row = cursor.fetchone()
    if not isinstance(row, tuple) or len(row) != 1 or not isinstance(row[0], str):
        raise PublicationReadSnapshotError(f"PostgreSQL {setting_name} setting is unavailable")
    value = row[0].strip().lower()
    if not value:
        raise PublicationReadSnapshotError(f"PostgreSQL {setting_name} setting is empty")
    return value


def _lock_publication_tables(fact_table: str, metadata_tables: tuple[str, ...]) -> None:
    """Lock metadata first, then facts → policy → publication → members.

    Configuration initialization acquires contracts before policies; acquiring
    metadata first avoids reversing that order. Asset parents precede aliases.
    SHARE protects updates and inserts, including currently absent metadata.
    Each lock waits at most the stricter of the caller's timeout and five
    seconds; seven locks therefore have a maximum total wait of 35 seconds.
    A timeout or deadlock rolls back the nested savepoint and fails closed.
    """

    table_names = (
        *metadata_tables,
        fact_table,
        _DATASET_POLICY_TABLE,
        _CANONICAL_PUBLICATION_TABLE,
        _PUBLICATION_MEMBER_TABLE,
    )
    previous_lock_timeout = _show_transaction_setting("SHOW lock_timeout", "lock_timeout")
    effective_lock_timeout = _bounded_lock_timeout(previous_lock_timeout)
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{effective_lock_timeout}'")
        for table_name in table_names:
            quoted_table = connection.ops.quote_name(table_name)
            cursor.execute(f"LOCK TABLE {quoted_table} IN SHARE MODE")
        _restore_lock_timeout(cursor, previous_lock_timeout)


def _bounded_lock_timeout(value: str) -> str:
    """Keep a stricter caller timeout while bounding disabled or loose values."""

    duration_seconds = _parse_lock_timeout(value)
    if duration_seconds == Decimal("0") or duration_seconds > _LOCK_TIMEOUT_SECONDS:
        return _LOCK_TIMEOUT
    return value


def _parse_lock_timeout(value: str) -> Decimal:
    """Parse a PostgreSQL non-negative ``lock_timeout`` duration in seconds."""

    match = _LOCK_TIMEOUT_VALUE_RE.fullmatch(value)
    if match is None:
        raise PublicationReadSnapshotError("PostgreSQL lock_timeout setting is invalid")
    amount_text = match.group("amount")
    if amount_text is None:
        raise PublicationReadSnapshotError("PostgreSQL lock_timeout setting is invalid")
    unit = match.group("unit") or "ms"
    return Decimal(amount_text) * _LOCK_TIMEOUT_UNIT_SECONDS[unit]


def _restore_lock_timeout(cursor: CursorWrapper, value: str) -> None:
    """Restore a validated transaction-local lock timeout after table locking."""

    _parse_lock_timeout(value)
    cursor.execute(f"SET LOCAL lock_timeout = '{value}'")


__all__ = ["PublicationReadSnapshotError", "consistent_publication_read"]
