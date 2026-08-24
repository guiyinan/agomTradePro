"""Opt-in PostgreSQL concurrency evidence for owner/tenant authority v1.

The normal suite skips this module.  A run requires an explicit disposable
PostgreSQL URL whose database name contains both ``authority`` and ``test``.
Production/VPS hosts, production-like names, SQLite, and non-empty databases
are refused; a skipped run is not evidence of PostgreSQL concurrency.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from urllib.parse import unquote, urlsplit

import django
import pytest

_FLAG = "AGOM_OWNER_TENANT_AUTHORITY_PG_CONCURRENCY_EVIDENCE"
_URL = "AGOM_OWNER_TENANT_AUTHORITY_PG_TEST_DATABASE_URL"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_owner_tenant_authority_v1_postgres")
django.setup()

from django.db import close_old_connections, connection, connections
from django.db.migrations.state import ProjectState

from apps.account.application.owner_tenant_authority_v1 import OwnerTenantAuthorityV1Conflict
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.owner_tenant_authority_v1 import OwnerTenantAuthorityV1
from apps.account.infrastructure.owner_tenant_authority_v1_models import (
    OwnerTenantAuthorityV1Model,
)
from apps.account.infrastructure.owner_tenant_authority_v1_repository import (
    DjangoOwnerTenantAuthorityV1Repository,
)

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 24, 12, 0, 0, 123456, tzinfo=UTC)


class _Clock:
    """Deterministic server clock for the disposable authority database."""

    def now(self) -> datetime:
        return NOW + timedelta(days=7)


@pytest.fixture(scope="session", autouse=True)
def _create_authority_database_before_registry_fixture(
    request: pytest.FixtureRequest,
) -> None:
    """Create the isolated database before the shared registry reset imports models."""

    if os.environ.get(_FLAG, "").strip() == "1":
        request.getfixturevalue("django_db_setup")


def _require_postgresql_authority() -> None:
    """Require explicit local PostgreSQL opt-in and identity checks."""

    if os.environ.get(_FLAG, "").strip() != "1":
        pytest.skip(f"Owner/tenant authority PostgreSQL concurrency is opt-in; set {_FLAG}=1")
    database_url = os.environ.get(_URL, "").strip()
    if not database_url:
        pytest.fail(f"{_URL} is required when {_FLAG}=1")
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail(f"{_URL} must use a PostgreSQL URL")
    if parsed.hostname is None or parsed.hostname.lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
        "postgresql",
        "db",
    }:
        pytest.fail(f"{_URL} must target a local/test-service PostgreSQL host")
    configured_name = unquote(parsed.path.removeprefix("/"))
    configured_lower = configured_name.lower()
    if "authority" not in configured_lower or "test" not in configured_lower:
        pytest.fail(f"{_URL} must target a disposable authority test database")
    if connection.vendor != "postgresql":
        pytest.fail(f"authority concurrency refused active vendor {connection.vendor!r}")
    runtime_name = str(connection.settings_dict.get("NAME", ""))
    if not runtime_name.lower().startswith("test_") or configured_lower not in runtime_name.lower():
        pytest.fail("authority concurrency refused a non-isolated database")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if row is None or str(row[0]) != runtime_name:
        pytest.fail("authority concurrency database identity mismatch")


@pytest.fixture(scope="module", autouse=True)
def _authority_schema(request: pytest.FixtureRequest, django_db_blocker: object) -> Iterator[None]:
    """Create only the zero-seed authority table for this opt-in run."""

    if os.environ.get(_FLAG, "").strip() != "1":
        pytest.skip(f"Owner/tenant authority PostgreSQL concurrency is opt-in; set {_FLAG}=1")
    request.getfixturevalue("django_db_setup")
    created = False
    migration = importlib.import_module(
        "apps.account.migrations.0055_owner_tenant_authority_v1"
    ).Migration
    before = ProjectState()
    after = before.clone()
    for operation in migration.operations:
        operation.state_forwards("account", after)

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _require_postgresql_authority()
        table_name = OwnerTenantAuthorityV1Model._meta.db_table
        existing_tables = set(connection.introspection.table_names())
        if table_name not in existing_tables:
            with connection.schema_editor() as editor:
                for operation in migration.operations:
                    operation.database_forwards("account", editor, before, after)
            created = True
        else:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                count = int(cursor.fetchone()[0])
            if count:
                pytest.fail(
                    "authority PostgreSQL concurrency requires an empty dedicated database; "
                    "refusing to delete existing rows"
                )
        _truncate_rows()
    yield
    if created:
        with django_db_blocker.unblock():  # type: ignore[attr-defined]
            with connection.schema_editor() as editor:
                for operation in reversed(migration.operations):
                    operation.database_backwards("account", editor, after, before)


@pytest.fixture(autouse=True)
def _clear_rows(django_db_blocker: object) -> Iterator[None]:
    """Clear rows created by this harness between authority cases."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _truncate_rows()
    yield


def _truncate_rows() -> None:
    table_name = connection.ops.quote_name(OwnerTenantAuthorityV1Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY")


def _authority(
    *,
    version: str = "v1",
    owner_id: str = "owner-1",
    recorded_at: datetime = NOW,
    valid_until: datetime = NOW + timedelta(days=2),
    supersedes_content_hash: str | None = None,
) -> OwnerTenantAuthorityV1:
    """Build a deterministic authority fact with independent staff approval."""

    return OwnerTenantAuthorityV1(
        authority_id="authority-pg-1",
        authority_version=version,
        tenant_id="tenant-1",
        owner_id=owner_id,
        account_namespace="broker",
        account_id="account-1",
        actor_id="owner-actor-1",
        actor_user_id=101,
        assignment_evidence_id="assignment-evidence-1",
        assignment_evidence_version="v1",
        assignment_evidence_content_hash="a" * 64,
        status="active",
        approved_by=AccountOwnerAssignmentActor(
            actor_id="approver-1",
            user_id=202,
            role="owner_tenant_authority_approver",
            is_staff=True,
        ),
        approved_at=recorded_at,
        recorded_at=recorded_at,
        valid_until=valid_until,
        supersedes_content_hash=supersedes_content_hash,
    )


def _append_worker(candidate: OwnerTenantAuthorityV1, barrier: Barrier) -> str:
    """Attempt one append on a fresh Django connection."""

    close_old_connections()
    try:
        repository = DjangoOwnerTenantAuthorityV1Repository(clock=_Clock())
        with repository.atomic():
            barrier.wait(timeout=20)
            repository.append(
                candidate,
                expected_predecessor_hash=candidate.supersedes_content_hash,
                recorded_at=candidate.recorded_at,
            )
        return "winner"
    except OwnerTenantAuthorityV1Conflict:
        return "conflict"
    finally:
        connections["default"].close()


def test_empty_root_race_has_one_postgresql_winner() -> None:
    """Different roots sharing identity cannot both commit on PostgreSQL."""

    first = _authority(owner_id="owner-a")
    second = _authority(owner_id="owner-b")
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_append_worker, first, barrier),
            executor.submit(_append_worker, second, barrier),
        )
        results = (futures[0].result(timeout=40), futures[1].result(timeout=40))
    assert sorted(results) == ["conflict", "winner"]
    assert OwnerTenantAuthorityV1Model._default_manager.count() == 1


def test_same_predecessor_race_has_one_successor() -> None:
    """Two successors of one root yield one committed child."""

    root = _authority()
    repository = DjangoOwnerTenantAuthorityV1Repository(clock=_Clock())
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
    first = _authority(
        version="v2",
        recorded_at=NOW + timedelta(minutes=1),
        valid_until=NOW + timedelta(days=2, minutes=1),
        supersedes_content_hash=root.content_hash,
    )
    second = _authority(
        version="v2",
        recorded_at=NOW + timedelta(minutes=1),
        valid_until=NOW + timedelta(days=3),
        supersedes_content_hash=root.content_hash,
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_append_worker, first, barrier),
            executor.submit(_append_worker, second, barrier),
        )
        results = (futures[0].result(timeout=40), futures[1].result(timeout=40))
    assert sorted(results) == ["conflict", "winner"]
    assert OwnerTenantAuthorityV1Model._default_manager.count() == 2


def test_outer_transaction_rollback_leaves_no_orphan() -> None:
    """A caller failure rolls back the authority append completely."""

    root = _authority()
    repository = DjangoOwnerTenantAuthorityV1Repository(clock=_Clock())
    with pytest.raises(RuntimeError, match="rollback"):
        with repository.atomic():
            repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
            raise RuntimeError("rollback")
    assert OwnerTenantAuthorityV1Model._default_manager.count() == 0


def test_0055_forward_reverse_reforward_remains_zero_seed() -> None:
    """The schema-only migration can round-trip without creating authority rows."""

    migration = importlib.import_module(
        "apps.account.migrations.0055_owner_tenant_authority_v1"
    ).Migration
    before = ProjectState()
    after = before.clone()
    for operation in migration.operations:
        operation.state_forwards("account", after)
    with connection.schema_editor() as editor:
        for operation in reversed(migration.operations):
            operation.database_backwards("account", editor, after, before)
        for operation in migration.operations:
            operation.database_forwards("account", editor, before, after)
    assert OwnerTenantAuthorityV1Model._default_manager.count() == 0
