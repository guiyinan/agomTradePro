"""Capture-only raw authority snapshot guarded by the canonical actor UOW."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    AccountActorAuthorityRawSourceRepositoriesFactoryV3,
    DjangoAccountActorAuthorityInputBundleProviderV3,
)


class DjangoAccountActorAuthorityCaptureBundleProviderV3(
    DjangoAccountActorAuthorityInputBundleProviderV3
):
    """Read raw authority under the append transaction's stable table locks."""

    def __init__(
        self,
        *,
        using: str = "default",
        require_capture_transaction: Callable[[], None],
        repositories_factory: AccountActorAuthorityRawSourceRepositoriesFactoryV3 | None = None,
    ) -> None:
        """Bind capture reads to one repository-owned transaction and alias."""

        super().__init__(using=using, repositories_factory=repositories_factory)
        if not callable(require_capture_transaction):
            raise TypeError("require_capture_transaction must be callable")
        self._require_capture_transaction = require_capture_transaction

    def _snapshot(self, connection: BaseDatabaseWrapper) -> AbstractContextManager[None]:
        """Lock every raw authority table before returning the no-op context."""

        try:
            self._require_capture_transaction()
        except AccountOwnerAssignmentActorAuthoritySourceV3Unavailable as error:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "authority capture transaction is unavailable"
            ) from error
        _require_capture_connection(connection, self._using)
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            row = cursor.fetchone()
            if row is None or len(row) != 1 or str(row[0]).strip().lower() != "read committed":
                raise AccountActorAuthorityRawSourceV3Unavailable(
                    "authority capture transaction must use READ COMMITTED"
                )
            tables = _quoted_raw_authority_tables(connection)
            cursor.execute(f"LOCK TABLE {', '.join(tables)} IN SHARE MODE NOWAIT")
        return nullcontext()


def _require_capture_connection(connection: BaseDatabaseWrapper, using: str) -> None:
    """Require the existing same-alias PostgreSQL write transaction."""

    if getattr(connection, "alias", None) != using:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority capture connection alias differs from requested alias"
        )
    if connection.vendor != "postgresql":
        raise AccountActorAuthorityRawSourceV3Unavailable("authority capture requires PostgreSQL")
    if not connection.in_atomic_block or connection.get_autocommit():
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority capture requires its active transaction"
        )


def _quoted_raw_authority_tables(connection: BaseDatabaseWrapper) -> tuple[str, ...]:
    """Return all six raw authority tables in one deterministic lock order."""

    models: tuple[type[Model], ...] = (
        AccountAuthenticationContextSourceV3AnchorModel,
        AccountAuthenticationContextSourceV3Model,
        AccountUserAuthoritySourceV3AnchorModel,
        AccountUserAuthoritySourceV3Model,
        AccountRbacAuthoritySourceV3AnchorModel,
        AccountRbacAuthoritySourceV3Model,
    )
    tables = tuple(sorted(connection.ops.quote_name(model._meta.db_table) for model in models))
    if len(tables) != 6 or len(set(tables)) != 6:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority capture raw table set is incomplete"
        )
    return tables


__all__ = ["DjangoAccountActorAuthorityCaptureBundleProviderV3"]
