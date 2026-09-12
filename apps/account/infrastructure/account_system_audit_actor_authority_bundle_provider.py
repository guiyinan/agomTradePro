"""System Audit actor-authority reads inside its same-alias write transaction."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext

from django.db import DatabaseError
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
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
    DjangoAccountActorAuthorityInputBundleProviderV3,
)


class DjangoAccountSystemAuditActorAuthorityBundleProviderV3(
    DjangoAccountActorAuthorityInputBundleProviderV3
):
    """Read standalone or lock raw authority inside System Audit's write UOW."""

    def _snapshot(self, connection: BaseDatabaseWrapper) -> AbstractContextManager[None]:
        """Use the standalone snapshot or stabilize the active READ COMMITTED UOW."""

        if not connection.in_atomic_block and connection.get_autocommit():
            return super()._snapshot(connection)
        _require_system_audit_connection(connection, self._using)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone() != ("read committed",):
                    raise AccountActorAuthorityRawSourceV3Unavailable(
                        "system audit authority transaction must use READ COMMITTED"
                    )
                tables = _quoted_raw_authority_tables(connection)
                cursor.execute(f"LOCK TABLE {', '.join(tables)} IN SHARE MODE NOWAIT")
        except AccountActorAuthorityRawSourceV3Unavailable:
            raise
        except DatabaseError as error:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "system audit authority source lock is unavailable"
            ) from error
        return nullcontext()


def _require_system_audit_connection(
    connection: BaseDatabaseWrapper,
    using: str,
) -> None:
    """Require an active same-alias PostgreSQL write transaction."""

    if getattr(connection, "alias", None) != using:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "system audit authority connection alias differs from requested alias"
        )
    if connection.vendor != "postgresql":
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "system audit authority transaction requires PostgreSQL"
        )
    if not connection.in_atomic_block or connection.get_autocommit():
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "system audit authority transaction is unavailable"
        )


def _quoted_raw_authority_tables(connection: BaseDatabaseWrapper) -> tuple[str, ...]:
    """Return all raw authority tables in one deterministic lock order."""

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
            "system audit authority raw table set is incomplete"
        )
    return tables


__all__ = ["DjangoAccountSystemAuditActorAuthorityBundleProviderV3"]
