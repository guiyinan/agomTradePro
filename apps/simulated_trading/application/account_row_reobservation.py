"""Observe a previously recorded account row without mutating the physical account."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnership,
    CurrentAccountOwnershipReader,
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountPhysicalRowMutation,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)


@dataclass(frozen=True, slots=True)
class ReobserveExistingAccountRowCommand:
    """Server-selected identities from a verified permanent creation binding.

    These expected facts are consistency constraints, not authentication proof.
    The caller must authenticate and retain the outer same-alias transaction.
    A new observation version records a new read, never another account creation.
    """

    observation_id: str
    observation_version: str
    row_pk: int
    expected_user_id: int
    expected_account_type: AccountType
    expected_created_at: datetime
    minimum_updated_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed selectors and historical source facts at the entry point."""
        for token_value in (self.observation_id, self.observation_version):
            if (
                type(token_value) is not str
                or not token_value
                or len(token_value) > 192
                or any(c.isspace() for c in token_value)
            ):
                raise ValueError("observation identity must be a bounded canonical token")
        for identity_value in (self.row_pk, self.expected_user_id):
            if type(identity_value) is not int or identity_value <= 0:
                raise ValueError("physical identity must be an exact positive integer")
        if type(self.expected_account_type) is not AccountType:
            raise TypeError("expected account type must be exact AccountType")
        for source_time in (self.expected_created_at, self.minimum_updated_at):
            if (
                type(source_time) is not datetime
                or source_time.tzinfo is None
                or source_time.utcoffset() is None
            ):
                raise ValueError("expected source clocks must be aware")
        if self.minimum_updated_at < self.expected_created_at:
            raise ValueError("expected source clocks are out of order")


class ExistingAccountRawObservationWriter(Protocol):
    """Append a present successor only when an actual raw chain already exists."""

    @property
    def database_alias(self) -> str:
        """Return the alias retaining the raw append transaction."""
        ...

    def record_update(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Record current source facts without changing the physical database row."""
        ...


class ReobserveExistingAccountRow:
    """Read, record, and recheck actual row identity inside the caller's transaction."""

    def __init__(
        self, *, reader: CurrentAccountOwnershipReader, writer: ExistingAccountRawObservationWriter
    ) -> None:
        """Require both injected ports to retain exactly the same database transaction."""
        alias = reader.database_alias
        if (
            type(alias) is not str
            or not alias
            or any(c.isspace() for c in alias)
            or writer.database_alias != alias
        ):
            raise ValueError("row reader and raw writer must share one explicit alias")
        self._reader = reader
        self._writer = writer

    def execute(
        self, command: ReobserveExistingAccountRowCommand
    ) -> SimulatedAccountRawObservation:
        """Record a fresh observation of the same owned row, never revive an old seal."""
        if type(command) is not ReobserveExistingAccountRowCommand:
            raise TypeError("command must be exact ReobserveExistingAccountRowCommand")
        command.__post_init__()
        first = self._read(command)
        mutation = SimulatedAccountPhysicalRowMutation(
            observation_id=command.observation_id,
            mutation_version=command.observation_version,
            row_pk=first.row_pk,
            row_user_id=first.user_id,
            raw_account_type=first.account_type.value,
            is_active=first.is_active,
            row_created_at=first.row_created_at,
            row_updated_at=first.row_updated_at,
            observed_at=first.observed_at,
        )
        result = self._writer.record_update(mutation)
        if type(result) is not SimulatedAccountRawObservation:
            raise CurrentAccountOwnershipUnavailable("raw writer returned a substituted type")
        try:
            result.__post_init__()
        except (TypeError, ValueError) as error:
            raise CurrentAccountOwnershipUnavailable("raw observation is invalid") from error
        if (
            result.observation_id != command.observation_id
            or result.observation_version != command.observation_version
            or result.row_pk != first.row_pk
            or result.row_user_id != first.user_id
            or result.raw_account_type != first.account_type.value
            or result.is_active is not True
            or result.is_present is not True
            or result.is_tombstone is not False
            or result.row_created_at != first.row_created_at
            or result.row_updated_at != first.row_updated_at
            or result.observed_at != first.observed_at
            or result.supersedes_content_hash is None
        ):
            raise CurrentAccountOwnershipUnavailable("raw writer changed the observed identity")
        final = self._read(command)
        if (
            final.observed_at < first.observed_at
            or replace(first, observed_at=final.observed_at) != final
            or final.observed_at >= result.valid_until
        ):
            raise CurrentAccountOwnershipUnavailable(
                "account changed or observation expired during capture"
            )
        return result

    def _read(self, command: ReobserveExistingAccountRowCommand) -> CurrentAccountOwnership:
        """Require the live row to match the permanent creation identity."""
        row = self._reader.read_locked(row_pk=command.row_pk)
        if type(row) is not CurrentAccountOwnership:
            raise CurrentAccountOwnershipUnavailable("current physical account is unavailable")
        row.__post_init__()
        if (
            row.row_pk != command.row_pk
            or row.user_id != command.expected_user_id
            or row.account_type != command.expected_account_type
            or row.is_active is not True
            or row.row_created_at != command.expected_created_at
            or row.row_updated_at < command.minimum_updated_at
        ):
            raise CurrentAccountOwnershipUnavailable(
                "physical account differs from permanent creation"
            )
        return row
