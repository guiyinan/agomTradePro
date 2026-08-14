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
)
from apps.account.application.account_user_authority_source_v3 import (
    PersistedAccountUserAuthoritySourceV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_user_authority_source_v3_repository import (
    DjangoAccountUserAuthoritySourceV3Repository,
)
from tests.unit.account.test_account_user_authority_source_v3 import _source, _successor

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW + timedelta(days=1)


def _record(source: AccountUserAuthoritySourceV3) -> PersistedAccountUserAuthoritySourceV3:
    return PersistedAccountUserAuthoritySourceV3(
        source,
        AccountActorAuthorityRawSourceV3Recorder("account-user-authority-recorder-v3"),
    )


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.schema_editor() as editor:
            editor.create_model(AccountUserAuthoritySourceV3AnchorModel)
            editor.create_model(AccountUserAuthoritySourceV3Model)
        yield
        with connection.schema_editor() as editor:
            editor.delete_model(AccountUserAuthoritySourceV3Model)
            editor.delete_model(AccountUserAuthoritySourceV3AnchorModel)


def _repository() -> DjangoAccountUserAuthoritySourceV3Repository:
    return DjangoAccountUserAuthoritySourceV3Repository(clock=_Clock())


def test_root_exact_replay_and_pit_are_zero_seed_and_permanent() -> None:
    repository = _repository()
    source = _source()
    assert repository.get_current_head(source_id=source.identity.source_id, as_of=NOW) is None
    with repository.atomic():
        stored = repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        replay = repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)

    assert replay == stored
    assert AccountUserAuthoritySourceV3AnchorModel.objects.count() == 1
    assert AccountUserAuthoritySourceV3Model.objects.count() == 1
    assert (
        repository.get_winner(
            source_id=source.identity.source_id,
            source_version=source.identity.source_version,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        repository.get_exact_by_hash(
            source_id=source.identity.source_id,
            source_version=source.identity.source_version,
            expected_content_hash=source.content_hash,
            as_of=NOW + timedelta(hours=12),
        )
        == stored
    )


def test_successor_and_deactivated_final_head_never_fall_back() -> None:
    repository = _repository()
    root = _source()
    current = _successor(root, is_staff=True)
    terminal = _successor(
        current,
        identity=type(root.identity)(root.identity.source_id, "v3"),
        clock=type(root.clock)(
            current.clock.recorded_at + timedelta(minutes=1),
            current.clock.recorded_at + timedelta(minutes=1),
            NOW + timedelta(hours=2),
        ),
        authority_state="deactivated",
        is_active=False,
    )
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)
        repository.append(
            _record(current),
            expected_predecessor_hash=root.content_hash,
            recorded_at=current.clock.recorded_at,
        )
        repository.append(
            _record(terminal),
            expected_predecessor_hash=current.content_hash,
            recorded_at=terminal.clock.recorded_at,
        )

    assert repository.get_current_head(
        source_id=root.identity.source_id,
        as_of=current.clock.recorded_at - timedelta(microseconds=1),
    ) == _record(root)
    assert repository.get_current_head(
        source_id=root.identity.source_id, as_of=current.clock.recorded_at
    ) == _record(current)
    assert repository.get_current_head(
        source_id=root.identity.source_id, as_of=NOW + timedelta(hours=12)
    ) == _record(terminal)
    later = _successor(
        terminal,
        identity=type(root.identity)(root.identity.source_id, "v4"),
        clock=type(root.clock)(
            terminal.clock.recorded_at + timedelta(minutes=1),
            terminal.clock.recorded_at + timedelta(minutes=1),
            NOW + timedelta(hours=2),
        ),
    )
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        with repository.atomic():
            repository.append(
                _record(later),
                expected_predecessor_hash=terminal.content_hash,
                recorded_at=later.clock.recorded_at,
            )


def test_private_uow_cas_failure_rolls_back_anchor_even_when_caught() -> None:
    repository = _repository()
    source = _source()
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
            repository.append(_record(source), expected_predecessor_hash="f" * 64, recorded_at=NOW)
    assert AccountUserAuthoritySourceV3AnchorModel.objects.count() == 0
    assert AccountUserAuthoritySourceV3Model.objects.count() == 0
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        with repository.atomic():
            with repository.atomic():
                pass


def test_full_table_restore_detects_recorder_and_canonical_tamper() -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
    table = AccountUserAuthoritySourceV3Model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET "recorded_by_service_id" = %s',  # noqa: S608
            ["substituted-recorder"],
        )
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        repository.get_current_head(source_id="unrelated", as_of=NOW)
