"""Locked current-head reads for simulated corporate-action service grants."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from django.db import DatabaseError, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantCurrent,
    SimulatedCorporateActionWriteGrantSelector,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
    SimulatedCorporateActionWriteGrantRevocationModel,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_seal import (
    SimulatedCorporateActionWriteGrantSeal,
)


def _require_transaction(*, using: str) -> BaseDatabaseWrapper:
    """Return one active PostgreSQL READ COMMITTED connection or fail closed."""

    if type(using) is not str or not using or using.strip() != using:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant database alias is invalid"
        )
    try:
        connection = connections[using]
        if (
            connection.vendor != "postgresql"
            or not connection.in_atomic_block
            or connection.get_autocommit()
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "current simulated write grant requires an active PostgreSQL transaction"
            )
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "current simulated write grant requires READ COMMITTED"
                )
    except (DatabaseError, ConnectionDoesNotExist) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "current simulated write grant transaction is unavailable"
        ) from error
    return connection


def _lock_grant_tables(connection: BaseDatabaseWrapper) -> None:
    """Fence grant and revocation appends using only owned, quoted table names."""

    table_names = tuple(
        sorted(
            {
                SimulatedCorporateActionWriteGrantModel._meta.db_table,
                SimulatedCorporateActionWriteGrantRevocationModel._meta.db_table,
            }
        )
    )
    try:
        with connection.cursor() as cursor:
            for table_name in table_names:
                quoted_table = connection.ops.quote_name(table_name)
                cursor.execute(f"LOCK TABLE {quoted_table} IN SHARE MODE NOWAIT")
    except (DatabaseError, ConnectionDoesNotExist) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant ledger is changing or unavailable"
        ) from error


def _read_exact_current_grant(
    *,
    selector: SimulatedCorporateActionWriteGrantSelector,
    repository: DjangoSimulatedCorporateActionWriteGrantRepository,
    seal: SimulatedCorporateActionWriteGrantSeal,
    as_of: datetime,
    required_capability: SimulatedCorporateActionWriteCapability,
) -> SimulatedCorporateActionWriteGrant:
    """Require the unique active scope head, exact selector, and current server MAC."""

    heads = repository.get_current_for_scope(
        selector.binding.account_namespace,
        selector.binding.account_id,
        as_of=as_of,
    )
    if (
        type(heads) is not tuple
        or len(heads) != 1
        or type(heads[0]) is not SimulatedCorporateActionWriteGrant
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant scope has no unique active head"
        )
    grant = heads[0]
    current = repository.get_current_grant(selector=selector, as_of=as_of)
    if type(current) is not SimulatedCorporateActionWriteGrantCurrent:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant is not the exact current head"
        )
    try:
        current.__post_init__()
        grant.__post_init__()
        selector.__post_init__()
        is_active = current.is_active_at(as_of)
        supports_required_capability = grant.supports_capability(required_capability)
    except (TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant current record is invalid"
        ) from error
    if (
        current.revocation is not None
        or current.grant != grant
        or current.selector != selector
        or grant.selector != selector
        or grant.binding != selector.binding
        or (
            grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
            and grant.permission != SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
        )
        or (
            grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
            and grant.permission != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
        )
        or grant.schema
        not in {
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        }
        or grant.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        or not supports_required_capability
        or not is_active
        or not seal.verify(grant)
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant is revoked, expired, unsigned, or out of scope"
        )
    return grant


@contextmanager
def locked_current_simulated_corporate_action_write_grant(
    *,
    selector: SimulatedCorporateActionWriteGrantSelector,
    using: str,
    required_capability: SimulatedCorporateActionWriteCapability = (
        SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE
    ),
) -> Iterator[SimulatedCorporateActionWriteGrant]:
    """Hold the exact unrevoked grant head stable inside its caller's write UOW.

    This composition never searches historical records. It locks both append-only
    grant ledgers before reading scope state, verifies the current server MAC and
    rechecks the same finite current grant before yielding back to the caller.
    Assessment reads require the explicit V2 assessment capability. The caller
    must separately qualify physical ownership, current policy and tax inputs.
    """

    if type(required_capability) is not SimulatedCorporateActionWriteCapability or (
        required_capability
        not in {
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        }
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "current simulated write grant reader does not support the requested capability"
        )
    if type(selector) is not SimulatedCorporateActionWriteGrantSelector:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant selector type is invalid"
        )
    try:
        selector.__post_init__()
    except (TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant selector is invalid"
        ) from error
    connection = _require_transaction(using=using)
    _lock_grant_tables(connection)
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(using=using)
    seal = SimulatedCorporateActionWriteGrantSeal()
    grant = _read_exact_current_grant(
        selector=selector,
        repository=repository,
        seal=seal,
        as_of=timezone.now(),
        required_capability=required_capability,
    )
    yield grant
    current = _read_exact_current_grant(
        selector=selector,
        repository=repository,
        seal=seal,
        as_of=timezone.now(),
        required_capability=required_capability,
    )
    if current != grant:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated write grant changed before transaction exit"
        )


__all__ = ["locked_current_simulated_corporate_action_write_grant"]
