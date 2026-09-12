"""Same-alias physical reads for creation name checks and permanent replay."""

from django.db import DatabaseError, connections
from django.utils.connection import ConnectionDoesNotExist

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowCorruption,
    CanonicalAccountCreationRowInvalid,
    CanonicalAccountCreationRowUnavailable,
    _validate_account,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.infrastructure.account_repository import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


class DjangoCanonicalAccountCreationReader:
    """Read exact current owner rows while the caller holds the user's lock."""

    def __init__(self, *, using: str) -> None:
        """Bind one explicit alias without performing any I/O."""

        if type(using) is not str or not using or any(character.isspace() for character in using):
            raise CanonicalAccountCreationRowInvalid("using must be an explicit database alias")
        self._using = using

    def _require_transaction(self, user_id: int) -> None:
        if type(user_id) is not int or user_id <= 0:
            raise CanonicalAccountCreationRowInvalid("user_id must be a positive integer")
        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise CanonicalAccountCreationRowUnavailable(
                "creation database is unavailable"
            ) from error
        if connection.vendor != "postgresql" or not connection.in_atomic_block:
            raise CanonicalAccountCreationRowUnavailable(
                "creation reads require a PostgreSQL transaction"
            )
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise CanonicalAccountCreationRowUnavailable(
                    "creation reads require READ COMMITTED"
                )

    def name_exists(self, *, user_id: int, account_name: str) -> bool:
        """Preserve the existing per-owner name rule, including inactive rows."""

        if (
            type(account_name) is not str
            or not account_name
            or len(account_name) > 100
            or account_name.strip() != account_name
        ):
            raise CanonicalAccountCreationRowInvalid("account_name is invalid")
        try:
            self._require_transaction(user_id)
            return (
                SimulatedAccountModel.objects.using(self._using)
                .filter(user_id=user_id, account_name=account_name)
                .exists()
            )
        except DatabaseError as error:
            raise CanonicalAccountCreationRowUnavailable("creation name lookup failed") from error

    def read_owned(
        self, *, user_id: int, account_id: int, account_type: AccountType
    ) -> SimulatedAccount | None:
        """Lock current physical ownership without falling back to historic rows."""

        if type(account_id) is not int or account_id <= 0 or type(account_type) is not AccountType:
            raise CanonicalAccountCreationRowInvalid("account selector is invalid")
        try:
            self._require_transaction(user_id)
            row = (
                SimulatedAccountModel.objects.using(self._using)
                .select_for_update()
                .filter(
                    pk=account_id, user_id=user_id, account_type=account_type.value, is_active=True
                )
                .first()
            )
            if row is None:
                return None
            return _validate_account(SimulatedAccountMapper.to_entity(row), require_unsaved=False)
        except DatabaseError as error:
            raise CanonicalAccountCreationRowUnavailable(
                "creation account lookup failed"
            ) from error
        except (CanonicalAccountCreationRowInvalid, ValueError, TypeError, OverflowError) as error:
            raise CanonicalAccountCreationRowCorruption(
                "creation account row is invalid"
            ) from error


__all__ = ["DjangoCanonicalAccountCreationReader"]
