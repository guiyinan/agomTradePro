"""Opt-in two-connection PostgreSQL proof for scoped advisory lock ownership."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from copy import deepcopy
from typing import Protocol
from urllib.parse import unquote, urlsplit

import pytest
from django.db import connections, transaction

from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    ScopedAdvisoryLockUnavailableError,
    canonicalize_scoped_advisory_lock_keys,
    try_acquire_scoped_advisory_exclusive,
)

_ALIASES: tuple[str, str] = ("scoped_lock_a", "scoped_lock_b")
_DATABASE_NAME = "evid06_authority_test"
_FIXED_OPTIONS: dict[str, object] = {
    "connect_timeout": 10,
    "sslmode": "disable",
    "gssencmode": "disable",
}


class _DjangoDatabaseBlocker(Protocol):
    """Subset of pytest-django's database blocker used by this fixture."""

    def unblock(self) -> AbstractContextManager[None]:
        """Allow direct access to the explicitly selected disposable database."""


def _test_key(*components: str) -> ScopedAdvisoryLockKey:
    """Build one isolated key in the shared helper test namespace."""

    return ScopedAdvisoryLockKey(domain="shared.advisory-lock-test", components=components)


def _database_settings() -> dict[str, object]:
    """Build a loopback-only alias from the opt-in EVID-06 URL."""

    raw_url = os.environ.get("AGOM_EVID06_POSTGRES_TEST_DATABASE_URL", "").strip()
    if not raw_url:
        pytest.skip("set the disposable EVID-06 PostgreSQL URL to run this component proof")
    try:
        parsed = urlsplit(raw_url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port or 5432
    except ValueError as error:
        pytest.fail(f"EVID-06 PostgreSQL URL is invalid: {error}")
    if os.environ.get("AGOM_EVID06_POSTGRES_TEST", "").strip() != "1":
        pytest.skip("set AGOM_EVID06_POSTGRES_TEST=1 to opt in to PostgreSQL evidence")
    if parsed.scheme.lower() not in {"postgres", "postgresql"}:
        pytest.fail("EVID-06 PostgreSQL URL must use postgres:// or postgresql://")
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("EVID-06 PostgreSQL lock proof requires a loopback host")
    if unquote(parsed.path.removeprefix("/")) != _DATABASE_NAME:
        pytest.fail(f"EVID-06 PostgreSQL lock proof requires the {_DATABASE_NAME!r} database")
    if not parsed.username or parsed.query or parsed.fragment:
        pytest.fail("EVID-06 PostgreSQL lock proof URL has unsupported credentials or query data")
    if not 1 <= port <= 65535:
        pytest.fail("EVID-06 PostgreSQL URL has an invalid port")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _DATABASE_NAME,
        "USER": unquote(parsed.username),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": hostname,
        "PORT": str(port),
        "CONN_MAX_AGE": 0,
        "OPTIONS": dict(_FIXED_OPTIONS),
    }


@pytest.fixture()
def scoped_postgres_aliases(
    django_db_blocker: _DjangoDatabaseBlocker,
) -> Iterator[tuple[str, str]]:
    """Register two real connections to the opt-in disposable EVID-06 database."""

    settings = deepcopy(connections["default"].settings_dict)
    settings.update(_database_settings())
    registered: list[str] = []
    with django_db_blocker.unblock():
        try:
            for alias in _ALIASES:
                if alias in connections.databases:
                    raise RuntimeError(f"test database alias is already registered: {alias}")
                connections.databases[alias] = deepcopy(settings)
                registered.append(alias)
            for alias in _ALIASES:
                connection = connections[alias]
                if connection.vendor != "postgresql":
                    raise RuntimeError("scoped advisory lock proof did not resolve PostgreSQL")
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    row = cursor.fetchone()
                if row is None or str(row[0]) != _DATABASE_NAME:
                    raise RuntimeError("scoped advisory lock proof database identity mismatch")
            yield _ALIASES
        finally:
            for alias in reversed(registered):
                connections[alias].close()
                connections.databases.pop(alias, None)


def test_postgres_partial_plan_rolls_back_prior_acquisition(
    scoped_postgres_aliases: tuple[str, str],
) -> None:
    """A failed second key does not leave the first key in the outer transaction."""

    first_alias, second_alias = scoped_postgres_aliases
    plan = canonicalize_scoped_advisory_lock_keys(
        (_test_key("partial", "first"), _test_key("partial", "second"))
    )
    released_key, blocked_key = plan

    with transaction.atomic(using=second_alias):
        assert try_acquire_scoped_advisory_exclusive(using=second_alias, keys=(blocked_key,)) == (
            blocked_key,
        )
        with transaction.atomic(using=first_alias):
            with pytest.raises(ScopedAdvisoryLockUnavailableError):
                try_acquire_scoped_advisory_exclusive(using=first_alias, keys=plan)
            assert try_acquire_scoped_advisory_exclusive(
                using=second_alias, keys=(released_key,)
            ) == (released_key,)


def test_postgres_success_keeps_lock_until_outer_transaction_ends(
    scoped_postgres_aliases: tuple[str, str],
) -> None:
    """A successful helper call protects its key until the caller commits."""

    first_alias, second_alias = scoped_postgres_aliases
    key = _test_key("success", "outer-transaction")

    with transaction.atomic(using=first_alias):
        assert try_acquire_scoped_advisory_exclusive(using=first_alias, keys=(key,)) == (key,)
        with transaction.atomic(using=second_alias):
            with pytest.raises(ScopedAdvisoryLockUnavailableError):
                try_acquire_scoped_advisory_exclusive(using=second_alias, keys=(key,))

    with transaction.atomic(using=second_alias):
        assert try_acquire_scoped_advisory_exclusive(using=second_alias, keys=(key,)) == (key,)
