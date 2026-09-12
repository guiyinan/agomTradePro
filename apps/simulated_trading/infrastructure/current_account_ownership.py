"""Same-alias live ownership lookup, independent of expired creation snapshots."""

from django.db import DatabaseError, connections
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnership,
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


class DjangoCurrentAccountOwnershipReader:
    """Hold the actual account row until the surrounding transaction completes."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind one explicit alias without querying or granting authority."""
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias used for the source query and row lock."""
        return self._using

    def read_locked(self, *, row_pk: int) -> CurrentAccountOwnership | None:
        """Read the live row in READ COMMITTED with a nonblocking write lock.

        A missing, inactive or ownerless row is never replaced by an older
        source ledger. Inactive and ownerless observations preserve the actual
        facts so the consuming authorization use case can reject them.
        """
        if type(row_pk) is not int or row_pk <= 0:
            raise ValueError("row_pk must be an exact positive integer")
        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise CurrentAccountOwnershipUnavailable(
                "ownership database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql" or not connection.in_atomic_block:
            raise CurrentAccountOwnershipUnavailable(
                "ownership read requires a PostgreSQL transaction"
            )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                isolation = cursor.fetchone()
            if isolation != ("read committed",):
                raise CurrentAccountOwnershipUnavailable("ownership read requires READ COMMITTED")
            row = (
                SimulatedAccountModel._default_manager.using(self._using)
                .select_for_update(nowait=True)
                .only("id", "user_id", "account_type", "is_active", "created_at", "updated_at")
                .filter(pk=row_pk)
                .first()
            )
            if row is None:
                return None
            return CurrentAccountOwnership(
                row_pk=row_pk,
                user_id=row.user_id,
                account_type=AccountType(row.account_type),
                is_active=row.is_active,
                row_created_at=row.created_at,
                row_updated_at=row.updated_at,
                observed_at=timezone.now(),
            )
        except (DatabaseError, ValueError, TypeError) as error:
            raise CurrentAccountOwnershipUnavailable(
                "live ownership source is unavailable or invalid"
            ) from error
