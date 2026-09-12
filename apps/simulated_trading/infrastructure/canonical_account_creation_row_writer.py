"""Django writer for one new SimulatedAccount physical row."""

from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowClock,
    CanonicalAccountCreationRowCommand,
    CanonicalAccountCreationRowConflict,
    CanonicalAccountCreationRowCorruption,
    CanonicalAccountCreationRowInvalid,
    CanonicalAccountCreationRowResult,
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountPhysicalRowMutation,
)
from apps.simulated_trading.infrastructure.account_repository import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


class DjangoCanonicalAccountCreationRowClock:
    """Django server clock used to timestamp the physical-row mutation."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoCanonicalAccountCreationRowWriter:
    """Insert one new account row under a caller-owned same-alias transaction."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str,
        clock: CanonicalAccountCreationRowClock | None = None,
    ) -> None:
        self._using = _require_database_alias(using)
        self._clock = clock or DjangoCanonicalAccountCreationRowClock()

    def execute(
        self, command: CanonicalAccountCreationRowCommand
    ) -> CanonicalAccountCreationRowResult:
        """Insert and refresh one new account, returning its exact physical mutation."""

        if type(command) is not CanonicalAccountCreationRowCommand:
            raise CanonicalAccountCreationRowInvalid(
                "command must be an exact CanonicalAccountCreationRowCommand"
            )
        command.__post_init__()
        connection = self._connection()
        if not connection.in_atomic_block:
            raise CanonicalAccountCreationRowUnavailable(
                "account creation row requires a caller-owned transaction"
            )
        try:
            with transaction.atomic(using=self._using):
                return self._execute_in_savepoint(command)
        except (
            CanonicalAccountCreationRowInvalid,
            CanonicalAccountCreationRowUnavailable,
            CanonicalAccountCreationRowConflict,
            CanonicalAccountCreationRowCorruption,
        ):
            raise
        except IntegrityError as error:
            raise CanonicalAccountCreationRowConflict(
                "account creation row insert conflicted"
            ) from error
        except ObjectDoesNotExist as error:
            raise CanonicalAccountCreationRowCorruption(
                "account creation row disappeared during refresh"
            ) from error
        except DatabaseError as error:
            raise CanonicalAccountCreationRowUnavailable(
                "account creation row database operation is unavailable"
            ) from error

    def _execute_in_savepoint(
        self, command: CanonicalAccountCreationRowCommand
    ) -> CanonicalAccountCreationRowResult:
        user_model = get_user_model()
        try:
            user = (
                user_model._default_manager.using(self._using)
                .select_for_update()
                .filter(pk=command.requester_user_id)
                .first()
            )
        except DatabaseError as error:
            raise CanonicalAccountCreationRowUnavailable(
                "requester user cannot be read on the requested alias"
            ) from error
        if (
            user is None
            or type(getattr(user, "pk", None)) is not int
            or user.pk != command.requester_user_id
            or type(getattr(user, "is_active", None)) is not bool
            or user.is_active is not True
        ):
            raise CanonicalAccountCreationRowUnavailable(
                "requester user is unavailable on the requested alias"
            )

        try:
            model = SimulatedAccountMapper.to_model(command.account)
        except (AttributeError, OverflowError, TypeError, ValueError) as error:
            raise CanonicalAccountCreationRowCorruption(
                "account cannot be mapped to a new physical row"
            ) from error
        model.pk = None
        model.user_id = command.requester_user_id
        try:
            model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            raise CanonicalAccountCreationRowConflict(
                "account creation row insert conflicted"
            ) from error
        except DatabaseError as error:
            raise CanonicalAccountCreationRowUnavailable(
                "account creation row cannot be inserted"
            ) from error

        try:
            model.refresh_from_db(using=self._using)
        except ObjectDoesNotExist as error:
            raise CanonicalAccountCreationRowCorruption(
                "new account row disappeared before refresh"
            ) from error
        except DatabaseError as error:
            raise CanonicalAccountCreationRowUnavailable(
                "new account row cannot be refreshed"
            ) from error

        row_pk, row_user_id, account_type, is_active, created_at, updated_at = (
            self._checked_persisted_fields(model, command)
        )
        observed_at = self._server_time()
        try:
            mutation = SimulatedAccountPhysicalRowMutation(
                observation_id=command.observation_id,
                mutation_version=command.mutation_version,
                row_pk=row_pk,
                row_user_id=row_user_id,
                raw_account_type=account_type,
                is_active=is_active,
                row_created_at=created_at,
                row_updated_at=updated_at,
                observed_at=observed_at,
            )
        except (TypeError, ValueError) as error:
            raise CanonicalAccountCreationRowCorruption(
                "persisted account facts cannot form a physical-row mutation"
            ) from error

        try:
            account = SimulatedAccountMapper.to_entity(model)
        except (AttributeError, TypeError, ValueError) as error:
            raise CanonicalAccountCreationRowCorruption(
                "persisted account cannot be restored as a Domain entity"
            ) from error
        try:
            return CanonicalAccountCreationRowResult(account=account, mutation=mutation)
        except (
            CanonicalAccountCreationRowInvalid,
            TypeError,
            ValueError,
            CanonicalAccountCreationRowCorruption,
        ) as error:
            raise CanonicalAccountCreationRowCorruption(
                "persisted account and mutation do not correspond"
            ) from error

    def _connection(self) -> BaseDatabaseWrapper:
        try:
            return connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise CanonicalAccountCreationRowUnavailable(
                "account creation database alias is unavailable"
            ) from error

    def _server_time(self) -> datetime:
        try:
            value = self._clock.now()
        except Exception as error:
            raise CanonicalAccountCreationRowCorruption(
                "account creation server clock is unavailable"
            ) from error
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalAccountCreationRowCorruption(
                "account creation server clock must be timezone-aware"
            )
        return value

    @staticmethod
    def _checked_persisted_fields(
        model: SimulatedAccountModel,
        command: CanonicalAccountCreationRowCommand,
    ) -> tuple[int, int, str, bool, datetime, datetime]:
        row_pk = model.pk
        row_user_id = model.user_id
        account_type = model.account_type
        is_active = model.is_active
        created_at = model.created_at
        updated_at = model.updated_at
        if type(row_pk) is not int or row_pk <= 0:
            raise CanonicalAccountCreationRowCorruption("refreshed account primary key is invalid")
        if type(row_user_id) is not int or row_user_id != command.requester_user_id:
            raise CanonicalAccountCreationRowCorruption(
                "refreshed account user does not match requester"
            )
        if type(account_type) is not str or account_type != command.account.account_type.value:
            raise CanonicalAccountCreationRowCorruption(
                "refreshed account type differs from requested account"
            )
        if type(is_active) is not bool or is_active != command.account.is_active:
            raise CanonicalAccountCreationRowCorruption(
                "refreshed account active state differs from requested account"
            )
        for field_name, value in (
            ("created_at", created_at),
            ("updated_at", updated_at),
        ):
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise CanonicalAccountCreationRowCorruption(
                    f"refreshed account {field_name} must be timezone-aware"
                )
        return row_pk, row_user_id, account_type, is_active, created_at, updated_at


def _require_database_alias(using: object) -> str:
    """Validate one exact non-whitespace database alias before any lookup."""

    if (
        type(using) is not str
        or not using
        or using.strip() != using
        or len(using) > 192
        or any(character.isspace() for character in using)
    ):
        raise CanonicalAccountCreationRowInvalid("using must be an exact database alias")
    return using


__all__ = [
    "DjangoCanonicalAccountCreationRowClock",
    "DjangoCanonicalAccountCreationRowWriter",
]
