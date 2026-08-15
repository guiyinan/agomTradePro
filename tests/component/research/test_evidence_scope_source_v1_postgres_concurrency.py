"""Opt-in PostgreSQL concurrency evidence for the Evidence scope ledger.

The normal test suite deliberately skips this module.  A run requires an
explicit disposable PostgreSQL URL whose database name contains both
``evidence`` and ``test``.  SQLite, the VPS database, and a non-empty database
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

_EVIDENCE_FLAG = "AGOM_EVIDENCE_SCOPE_PG_CONCURRENCY_EVIDENCE"
_EVIDENCE_URL = "AGOM_EVIDENCE_SCOPE_PG_TEST_DATABASE_URL"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_evidence_scope_source_v1_postgres")
django.setup()

from django.db import close_old_connections, connection, connections
from django.db.migrations.state import ProjectState

from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)
from apps.research.infrastructure.evidence_models import EvidenceScopeSourceV1Model
from apps.research.infrastructure.evidence_scope_source_v1_repository import (
    EvidenceScopeSourceV1Conflict,
    _build_evidence_scope_source_v1_store,
)

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 15, 12, 0, 0, 123456, tzinfo=UTC)


class _Clock:
    """Deterministic aware clock for a disposable evidence database."""

    def now(self) -> datetime:
        return NOW + timedelta(days=1)


def _require_postgresql_evidence() -> None:
    """Require explicit local PostgreSQL opt-in and database identity checks."""

    if os.environ.get(_EVIDENCE_FLAG, "").strip() != "1":
        pytest.skip("Evidence PostgreSQL concurrency is opt-in; " f"set {_EVIDENCE_FLAG}=1")
    database_url = os.environ.get(_EVIDENCE_URL, "").strip()
    if not database_url:
        pytest.fail(f"{_EVIDENCE_URL} is required when {_EVIDENCE_FLAG}=1")
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail(f"{_EVIDENCE_URL} must use a PostgreSQL URL")
    if parsed.hostname is None or parsed.hostname.lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
        "postgresql",
        "db",
    }:
        pytest.fail(f"{_EVIDENCE_URL} must target a local/test-service PostgreSQL host")
    configured_name = unquote(parsed.path.removeprefix("/"))
    configured_lower = configured_name.lower()
    if "evidence" not in configured_lower or "test" not in configured_lower:
        pytest.fail(
            f"{_EVIDENCE_URL} must target a disposable database containing evidence and test"
        )
    if connection.vendor != "postgresql":
        pytest.fail(
            "Evidence PostgreSQL concurrency refused active vendor " f"{connection.vendor!r}"
        )
    runtime_name = str(connection.settings_dict.get("NAME", ""))
    if not runtime_name.lower().startswith("test_") or configured_lower not in runtime_name.lower():
        pytest.fail("Evidence PostgreSQL concurrency refused non-isolated database")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if row is None or str(row[0]) != runtime_name:
        pytest.fail("Evidence PostgreSQL concurrency database identity mismatch")


@pytest.fixture(scope="module", autouse=True)
def _evidence_schema(request: pytest.FixtureRequest, django_db_blocker: object) -> Iterator[None]:
    """Create only the zero-seed Evidence scope table for this opt-in run."""

    if os.environ.get(_EVIDENCE_FLAG, "").strip() != "1":
        pytest.skip("Evidence PostgreSQL concurrency is opt-in; " f"set {_EVIDENCE_FLAG}=1")
    request.getfixturevalue("django_db_setup")
    created = False
    migration = importlib.import_module(
        "apps.research.migrations.0028_evidence_scope_source_v1"
    ).Migration
    before = ProjectState()
    after = before.clone()
    for operation in migration.operations:
        operation.state_forwards("research", after)

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _require_postgresql_evidence()
        table_name = EvidenceScopeSourceV1Model._meta.db_table
        existing_tables = set(connection.introspection.table_names())
        if table_name not in existing_tables:
            with connection.schema_editor() as editor:
                for operation in migration.operations:
                    operation.database_forwards("research", editor, before, after)
            created = True
        else:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                count = int(cursor.fetchone()[0])
            if count:
                pytest.fail(
                    "Evidence PostgreSQL concurrency requires an empty dedicated database; "
                    "refusing to delete existing rows"
                )
        _truncate_rows()
    yield
    if created:
        with django_db_blocker.unblock():  # type: ignore[attr-defined]
            with connection.schema_editor() as editor:
                for operation in reversed(migration.operations):
                    operation.database_backwards("research", editor, after, before)


@pytest.fixture(autouse=True)
def _clear_rows(django_db_blocker: object) -> Iterator[None]:
    """Clear only rows created by this harness between evidence cases."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _truncate_rows()
    yield


def _truncate_rows() -> None:
    table_name = connection.ops.quote_name(EvidenceScopeSourceV1Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY")


def _artifact(identifier: str) -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id=identifier,
        artifact_version="v1",
        content_hash=("a" if identifier == "operator-a" else "b") * 64,
    )


def _source(
    *,
    version: str = "v1",
    previous: EvidenceScopeSourceV1 | None = None,
    artifact: ArtifactRef | None = None,
    validity: timedelta = timedelta(hours=1),
) -> EvidenceScopeSourceV1:
    exact_artifact = artifact or _artifact("operator-a")
    recorded_at = NOW if previous is None else previous.recorded_at + timedelta(minutes=1)
    return EvidenceScopeSourceV1(
        source_id="scope-source-pg-1",
        source_version=version,
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=exact_artifact,
        status="active",
        recorded_at=recorded_at,
        valid_until=recorded_at + validity,
        root_claim_hash=(
            root_claim_hash_for_evidence_scope_source_v1(
                source_id="scope-source-pg-1",
                owner_id="owner-1",
                tenant_id="tenant-1",
                account_id="account-1",
                actor_id="actor-1",
                artifact=exact_artifact,
            )
            if previous is None
            else None
        ),
        supersedes_content_hash=None if previous is None else previous.content_hash,
    )


def _append_root_worker(candidate: EvidenceScopeSourceV1, barrier: Barrier) -> str:
    """Attempt one root append on a fresh Django connection."""

    close_old_connections()
    try:
        store = _build_evidence_scope_source_v1_store(clock=_Clock())
        with store.atomic():
            barrier.wait(timeout=20)
            store.append_root(candidate)
        return "winner"
    except EvidenceScopeSourceV1Conflict:
        return "conflict"
    finally:
        connections["default"].close()


def _append_successor_worker(
    predecessor: EvidenceScopeSourceV1,
    candidate: EvidenceScopeSourceV1,
    barrier: Barrier,
) -> str:
    """Attempt one successor append on a fresh Django connection."""

    close_old_connections()
    try:
        store = _build_evidence_scope_source_v1_store(clock=_Clock())
        with store.atomic():
            barrier.wait(timeout=20)
            store.append_successor(predecessor, candidate)
        return "winner"
    except EvidenceScopeSourceV1Conflict:
        return "conflict"
    finally:
        connections["default"].close()


def test_empty_root_race_has_one_postgresql_winner() -> None:
    """Different roots sharing identity cannot both commit on PostgreSQL."""

    first = _source(artifact=_artifact("operator-a"))
    second = _source(artifact=_artifact("operator-b"))
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_append_root_worker, first, barrier),
            executor.submit(_append_root_worker, second, barrier),
        )
        results = (futures[0].result(timeout=40), futures[1].result(timeout=40))
    assert sorted(results) == ["conflict", "winner"]
    assert EvidenceScopeSourceV1Model._default_manager.count() == 1


def test_same_predecessor_race_has_one_successor() -> None:
    """Two different successors of one predecessor yield one committed child."""

    root = _source()
    store = _build_evidence_scope_source_v1_store(clock=_Clock())
    with store.atomic():
        store.append_root(root)
    first = _source(version="v2", previous=root, validity=timedelta(hours=1))
    second = _source(version="v2", previous=root, validity=timedelta(hours=2))
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_append_successor_worker, root, first, barrier),
            executor.submit(_append_successor_worker, root, second, barrier),
        )
        results = (futures[0].result(timeout=40), futures[1].result(timeout=40))
    assert sorted(results) == ["conflict", "winner"]
    assert EvidenceScopeSourceV1Model._default_manager.count() == 2


def test_rollback_leaves_no_orphan_scope_row() -> None:
    """A caller failure rolls back the append instead of leaving an anchor/row."""

    root = _source()
    store = _build_evidence_scope_source_v1_store(clock=_Clock())
    with pytest.raises(RuntimeError, match="rollback"):
        with store.atomic():
            store.append_root(root)
            raise RuntimeError("rollback")
    assert EvidenceScopeSourceV1Model._default_manager.count() == 0
