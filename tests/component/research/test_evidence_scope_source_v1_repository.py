"""Component proof for the dormant Evidence scope-source v1 repository."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_evidence_scope_source_v1")
django.setup()

from django.db import connection

from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Unavailable,
    GetCurrentEvidenceScopeSourceV1,
    GetCurrentEvidenceScopeSourceV1Command,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)
from apps.research.infrastructure.evidence_models import EvidenceScopeSourceV1Model
from apps.research.infrastructure.evidence_scope_source_v1_repository import (
    DjangoEvidenceScopeSourceV1Repository,
    EvidenceScopeSourceV1Clock,
    EvidenceScopeSourceV1Conflict,
    EvidenceScopeSourceV1Corruption,
    _build_evidence_scope_source_v1_store,
)
from tests.support.isolated_schema import isolated_schema

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _NaiveClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 15, 8)


class _FailingClock:
    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the target table, avoiding the full project migration graph."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((EvidenceScopeSourceV1Model,)):
            yield


def _artifact(identifier: str = "operator-1") -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id=identifier,
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _source(
    *,
    version: str = "v1",
    previous: EvidenceScopeSourceV1 | None = None,
    status: str = "active",
    recorded_at: datetime | None = None,
    artifact: ArtifactRef | None = None,
) -> EvidenceScopeSourceV1:
    exact_artifact = artifact or _artifact()
    exact_recorded_at = (
        recorded_at
        if recorded_at is not None
        else NOW if previous is None else previous.recorded_at + timedelta(minutes=1)
    )
    root_claim_hash = None
    supersedes_content_hash = None
    if previous is None:
        root_claim_hash = root_claim_hash_for_evidence_scope_source_v1(
            source_id="scope-source-1",
            owner_id="owner-1",
            tenant_id="tenant-1",
            account_id="account-1",
            actor_id="actor-1",
            artifact=exact_artifact,
        )
    else:
        supersedes_content_hash = previous.content_hash
    return EvidenceScopeSourceV1(
        source_id="scope-source-1",
        source_version=version,
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=exact_artifact,
        status=status,
        recorded_at=exact_recorded_at,
        valid_until=exact_recorded_at + timedelta(hours=1),
        root_claim_hash=root_claim_hash,
        supersedes_content_hash=supersedes_content_hash,
    )


def test_private_store_round_trips_root_successor_and_exact_replay() -> None:
    root = _source()
    successor = _source(version="v2", previous=root)
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW + timedelta(hours=2)))

    with store.atomic():
        assert store.append_root(root) == root
        assert store.append_root(root) == root
        assert store.append_successor(root, successor) == successor

    reader = DjangoEvidenceScopeSourceV1Repository(clock=_Clock(NOW + timedelta(hours=2)))
    assert EvidenceScopeSourceV1Model._default_manager.count() == 2
    assert (
        reader.get_exact(
            source_id=root.source_id,
            source_version=root.source_version,
            expected_content_hash=root.content_hash,
            as_of=NOW,
        )
        == root
    )
    assert reader.get_current_head(source_id=root.source_id, as_of=NOW) == root
    assert (
        reader.get_current_head(source_id=root.source_id, as_of=successor.recorded_at) == successor
    )


def test_current_reader_does_not_fallback_from_terminal_head() -> None:
    root = _source()
    revoked = _source(version="v2", previous=root, status="revoked")
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW + timedelta(hours=2)))
    with store.atomic():
        store.append_root(root)
        store.append_successor(root, revoked)

    reader = DjangoEvidenceScopeSourceV1Repository(clock=_Clock(NOW + timedelta(hours=2)))
    assert reader.get_current_head(source_id=root.source_id, as_of=revoked.recorded_at) == revoked
    result = GetCurrentEvidenceScopeSourceV1(reader).execute(
        GetCurrentEvidenceScopeSourceV1Command(
            source_id=root.source_id,
            source_version=root.source_version,
            expected_content_hash=root.content_hash,
            as_of=revoked.recorded_at,
        )
    )
    assert result is None


def test_append_requires_private_atomic_and_rolls_back_root_on_failure() -> None:
    root = _source()
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW))
    with pytest.raises(EvidenceScopeSourceV1Conflict, match="private atomic"):
        store.append_root(root)

    with pytest.raises(RuntimeError, match="rollback"):
        with store.atomic():
            store.append_root(root)
            raise RuntimeError("rollback")
    assert EvidenceScopeSourceV1Model._default_manager.count() == 0


def test_same_identity_with_different_canonical_content_conflicts() -> None:
    root = _source()
    changed = replace(
        root,
        valid_until=root.valid_until + timedelta(minutes=1),
        identity_hash="",
        content_hash="",
    )
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW + timedelta(hours=2)))
    with store.atomic():
        store.append_root(root)
        with pytest.raises(EvidenceScopeSourceV1Conflict, match="forks"):
            store.append_root(changed)
    assert EvidenceScopeSourceV1Model._default_manager.count() == 1


def test_future_successor_is_not_visible_before_its_recorded_at() -> None:
    root = _source()
    successor = _source(
        version="v2",
        previous=root,
        recorded_at=NOW + timedelta(hours=1),
    )
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW + timedelta(hours=2)))
    with store.atomic():
        store.append_root(root)
        store.append_successor(root, successor)

    reader = DjangoEvidenceScopeSourceV1Repository(clock=_Clock(NOW + timedelta(hours=2)))
    assert (
        reader.get_exact(
            source_id=successor.source_id,
            source_version=successor.source_version,
            expected_content_hash=successor.content_hash,
            as_of=NOW,
        )
        is None
    )
    assert reader.get_current_head(source_id=root.source_id, as_of=NOW) == root


def test_append_rejects_future_recorded_at_without_persisting_a_row() -> None:
    """A caller cannot backdate the ledger into a server-future PIT."""

    future_root = _source(recorded_at=NOW + timedelta(hours=3))
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW + timedelta(hours=2)))
    with store.atomic():
        with pytest.raises(EvidenceScopeSourceV1Conflict, match="recorded_at.*future"):
            store.append_root(future_root)
    assert EvidenceScopeSourceV1Model._default_manager.count() == 0


@pytest.mark.parametrize("clock", [_NaiveClock(), _FailingClock()])
def test_append_fails_closed_when_server_clock_is_unavailable(
    clock: EvidenceScopeSourceV1Clock,
) -> None:
    """Naive or unavailable server clocks never authorize an append."""

    store = _build_evidence_scope_source_v1_store(clock=clock)
    with store.atomic():
        with pytest.raises(EvidenceScopeSourceV1Unavailable, match="server clock"):
            store.append_root(_source())
    assert EvidenceScopeSourceV1Model._default_manager.count() == 0


def test_full_world_restore_rejects_unrelated_header_tamper() -> None:
    root = _source()
    successor = _source(version="v2", previous=root)
    store = _build_evidence_scope_source_v1_store(clock=_Clock(NOW + timedelta(hours=2)))
    with store.atomic():
        store.append_root(root)
        store.append_successor(root, successor)

    table = connection.ops.quote_name(EvidenceScopeSourceV1Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET tenant_id = %s WHERE content_hash = %s",
            ["tampered-tenant", successor.content_hash],
        )

    reader = DjangoEvidenceScopeSourceV1Repository(clock=_Clock(NOW + timedelta(hours=2)))
    with pytest.raises(EvidenceScopeSourceV1Corruption, match="headers"):
        reader.get_exact(
            source_id=root.source_id,
            source_version=root.source_version,
            expected_content_hash=root.content_hash,
            as_of=NOW,
        )
