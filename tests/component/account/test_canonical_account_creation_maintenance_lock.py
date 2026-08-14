from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.account.infrastructure import canonical_account_creation_maintenance_lock as locks
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _fake_connection(*, vendor: str, in_atomic_block: bool = True) -> tuple[object, MagicMock]:
    cursor = MagicMock()
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = SimpleNamespace(
        vendor=vendor,
        in_atomic_block=in_atomic_block,
        cursor=MagicMock(return_value=cursor_context),
    )
    return connection, cursor


def test_postgresql_writer_and_maintenance_use_same_transaction_lock_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, cursor = _fake_connection(vendor="postgresql")
    monkeypatch.setattr(locks, "connections", {"ledger": connection})

    locks.acquire_canonical_account_creation_writer_lock(using="ledger")
    locks.acquire_canonical_account_creation_maintenance_lock(using="ledger")

    writer_sql, writer_params = cursor.execute.call_args_list[0].args
    maintenance_sql, maintenance_params = cursor.execute.call_args_list[1].args
    assert writer_sql == "SELECT pg_advisory_xact_lock_shared(%s)"
    assert maintenance_sql == "SELECT pg_advisory_xact_lock(%s)"
    assert writer_params == maintenance_params


def test_postgresql_lock_requires_active_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, _ = _fake_connection(vendor="postgresql", in_atomic_block=False)
    monkeypatch.setattr(locks, "connections", {"ledger": connection})

    with pytest.raises(
        locks.CanonicalAccountCreationMaintenanceLockUnavailable,
        match="requires an active transaction",
    ):
        locks.acquire_canonical_account_creation_writer_lock(using="ledger")


def test_maintenance_lock_rejects_sqlite_without_explicit_test_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, _ = _fake_connection(vendor="sqlite")
    monkeypatch.setattr(locks, "connections", {"ledger": connection})

    with pytest.raises(
        locks.CanonicalAccountCreationMaintenanceLockUnavailable,
        match="require PostgreSQL",
    ):
        locks.acquire_canonical_account_creation_maintenance_lock(using="ledger")

    locks.acquire_canonical_account_creation_maintenance_lock(
        using="ledger", allow_sqlite_test_degradation=True
    )


def test_both_writer_repositories_acquire_shared_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_lock = MagicMock()
    consumption_lock = MagicMock()
    monkeypatch.setattr(
        "apps.account.infrastructure.canonical_account_creation_repository."
        "acquire_canonical_account_creation_writer_lock",
        legacy_lock,
    )
    monkeypatch.setattr(
        "apps.account.infrastructure.canonical_account_creation_consumption_repository."
        "acquire_canonical_account_creation_writer_lock",
        consumption_lock,
    )

    with DjangoCanonicalAccountCreationRepository(using="default").atomic():
        pass
    with DjangoCanonicalAccountCreationConsumptionRepository(using="default").atomic():
        pass

    legacy_lock.assert_called_once_with(using="default")
    consumption_lock.assert_called_once_with(using="default")
