from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import django
import pytest

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_account_actor_authority_source_v3"
django.setup()

from django.db import connection

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Selector,
)
from apps.account.application.account_authentication_context_source_v3 import (
    GetCurrentAccountAuthenticationContextSourceV3,
    GetExactAccountAuthenticationContextSourceV3,
    PersistedAccountAuthenticationContextSourceV3,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.account.test_account_authentication_context_source_v3 import (
    NOW,
    _source,
    _successor,
)


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 20, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(
            (
                AccountAuthenticationContextSourceV3AnchorModel,
                AccountAuthenticationContextSourceV3Model,
            )
        ):
            yield


def _repository() -> DjangoAccountAuthenticationContextSourceV3Repository:
    return DjangoAccountAuthenticationContextSourceV3Repository(clock=_Clock())


def _record(source: object) -> PersistedAccountAuthenticationContextSourceV3:
    return PersistedAccountAuthenticationContextSourceV3(
        source,  # type: ignore[arg-type]
        AccountActorAuthorityRawSourceV3Recorder("auth-context-raw-recorder-v3"),
    )


def _append_root(repository: DjangoAccountAuthenticationContextSourceV3Repository):
    source = _source()
    record = _record(source)
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=source.clock.recorded_at,
            )
            == record
        )
    return source, record


def _selector(source: object, as_of: datetime) -> AccountActorAuthorityRawSourceV3Selector:
    return AccountActorAuthorityRawSourceV3Selector(
        source.identity.source_id,  # type: ignore[attr-defined]
        source.identity.source_version,  # type: ignore[attr-defined]
        source.content_hash,  # type: ignore[attr-defined]
        as_of,
    )


def test_root_exact_replay_and_permanent_pit_read() -> None:
    repository = _repository()
    source, record = _append_root(repository)
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=source.clock.recorded_at,
            )
            == record
        )

    assert (
        repository.get_exact_by_hash(
            source_id=source.identity.source_id,
            source_version=source.identity.source_version,
            expected_content_hash=source.content_hash,
            as_of=source.clock.recorded_at - timedelta(microseconds=1),
        )
        is None
    )
    cutoff = source.clock.valid_until + timedelta(days=1)
    assert (
        GetExactAccountAuthenticationContextSourceV3(repository).execute(_selector(source, cutoff))
        == source
    )
    assert AccountAuthenticationContextSourceV3AnchorModel.objects.count() == 1
    assert AccountAuthenticationContextSourceV3Model.objects.count() == 1


def test_successor_terminal_head_never_falls_back_and_cannot_extend() -> None:
    repository = _repository()
    root, _ = _append_root(repository)
    revoked = _successor(root)
    revoked_record = _record(revoked)
    with repository.atomic():
        repository.append(
            revoked_record,
            expected_predecessor_hash=root.content_hash,
            recorded_at=revoked.clock.recorded_at,
        )
    cutoff = revoked.clock.recorded_at

    assert (
        repository.get_current_head(source_id=root.identity.source_id, as_of=cutoff)
        == revoked_record
    )
    assert (
        GetCurrentAccountAuthenticationContextSourceV3(repository).execute(_selector(root, cutoff))
        is None
    )
    assert (
        GetCurrentAccountAuthenticationContextSourceV3(repository).execute(
            _selector(revoked, cutoff)
        )
        is None
    )

    invalid_successor = _successor(
        revoked,
        identity=type(revoked.identity)(revoked.identity.source_id, "v3"),
        clock=type(revoked.clock)(
            NOW + timedelta(minutes=4),
            NOW + timedelta(minutes=5),
            NOW + timedelta(hours=3),
        ),
    )
    with repository.atomic():
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
            repository.append(
                _record(invalid_successor),
                expected_predecessor_hash=revoked.content_hash,
                recorded_at=invalid_successor.clock.recorded_at,
            )
    assert AccountAuthenticationContextSourceV3Model.objects.count() == 2


def test_every_read_restores_whole_table_and_detects_scalar_tamper() -> None:
    repository = _repository()
    source, _ = _append_root(repository)
    table = AccountAuthenticationContextSourceV3Model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(f'UPDATE "{table}" SET principal_id = %s', ["substituted"])

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        repository.get_winner(
            source_id=source.identity.source_id,
            source_version=source.identity.source_version,
            as_of=source.clock.recorded_at,
        )


def test_private_uow_is_nonnested_and_failed_append_rolls_back_anchor() -> None:
    repository = _repository()
    source = _source()
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        repository.append(
            _record(source),
            expected_predecessor_hash=None,
            recorded_at=source.clock.recorded_at,
        )
    with repository.atomic():
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
            with repository.atomic():
                pass
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
            repository.append(
                _record(source),
                expected_predecessor_hash="f" * 64,
                recorded_at=source.clock.recorded_at,
            )
        assert AccountAuthenticationContextSourceV3AnchorModel.objects.count() == 0
    assert AccountAuthenticationContextSourceV3AnchorModel.objects.count() == 0
    assert AccountAuthenticationContextSourceV3Model.objects.count() == 0


def test_wrong_cas_does_not_create_fork_or_orphan() -> None:
    repository = _repository()
    root, _ = _append_root(repository)
    successor = _successor(root)
    with repository.atomic():
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
            repository.append(
                _record(successor),
                expected_predecessor_hash="e" * 64,
                recorded_at=successor.clock.recorded_at,
            )
    assert AccountAuthenticationContextSourceV3AnchorModel.objects.count() == 1
    assert AccountAuthenticationContextSourceV3Model.objects.count() == 1
