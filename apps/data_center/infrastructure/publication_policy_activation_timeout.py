"""Bound and restore PostgreSQL timeouts around one activation transaction."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from django.db import connection
from django.db.backends.utils import CursorWrapper

from apps.data_center.application.publication_policy_activation import (
    PublicationPolicyActivationError,
)

_DURATION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<amount>(?:0|[0-9]+(?:\.[0-9]+)?))\s*(?P<unit>us|ms|min|s|h|d)?"
)
_UNIT_TO_MILLISECONDS: Final[dict[str, Decimal]] = {
    "us": Decimal("0.001"),
    "ms": Decimal("1"),
    "s": Decimal("1000"),
    "min": Decimal("60000"),
    "h": Decimal("3600000"),
    "d": Decimal("86400000"),
}


def _validate_timeout_ms(value: int, field_name: str) -> None:
    """Validate one finite positive activation timeout."""

    if type(value) is not int or value <= 0:
        raise PublicationPolicyActivationError(f"{field_name} must be a positive integer")


def _parse_duration_ms(value: str, setting_name: str) -> Decimal:
    """Parse PostgreSQL's textual timeout setting into milliseconds."""

    match = _DURATION_RE.fullmatch(value.strip().lower())
    if match is None:
        raise PublicationPolicyActivationError(f"PostgreSQL {setting_name} setting is invalid")
    amount_text = match.group("amount")
    unit = match.group("unit") or "ms"
    if amount_text is None:
        raise PublicationPolicyActivationError(f"PostgreSQL {setting_name} setting is invalid")
    return Decimal(amount_text) * _UNIT_TO_MILLISECONDS[unit]


def _effective_timeout(value: str, own_timeout_ms: int, setting_name: str) -> str:
    """Keep a stricter caller timeout while bounding unlimited or loose values."""

    caller_timeout_ms = _parse_duration_ms(value, setting_name)
    if caller_timeout_ms == Decimal("0") or caller_timeout_ms > own_timeout_ms:
        return _format_timeout(own_timeout_ms)
    return value.strip().lower()


def _format_timeout(timeout_ms: int) -> str:
    """Render whole-second bounds in the stable PostgreSQL form."""

    if timeout_ms % 1_000 == 0:
        return f"{timeout_ms // 1_000}s"
    return f"{timeout_ms}ms"


def _show_setting(cursor: CursorWrapper, statement: str, setting_name: str) -> str:
    """Read one scalar PostgreSQL timeout setting."""

    cursor.execute(statement)
    row = cursor.fetchone()
    if not isinstance(row, tuple) or len(row) != 1 or not isinstance(row[0], str):
        raise PublicationPolicyActivationError(f"PostgreSQL {setting_name} setting is unavailable")
    value = row[0].strip().lower()
    if not value:
        raise PublicationPolicyActivationError(f"PostgreSQL {setting_name} setting is empty")
    return value


def _show_timeout_settings() -> tuple[str, str]:
    """Read caller timeout settings before entering the activation savepoint."""

    with connection.cursor() as cursor:
        return (
            _show_setting(cursor, "SHOW lock_timeout", "lock_timeout"),
            _show_setting(cursor, "SHOW statement_timeout", "statement_timeout"),
        )


@dataclass
class _PostgresTimeoutGuard:
    """Apply bounded settings inside a transaction and restore its caller."""

    previous_lock_timeout: str | None
    previous_statement_timeout: str | None
    effective_lock_timeout: str | None
    effective_statement_timeout: str | None
    _applied: bool = False

    def apply(self) -> None:
        """Apply effective settings after the activation transaction begins."""

        if self.effective_lock_timeout is None or self.effective_statement_timeout is None:
            return
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{self.effective_lock_timeout}'")
            cursor.execute(f"SET LOCAL statement_timeout = '{self.effective_statement_timeout}'")
        self._applied = True

    def restore(self) -> None:
        """Restore caller settings after the nested savepoint has settled."""

        if (
            not self._applied
            or self.previous_lock_timeout is None
            or self.previous_statement_timeout is None
            or not connection.in_atomic_block
            or connection.needs_rollback
        ):
            return
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{self.previous_lock_timeout}'")
            cursor.execute(f"SET LOCAL statement_timeout = '{self.previous_statement_timeout}'")


@contextmanager
def postgres_timeout_guard(
    lock_timeout_ms: int,
    statement_timeout_ms: int,
) -> Iterator[_PostgresTimeoutGuard]:
    """Preserve caller PostgreSQL timeouts while bounding one activation.

    The caller must invoke ``guard.apply()`` inside its transaction.  Keeping
    this context outside that transaction ensures an exception first rolls
    back its savepoint, then restores caller-local settings while the parent
    transaction is still usable.  SQLite receives a no-op guard.
    """

    _validate_timeout_ms(lock_timeout_ms, "lock_timeout_ms")
    _validate_timeout_ms(statement_timeout_ms, "statement_timeout_ms")
    if connection.vendor != "postgresql":
        yield _PostgresTimeoutGuard(None, None, None, None)
        return

    previous_lock_timeout, previous_statement_timeout = _show_timeout_settings()
    guard = _PostgresTimeoutGuard(
        previous_lock_timeout=previous_lock_timeout,
        previous_statement_timeout=previous_statement_timeout,
        effective_lock_timeout=_effective_timeout(
            previous_lock_timeout, lock_timeout_ms, "lock_timeout"
        ),
        effective_statement_timeout=_effective_timeout(
            previous_statement_timeout, statement_timeout_ms, "statement_timeout"
        ),
    )
    try:
        yield guard
    except BaseException:
        guard.restore()
        raise
    else:
        guard.restore()


__all__ = ["postgres_timeout_guard"]
