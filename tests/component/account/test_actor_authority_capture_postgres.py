"""Opt-in real PostgreSQL capture, replay, locking and rollback evidence."""

from datetime import timedelta
from unittest.mock import Mock

import psycopg
import pytest
from django.db import connections, transaction

from apps.account import account_actor_authority_capture_composition as composition
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Recorder,
)
from apps.account.application.account_authentication_context_source_v3 import (
    PersistedAccountAuthenticationContextSourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceClockV3,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from tests.support import actor_authority_capture_postgres as pg_support
from tests.support.actor_authority_capture_postgres import (
    CAPTURE_AT,
    Clock,
    seed_raw_sources,
)
from tests.unit.account.test_account_authentication_context_source_v3 import _source, _successor

pytestmark = pytest.mark.usefixtures("pg_capture_alias")
capture_database = pg_support.pg_capture_alias


def _prepare(alias: str, monkeypatch: pytest.MonkeyPatch):
    context, user, rbac = seed_raw_sources(alias)
    command = CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
        "actor-capture-pg",
        "v1",
        context.principal_id,
        context.user_id,
        context.identity.source_id,
        context.identity.source_version,
        context.content_hash,
        user.identity.source_id,
        user.identity.source_version,
        user.content_hash,
        rbac.identity.source_id,
        rbac.identity.source_version,
        rbac.content_hash,
    )
    repository = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(
        using=alias, clock=Clock()
    )
    monkeypatch.setattr(
        composition,
        "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository",
        Mock(return_value=repository),
    )
    capture = composition.build_account_actor_authority_capture(
        using=alias, recorder_service_id="local-pg-test", validity_period=timedelta(minutes=5)
    )
    return command, repository, capture


def _competitor() -> psycopg.Connection:
    return psycopg.connect(
        host="127.0.0.1", port=55435, dbname="evid05_authority_test", user="postgres"
    )


def _raw_tables(alias: str) -> list[str]:
    return sorted(
        name
        for name in connections[alias].introspection.table_names()
        if name.startswith(
            ("account_auth_context_", "account_user_authority_", "account_rbac_authority_")
        )
    )


def _assert_no_actor_rows(alias: str) -> None:
    with connections[alias].cursor() as cursor:
        for table in (
            "account_actor_authority_source_v3_root_lock",
            "account_actor_authority_source_v3_ledger",
        ):
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)


def test_first_capture_current_read_and_winner_replay(
    pg_capture_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, repository, capture = _prepare(pg_capture_alias, monkeypatch)
    source = capture.execute(command)
    reader = composition.build_account_actor_authority_request_reader(
        using=pg_capture_alias,
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
    )
    assert (
        reader.get_exact_current(
            principal_id=command.principal_id,
            user_id=command.user_id,
            expected_authentication_context_hash=command.expected_authentication_context_content_hash,
            as_of=CAPTURE_AT,
        )
        is not None
    )
    # A historical winner must replay without reading even a currently locked raw ledger.
    with _competitor() as competitor:
        competitor.execute(
            "LOCK TABLE account_user_authority_source_v3_ledger IN ACCESS EXCLUSIVE MODE"
        )
        assert capture.execute(command) == source
    assert (
        repository.get_winner(
            source_id=source.source_id, source_version=source.source_version, as_of=CAPTURE_AT
        ).source
        == source
    )


@pytest.mark.parametrize("table_index", range(6))
def test_each_raw_table_write_conflict_fails_without_actor_rows(
    pg_capture_alias: str, monkeypatch: pytest.MonkeyPatch, table_index: int
) -> None:
    command, _, capture = _prepare(pg_capture_alias, monkeypatch)
    tables = _raw_tables(pg_capture_alias)
    assert len(tables) == 6
    with _competitor() as competitor:
        competitor.execute(f'LOCK TABLE "{tables[table_index]}" IN ROW EXCLUSIVE MODE')
        with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Unavailable):
            capture.execute(command)
        _assert_no_actor_rows(pg_capture_alias)
    assert capture.execute(command).source_id == command.source_id


def test_all_raw_locks_survive_final_read_until_append(
    pg_capture_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, repository, capture = _prepare(pg_capture_alias, monkeypatch)
    append = repository.append
    tested: list[str] = []

    def checked_append(*args: object, **kwargs: object):
        with _competitor() as competitor:
            for table in _raw_tables(pg_capture_alias):
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    with competitor.transaction():
                        competitor.execute(f'LOCK TABLE "{table}" IN ROW EXCLUSIVE MODE NOWAIT')
                tested.append(table)
        return append(*args, **kwargs)

    monkeypatch.setattr(repository, "append", checked_append)
    capture.execute(command)
    assert len(tested) == 6
    # Commit releases the locks, allowing an upstream mutation transaction to proceed.
    with _competitor() as competitor:
        for table in tested:
            competitor.execute(f'LOCK TABLE "{table}" IN ROW EXCLUSIVE MODE NOWAIT')


def test_error_after_append_rolls_back_actor_root_and_ledger(
    pg_capture_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, repository, capture = _prepare(pg_capture_alias, monkeypatch)
    append = repository.append

    def failed_append(*args: object, **kwargs: object):
        append(*args, **kwargs)
        raise RuntimeError("test failure after insert")

    monkeypatch.setattr(repository, "append", failed_append)
    with pytest.raises(RuntimeError, match="test failure after insert"):
        capture.execute(command)
    _assert_no_actor_rows(pg_capture_alias)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_capture_rejects_an_old_snapshot_transaction(
    pg_capture_alias: str, monkeypatch: pytest.MonkeyPatch, isolation: str
) -> None:
    command, _, capture = _prepare(pg_capture_alias, monkeypatch)
    with transaction.atomic(using=pg_capture_alias):
        with connections[pg_capture_alias].cursor() as cursor:
            cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Unavailable):
            capture.execute(command)
    _assert_no_actor_rows(pg_capture_alias)


def test_committed_raw_revocation_invalidates_current_reader(
    pg_capture_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, actor_repository, capture = _prepare(pg_capture_alias, monkeypatch)
    source = capture.execute(command)
    revoked_at = CAPTURE_AT + timedelta(minutes=1)
    revoked = _successor(
        _source(),
        clock=AccountAuthorityRawSourceClockV3(
            revoked_at, revoked_at, CAPTURE_AT + timedelta(hours=1)
        ),
    )
    raw_repository = DjangoAccountAuthenticationContextSourceV3Repository(
        using=pg_capture_alias, clock=Mock(now=Mock(return_value=revoked_at))
    )
    with raw_repository.atomic():
        raw_repository.append(
            PersistedAccountAuthenticationContextSourceV3(
                revoked, AccountActorAuthorityRawSourceV3Recorder("local-pg-test")
            ),
            expected_predecessor_hash=revoked.chain.supersedes_content_hash,
            recorded_at=revoked.clock.recorded_at,
        )
    monkeypatch.setattr(actor_repository, "now", lambda: revoked_at)
    reader = composition.build_account_actor_authority_request_reader(
        using=pg_capture_alias,
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
    )
    assert (
        reader.get_exact_current(
            principal_id=command.principal_id,
            user_id=command.user_id,
            expected_authentication_context_hash=command.expected_authentication_context_content_hash,
            as_of=revoked_at,
        )
        is None
    )
    assert capture.execute(command) == source
