"""Disposable PostgreSQL support for Account actor-authority capture tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest
from django.db import connections, models

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Recorder,
)
from apps.account.application.account_authentication_context_source_v3 import (
    PersistedAccountAuthenticationContextSourceV3,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.application.account_user_authority_source_v3 import (
    PersistedAccountUserAuthoritySourceV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import AccountRbacAuthoritySourceV3
from apps.account.domain.account_user_authority_source_v3 import AccountUserAuthoritySourceV3
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_repository import (
    DjangoAccountRbacAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_user_authority_source_v3_repository import (
    DjangoAccountUserAuthoritySourceV3Repository,
)
from tests.unit.account.test_account_authentication_context_source_v3 import (
    _source as _authentication_context_source,
)
from tests.unit.account.test_account_rbac_authority_source_v3 import _source as _rbac_source
from tests.unit.account.test_account_user_authority_source_v3 import _source as _user_source

CAPTURE_AT = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
PG_ALIAS = "evid05_authority_test"

_MODELS: tuple[type[models.Model], ...] = (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)


class _DjangoDbBlocker(Protocol):
    def unblock(self) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class Clock:
    """Return the deterministic cutoff used by the disposable capture database."""

    def now(self) -> datetime:
        """Return the fixed aware capture time."""

        return CAPTURE_AT


@pytest.fixture(name="pg_capture_alias")
def pg_capture_alias(django_db_blocker: _DjangoDbBlocker) -> Iterator[str]:
    """Create and tear down the empty, dedicated PostgreSQL capture schema."""

    if os.environ.get("AGOM_EVID05_POSTGRES_TEST") != "1":
        pytest.skip("set AGOM_EVID05_POSTGRES_TEST=1 for the disposable PostgreSQL test")
    if PG_ALIAS in connections.databases:
        raise RuntimeError(f"refusing preexisting database alias: {PG_ALIAS}")

    default_settings = connections["default"].settings_dict
    database_settings = cast(dict[str, object], deepcopy(default_settings))
    database_settings.update(
        {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "evid05_authority_test",
            "USER": "postgres",
            "PASSWORD": "",
            "HOST": "127.0.0.1",
            "PORT": 55435,
            "CONN_MAX_AGE": 0,
            "OPTIONS": {},
        }
    )
    connections.databases[PG_ALIAS] = database_settings  # type: ignore[assignment]
    connection = connections[PG_ALIAS]
    created: list[type[models.Model]] = []
    try:
        with django_db_blocker.unblock():
            existing_tables = tuple(connection.introspection.table_names())
            if existing_tables:
                raise RuntimeError("refusing PostgreSQL database with preexisting tables")
            with connection.schema_editor() as editor:
                for model in _MODELS:
                    editor.create_model(model)
                    created.append(model)
        with django_db_blocker.unblock():
            yield PG_ALIAS
    finally:
        try:
            with django_db_blocker.unblock():
                if created:
                    with connection.schema_editor() as editor:
                        for model in reversed(created):
                            editor.delete_model(model)
        finally:
            connection.close()
            del connections[PG_ALIAS]
            connections.databases.pop(PG_ALIAS, None)


def seed_raw_sources(
    using: str,
) -> tuple[
    AccountAuthenticationContextSourceV3,
    AccountUserAuthoritySourceV3,
    AccountRbacAuthoritySourceV3,
]:
    """Persist the canonical unit-test raw sources into one disposable alias."""

    if type(using) is not str or using != PG_ALIAS:
        raise ValueError("seed_raw_sources requires the dedicated capture alias")
    authentication = _authentication_context_source()
    user = _user_source()
    rbac = _rbac_source()
    recorder = AccountActorAuthorityRawSourceV3Recorder("evid05-authority-test")

    authentication_repository = DjangoAccountAuthenticationContextSourceV3Repository(
        clock=Clock(), using=using
    )
    with authentication_repository.atomic():
        authentication_repository.append(
            PersistedAccountAuthenticationContextSourceV3(authentication, recorder),
            expected_predecessor_hash=None,
            recorded_at=authentication.clock.recorded_at,
        )

    user_repository = DjangoAccountUserAuthoritySourceV3Repository(clock=Clock(), using=using)
    with user_repository.atomic():
        user_repository.append(
            PersistedAccountUserAuthoritySourceV3(user, recorder),
            expected_predecessor_hash=None,
            recorded_at=user.clock.recorded_at,
        )

    rbac_repository = DjangoAccountRbacAuthoritySourceV3Repository(clock=Clock(), using=using)
    with rbac_repository.atomic():
        rbac_repository.append(
            PersistedAccountRbacAuthoritySourceV3(rbac, recorder),
            expected_predecessor_hash=None,
            recorded_at=rbac.clock.recorded_at,
        )
    return authentication, user, rbac
