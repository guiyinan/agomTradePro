"""PostgreSQL-only, read-only composition of Account actor authority sources v3.

This module is deliberately a dormant composition boundary.  It reads the
three immutable raw authority ledgers through their existing Application
current readers and returns the consumer-owned DTO bundle used by the actor
authority Application contract.  It does not read Django's mutable user,
session, profile, or request objects and it is not registered in Evidence
runtime composition.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeAlias, cast

from django.db import DatabaseError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Selector,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3Repository,
    GetCurrentAccountAuthenticationContextSourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    ExactActorAuthorityInputBundleProviderV3,
    ExactCurrentAccountRbacAuthorityV3,
    ExactCurrentAccountUserAuthorityV3,
    ExactCurrentActorAuthorityInputBundleV3,
    ExactCurrentAuthenticationContextV3,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3Repository,
    GetCurrentAccountRbacAuthoritySourceV3,
)
from apps.account.application.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3Repository,
    GetCurrentAccountUserAuthoritySourceV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_repository import (
    DjangoAccountRbacAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_user_authority_source_v3_repository import (
    DjangoAccountUserAuthoritySourceV3Repository,
)


class AccountActorAuthorityRawSourceRepositoriesFactoryV3(Protocol):
    """Build all raw-source repositories for one explicit database alias."""

    def build(self, *, using: str) -> AccountActorAuthorityRawSourceRepositoriesV3: ...


@dataclass(frozen=True, slots=True)
class AccountActorAuthorityRawSourceRepositoriesV3:
    """Bind the three raw-source repositories to one declared alias."""

    using: str
    authentication: AccountAuthenticationContextSourceV3Repository
    user: AccountUserAuthoritySourceV3Repository
    rbac: AccountRbacAuthoritySourceV3Repository

    def __post_init__(self) -> None:
        """Reject malformed or cross-alias repository bundles."""

        if type(self.using) is not str or not self.using or self.using.strip() != self.using:
            raise ValueError("repository bundle using must be one exact database alias")
        for name, repository in (
            ("authentication", self.authentication),
            ("user", self.user),
            ("rbac", self.rbac),
        ):
            if repository is None:
                raise TypeError(f"{name} repository is required")


class DjangoAccountActorAuthorityRawSourceRepositoriesFactoryV3:
    """Construct the three existing Django raw-source repositories together."""

    def build(self, *, using: str) -> AccountActorAuthorityRawSourceRepositoriesV3:
        """Return repositories that all target the supplied alias."""

        return AccountActorAuthorityRawSourceRepositoriesV3(
            using=using,
            authentication=DjangoAccountAuthenticationContextSourceV3Repository(using=using),
            user=DjangoAccountUserAuthoritySourceV3Repository(using=using),
            rbac=DjangoAccountRbacAuthoritySourceV3Repository(using=using),
        )


def _connection_for_alias(using: str) -> BaseDatabaseWrapper:
    """Resolve one Django connection without falling back to another alias."""

    try:
        return connections[using]
    except (KeyError, ConnectionDoesNotExist) as error:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            f"authority database alias is unavailable: {using}"
        ) from error


def _atomic_for_alias(using: str) -> AbstractContextManager[None]:
    """Open the provider-owned outer transaction for one alias."""

    return transaction.atomic(using=using)


class DjangoAccountActorAuthorityInputBundleProviderV3(ExactActorAuthorityInputBundleProviderV3):
    """Read one exact-current Account actor bundle from a PostgreSQL snapshot.

    The provider owns one top-level transaction and configures it before any
    ledger query.  Nested caller transactions are rejected because a Django
    savepoint cannot establish the required PostgreSQL snapshot semantics.
    """

    def __init__(
        self,
        *,
        using: str = "default",
        repositories_factory: AccountActorAuthorityRawSourceRepositoriesFactoryV3 | None = None,
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be one exact database alias")
        self._using = using
        self._repositories_factory = (
            repositories_factory or DjangoAccountActorAuthorityRawSourceRepositoriesFactoryV3()
        )

    def get_exact_current(
        self,
        *,
        authentication_context_id: str,
        authentication_context_version: str,
        expected_authentication_context_content_hash: str,
        user_source_id: str,
        user_source_version: str,
        expected_user_source_content_hash: str,
        rbac_source_id: str,
        rbac_source_version: str,
        expected_rbac_source_content_hash: str,
        as_of: datetime,
    ) -> ExactCurrentActorAuthorityInputBundleV3 | None:
        """Return a same-cutoff bundle, or ``None`` when any source is not current."""

        selectors = _selectors(
            authentication_context_id=authentication_context_id,
            authentication_context_version=authentication_context_version,
            expected_authentication_context_content_hash=(
                expected_authentication_context_content_hash
            ),
            user_source_id=user_source_id,
            user_source_version=user_source_version,
            expected_user_source_content_hash=expected_user_source_content_hash,
            rbac_source_id=rbac_source_id,
            rbac_source_version=rbac_source_version,
            expected_rbac_source_content_hash=expected_rbac_source_content_hash,
            as_of=as_of,
        )
        connection = _connection_for_alias(self._using)
        _require_postgresql_outer_connection(connection, self._using)
        try:
            repositories = self._repositories_factory.build(using=self._using)
            _require_repository_bundle(repositories, self._using)
            with _atomic_for_alias(self._using):
                _configure_snapshot(connection)
                context = GetCurrentAccountAuthenticationContextSourceV3(
                    repositories.authentication
                ).execute(selectors[0])
                user = GetCurrentAccountUserAuthoritySourceV3(repositories.user).execute(
                    selectors[1]
                )
                rbac = GetCurrentAccountRbacAuthoritySourceV3(repositories.rbac).execute(
                    selectors[2]
                )
                if context is None or user is None or rbac is None:
                    return None
                return _project_bundle(context, user, rbac, selectors, as_of)
        except AccountActorAuthorityRawSourceV3Unavailable:
            raise
        except AccountActorAuthorityRawSourceV3Conflict as error:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "authority snapshot changed during read"
            ) from error
        except AccountActorAuthorityRawSourceV3Corruption:
            raise
        except DatabaseError as error:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "authority snapshot database read is unavailable"
            ) from error
        except (TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "authority snapshot composition is corrupt"
            ) from error


def _selectors(
    *,
    authentication_context_id: str,
    authentication_context_version: str,
    expected_authentication_context_content_hash: str,
    user_source_id: str,
    user_source_version: str,
    expected_user_source_content_hash: str,
    rbac_source_id: str,
    rbac_source_version: str,
    expected_rbac_source_content_hash: str,
    as_of: datetime,
) -> tuple[
    AccountActorAuthorityRawSourceV3Selector,
    AccountActorAuthorityRawSourceV3Selector,
    AccountActorAuthorityRawSourceV3Selector,
]:
    """Construct the three scalar selectors without accepting raw authority facts."""

    try:
        return (
            AccountActorAuthorityRawSourceV3Selector(
                authentication_context_id,
                authentication_context_version,
                expected_authentication_context_content_hash,
                as_of,
            ),
            AccountActorAuthorityRawSourceV3Selector(
                user_source_id,
                user_source_version,
                expected_user_source_content_hash,
                as_of,
            ),
            AccountActorAuthorityRawSourceV3Selector(
                rbac_source_id,
                rbac_source_version,
                expected_rbac_source_content_hash,
                as_of,
            ),
        )
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority source selector is corrupt"
        ) from error


def _require_postgresql_outer_connection(connection: BaseDatabaseWrapper, using: str) -> None:
    """Require a clean outer PostgreSQL transaction boundary."""

    if getattr(connection, "alias", None) != using:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority connection alias differs from requested alias"
        )
    if connection.vendor != "postgresql":
        raise AccountActorAuthorityRawSourceV3Unavailable("authority bundle requires PostgreSQL")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority bundle requires its own outer transaction"
        )


def _configure_snapshot(connection: BaseDatabaseWrapper) -> None:
    """Make the provider transaction a read-only repeatable-read snapshot."""

    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def _require_repository_bundle(
    repositories: AccountActorAuthorityRawSourceRepositoriesV3, using: str
) -> None:
    """Reject a factory result that is not bound to the requested alias."""

    if type(repositories) is not AccountActorAuthorityRawSourceRepositoriesV3:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority repository bundle type was substituted"
        )
    if repositories.using != using:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority repository bundle alias differs"
        )
    repositories.__post_init__()


def _project_bundle(
    context: AccountAuthenticationContextSourceV3,
    user: AccountUserAuthoritySourceV3,
    rbac: AccountRbacAuthoritySourceV3,
    selectors: tuple[
        AccountActorAuthorityRawSourceV3Selector,
        AccountActorAuthorityRawSourceV3Selector,
        AccountActorAuthorityRawSourceV3Selector,
    ],
    as_of: datetime,
) -> ExactCurrentActorAuthorityInputBundleV3 | None:
    """Validate current source identity and project only existing DTO fields."""

    _require_source(context, selectors[0], AccountAuthenticationContextSourceV3, "context")
    _require_source(user, selectors[1], AccountUserAuthoritySourceV3, "user")
    _require_source(rbac, selectors[2], AccountRbacAuthoritySourceV3, "rbac")
    try:
        context.__post_init__()
        user.__post_init__()
        rbac.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority source projection is corrupt"
        ) from error
    if not (
        context.is_temporally_current_at(as_of)
        and user.is_temporally_current_at(as_of)
        and rbac.is_temporally_current_at(as_of)
    ):
        return None
    if (
        context.user_id != user.user_id
        or user.user_id != rbac.user_id
        or context.actor_id != user.actor_id
        or user.actor_id != rbac.actor_id
    ):
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority source identity drifted across ledgers"
        )
    try:
        return ExactCurrentActorAuthorityInputBundleV3(
            context=ExactCurrentAuthenticationContextV3(
                context_id=context.identity.source_id,
                context_version=context.identity.source_version,
                identity_hash=context.identity_hash,
                content_hash=context.content_hash,
                principal_id=context.principal_id,
                user_id=context.user_id,
                is_authenticated=context.is_authenticated,
                authenticated_at=context.authenticated_at,
                recorded_at=context.clock.recorded_at,
                valid_until=context.clock.valid_until,
            ),
            user=ExactCurrentAccountUserAuthorityV3(
                source_id=user.identity.source_id,
                source_version=user.identity.source_version,
                identity_hash=user.identity_hash,
                content_hash=user.content_hash,
                user_id=user.user_id,
                actor_id=user.actor_id,
                is_active=user.is_active,
                is_staff=user.is_staff,
                is_superuser=user.is_superuser,
                recorded_at=user.clock.recorded_at,
                valid_until=user.clock.valid_until,
            ),
            rbac=ExactCurrentAccountRbacAuthorityV3(
                source_id=rbac.identity.source_id,
                source_version=rbac.identity.source_version,
                identity_hash=rbac.identity_hash,
                content_hash=rbac.content_hash,
                user_id=rbac.user_id,
                rbac_role=rbac.rbac_role,
                recorded_at=rbac.clock.recorded_at,
                valid_until=rbac.clock.valid_until,
            ),
        )
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority DTO projection is corrupt"
        ) from error


def _require_source(
    source: object,
    selector: AccountActorAuthorityRawSourceV3Selector,
    expected_type: type[
        AccountAuthenticationContextSourceV3
        | AccountUserAuthoritySourceV3
        | AccountRbacAuthoritySourceV3
    ],
    label: str,
) -> None:
    """Verify reader output is the exact selected immutable source."""

    if type(source) is not expected_type:
        raise AccountActorAuthorityRawSourceV3Corruption(f"{label} source type was substituted")
    checked = cast(AccountAuthoritySourceV3, source)
    identity = checked.identity
    if (
        identity.source_id,
        identity.source_version,
        checked.content_hash,
    ) != (selector.source_id, selector.source_version, selector.expected_content_hash):
        raise AccountActorAuthorityRawSourceV3Corruption(
            f"{label} source identity or content hash was substituted"
        )


AccountAuthoritySourceV3: TypeAlias = (
    AccountAuthenticationContextSourceV3
    | AccountUserAuthoritySourceV3
    | AccountRbacAuthoritySourceV3
)


__all__ = [
    "AccountActorAuthorityRawSourceRepositoriesFactoryV3",
    "AccountActorAuthorityRawSourceRepositoriesV3",
    "DjangoAccountActorAuthorityInputBundleProviderV3",
    "DjangoAccountActorAuthorityRawSourceRepositoriesFactoryV3",
]
