from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import django
import pytest

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_account_actor_authority_source_v3"
django.setup()

from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Recorder,
    PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
    root_claim_hash_for_actor_authority_source_v3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from tests.support.isolated_schema import isolated_schema

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW + timedelta(days=1)


def _source(**changes: object) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    values: dict[str, object] = {
        "source_id": "authority-session-41",
        "source_version": "v1",
        "principal_id": "principal-41",
        "user_id": 41,
        "authentication_context_id": "session-abc",
        "authentication_context_version": "generation-1",
        "authentication_context_identity_hash": "a" * 64,
        "authentication_context_content_hash": "b" * 64,
        "user_source_id": "django-user-41",
        "user_source_version": "v7",
        "user_source_content_hash": "c" * 64,
        "rbac_source_id": "account-profile-41",
        "rbac_source_version": "v3",
        "rbac_source_content_hash": "d" * 64,
        "actor_id": "django-user:41",
        "is_authenticated": True,
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
        "rbac_role": "owner",
        "authority_state": "current",
        "principal_authenticated_at": NOW - timedelta(minutes=10),
        "principal_valid_until": NOW + timedelta(hours=4),
        "source_recorded_at": NOW - timedelta(minutes=5),
        "source_valid_until": NOW + timedelta(hours=3),
        "issued_at": NOW - timedelta(minutes=2),
        "recorded_at": NOW,
        "ttl_valid_until": NOW + timedelta(hours=2),
        "valid_until": NOW + timedelta(hours=2),
        "root_claim_hash": root_claim_hash_for_actor_authority_source_v3(
            source_id="authority-session-41",
            principal_id="principal-41",
            user_id=41,
            authentication_context_identity_hash="a" * 64,
            actor_id="django-user:41",
        ),
    }
    values.update(changes)
    return AccountOwnerAssignmentActorAuthoritySourceV3(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountOwnerAssignmentActorAuthoritySourceV3, **changes: object
) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    values: dict[str, object] = {
        field.name: getattr(previous, field.name) for field in fields(previous)
    }
    values.update(
        {
            "source_version": "v2",
            "user_source_version": "v8",
            "user_source_content_hash": "e" * 64,
            "source_recorded_at": previous.recorded_at + timedelta(minutes=1),
            "issued_at": previous.recorded_at + timedelta(minutes=1),
            "recorded_at": previous.recorded_at + timedelta(minutes=1),
            "root_claim_hash": None,
            "supersedes_content_hash": previous.content_hash,
        }
    )
    for field in fields(previous):
        if field.name.endswith("_seal") or field.name in {"identity_hash", "content_hash"}:
            values[field.name] = ""
    values.update(changes)
    return AccountOwnerAssignmentActorAuthoritySourceV3(**values)  # type: ignore[arg-type]


def _record(
    source: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
    return PersistedAccountOwnerAssignmentActorAuthoritySourceV3(
        source=source,
        recorded_by=AccountOwnerAssignmentActorAuthoritySourceV3Recorder(
            service_id="account-authority-attestor-v3"
        ),
    )


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(
            (
                AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
                AccountOwnerAssignmentActorAuthoritySourceV3Model,
            )
        ):
            yield


def _repository() -> DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository:
    return DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(clock=_Clock())


def test_zero_seed_root_first_winner_and_pit_exact_replay() -> None:
    repository = _repository()
    source = _source()
    assert repository.get_current_head(source_id=source.source_id, as_of=NOW) is None

    with repository.atomic():
        stored = repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )
    with repository.atomic():
        replay = repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )

    assert replay == stored
    assert AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.count() == 1
    assert AccountOwnerAssignmentActorAuthoritySourceV3Model.objects.count() == 1
    assert (
        repository.get_winner(
            source_id=source.source_id,
            source_version=source.source_version,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        repository.get_exact_by_hash(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            as_of=NOW + timedelta(hours=12),
        )
        == stored
    )


def test_successor_terminal_is_final_head_without_expiry_fallback() -> None:
    repository = _repository()
    root = _source()
    terminal = _successor(
        root,
        authority_state="revoked",
        is_authenticated=False,
        is_active=False,
    )
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)
        repository.append(
            _record(terminal),
            expected_predecessor_hash=root.content_hash,
            recorded_at=terminal.recorded_at,
        )

    assert repository.get_current_head(
        source_id=root.source_id,
        as_of=terminal.recorded_at - timedelta(microseconds=1),
    ) == _record(root)
    assert repository.get_current_head(
        source_id=root.source_id, as_of=terminal.recorded_at
    ) == _record(terminal)
    assert repository.get_current_head(
        source_id=root.source_id, as_of=NOW + timedelta(hours=12)
    ) == _record(terminal)
    later = _successor(
        terminal,
        source_version="v3",
        source_recorded_at=terminal.recorded_at + timedelta(minutes=1),
        issued_at=terminal.recorded_at + timedelta(minutes=1),
        recorded_at=terminal.recorded_at + timedelta(minutes=1),
    )
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Conflict):
        with repository.atomic():
            repository.append(
                _record(later),
                expected_predecessor_hash=terminal.content_hash,
                recorded_at=later.recorded_at,
            )


def test_cas_and_private_uow_guards_roll_back_empty_anchor() -> None:
    repository = _repository()
    source = _source()
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Conflict):
        repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Conflict):
        with repository.atomic():
            repository.append(_record(source), expected_predecessor_hash="f" * 64, recorded_at=NOW)
    assert AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.count() == 0
    assert AccountOwnerAssignmentActorAuthoritySourceV3Model.objects.count() == 0
    with repository.atomic():
        with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Conflict):
            repository.append(_record(source), expected_predecessor_hash="f" * 64, recorded_at=NOW)
    assert AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.count() == 0
    assert AccountOwnerAssignmentActorAuthoritySourceV3Model.objects.count() == 0
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.create(
            source_id=source.source_id,
            root_claim_hash=source.root_claim_hash,
            created_at=NOW,
        )


def test_full_table_restore_detects_tamper_before_unrelated_read() -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
    table = AccountOwnerAssignmentActorAuthoritySourceV3Model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET "recorded_by_service_id" = %s',  # noqa: S608
            ["substituted-recorder"],
        )
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Corruption):
        repository.get_current_head(source_id="unrelated-source", as_of=NOW)
