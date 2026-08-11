"""ID-only registration for Broker-owned R8 monitoring period receipts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.broker_execution.domain.r8_monitoring_reconciliation import (
    R8BrokerMonitoringPeriodReceipt,
    R8BrokerReconciliationDefinition,
    R8BrokerReconciliationSourceReceipt,
)


class R8BrokerMonitoringRegistryUnavailable(RuntimeError):
    """One exact Broker owner dependency is absent or inconsistent."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return a stable transaction identity."""


class R8BrokerReconciliationDefinitionProvider(_UnitOfWorkBound, Protocol):
    """Provider for complete raw reconciliation definitions."""

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        as_of: datetime,
    ) -> R8BrokerReconciliationDefinition | None:
        """Return the exact PIT definition or explicit absence."""


class R8BrokerReconciliationSourceProvider(_UnitOfWorkBound, Protocol):
    """Provider for independent source authorization receipts."""

    def get_exact(
        self,
        *,
        source_receipt_id: str,
        source_receipt_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R8BrokerReconciliationSourceReceipt | None:
        """Return one exact source receipt or explicit absence."""


class R8BrokerMonitoringPeriodStore(_UnitOfWorkBound, Protocol):
    """Private append-only persistence port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared Broker owner transaction."""

    def append(
        self,
        receipt: R8BrokerMonitoringPeriodReceipt,
        *,
        definition: R8BrokerReconciliationDefinition,
        source_receipt: R8BrokerReconciliationSourceReceipt,
    ) -> R8BrokerMonitoringPeriodReceipt:
        """Append the exact owner graph or return its exact winner."""


class R8BrokerMonitoringPeriodReceiptProvider(_UnitOfWorkBound, Protocol):
    """Exact PIT read port exposed by the Broker owner."""

    def get_exact(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_receipt_hash: str,
        as_of: datetime,
    ) -> R8BrokerMonitoringPeriodReceipt | None:
        """Return one exact live receipt or explicit absence."""

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        portfolio_receipt_id: str,
        portfolio_receipt_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[R8BrokerMonitoringPeriodReceipt, ...] | None:
        """Return the exact ordered complete period set or explicit absence."""


class R8BrokerMonitoringRegistryClock(_UnitOfWorkBound, Protocol):
    """Trusted Broker owner clock."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


@dataclass(frozen=True)
class RegisterR8BrokerMonitoringPeriodCommand:
    """Source identities plus a caller PIT cutoff; never raw facts or ratios."""

    definition_id: str
    definition_version: str
    source_receipt_id: str
    source_receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("definition_id", self.definition_id),
            ("definition_version", self.definition_version),
            ("source_receipt_id", self.source_receipt_id),
            ("source_receipt_version", self.source_receipt_version),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"Broker monitoring command {label} is invalid")
        if (
            type(self.as_of) is not datetime
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
        ):
            raise ValueError("Broker monitoring command as_of must be timezone-aware")


class RegisterR8BrokerMonitoringPeriod:
    """Double-read canonical Broker sources before one trusted-clock append."""

    def __init__(
        self,
        *,
        definition_provider: R8BrokerReconciliationDefinitionProvider,
        source_provider: R8BrokerReconciliationSourceProvider,
        store: R8BrokerMonitoringPeriodStore,
        clock: R8BrokerMonitoringRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._source_provider = source_provider
        self._store = store
        self._clock = clock
        self._participants: tuple[_UnitOfWorkBound, ...] = (
            definition_provider,
            source_provider,
            store,
            clock,
        )
        self._participant_ids = tuple(id(item) for item in self._participants)
        self._expected_uow_key = _shared_uow_key(self._participants)

    def execute(
        self,
        command: RegisterR8BrokerMonitoringPeriodCommand,
    ) -> R8BrokerMonitoringPeriodReceipt:
        """Append only a stable exact graph; every failure remains zero-write."""

        try:
            _validate_command(command)
            self._require_unchanged_participants()
            with self._store.atomic():
                self._require_unchanged_participants()
                now = self._clock.now()
                _require_aware(now, "Broker monitoring registry clock")
                if command.as_of > now:
                    raise R8BrokerMonitoringRegistryUnavailable(
                        "future Broker monitoring registration cutoff"
                    )
                first_definition = self._read_definition(command)
                first_source = self._read_source(command, first_definition)
                self._require_unchanged_participants()
                second_definition = self._read_definition(command)
                second_source = self._read_source(command, second_definition)
                self._require_unchanged_participants()
                if first_definition != second_definition or first_source != second_source:
                    raise R8BrokerMonitoringRegistryUnavailable(
                        "Broker monitoring owner graph changed during reread"
                    )
                receipt = R8BrokerMonitoringPeriodReceipt.record(
                    definition=second_definition,
                    source_receipt=second_source,
                    owner_recorded_at=now,
                )
                result = self._store.append(
                    receipt,
                    definition=second_definition,
                    source_receipt=second_source,
                )
                if type(result) is not R8BrokerMonitoringPeriodReceipt:
                    raise R8BrokerMonitoringRegistryUnavailable(
                        "Broker monitoring store returned an invalid Domain type"
                    )
                R8BrokerMonitoringPeriodReceipt.__post_init__(result)
                if result != receipt:
                    raise R8BrokerMonitoringRegistryUnavailable(
                        "Broker monitoring store substituted the owner receipt"
                    )
                self._require_unchanged_participants()
                return result
        except R8BrokerMonitoringRegistryUnavailable:
            raise
        except Exception as error:
            raise R8BrokerMonitoringRegistryUnavailable(
                "Broker monitoring period registration is unavailable"
            ) from error

    def _read_definition(
        self,
        command: RegisterR8BrokerMonitoringPeriodCommand,
    ) -> R8BrokerReconciliationDefinition:
        value = self._definition_provider.get_exact(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            as_of=command.as_of,
        )
        if type(value) is not R8BrokerReconciliationDefinition:
            raise R8BrokerMonitoringRegistryUnavailable(
                "exact Broker reconciliation definition is unavailable"
            )
        definition = value.validated_copy()
        if (
            definition.definition_id != command.definition_id
            or definition.definition_version != command.definition_version
            or not definition.available_at <= command.as_of < definition.valid_until
        ):
            raise R8BrokerMonitoringRegistryUnavailable(
                "Broker reconciliation definition is substituted, future, or stale"
            )
        return definition

    def _read_source(
        self,
        command: RegisterR8BrokerMonitoringPeriodCommand,
        definition: R8BrokerReconciliationDefinition,
    ) -> R8BrokerReconciliationSourceReceipt:
        value = self._source_provider.get_exact(
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            as_of=command.as_of,
        )
        if type(value) is not R8BrokerReconciliationSourceReceipt:
            raise R8BrokerMonitoringRegistryUnavailable(
                "exact Broker reconciliation source receipt is unavailable"
            )
        source = value.validated_copy()
        if (
            source.source_receipt_id != command.source_receipt_id
            or source.source_receipt_version != command.source_receipt_version
            or source.definition_hash != definition.content_hash
            or not source.available_at <= command.as_of < source.valid_until
            or source.valid_until < definition.valid_until
        ):
            raise R8BrokerMonitoringRegistryUnavailable(
                "Broker reconciliation source is substituted, future, or stale"
            )
        return source

    def _require_unchanged_participants(self) -> None:
        current = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if tuple(id(item) for item in current) != self._participant_ids:
            raise R8BrokerMonitoringRegistryUnavailable(
                "Broker monitoring registry participant was replaced"
            )
        if _shared_uow_key(current) != self._expected_uow_key:
            raise R8BrokerMonitoringRegistryUnavailable(
                "Broker monitoring registry UoW identity changed"
            )


def _validate_command(command: RegisterR8BrokerMonitoringPeriodCommand) -> None:
    if type(command) is not RegisterR8BrokerMonitoringPeriodCommand:
        raise R8BrokerMonitoringRegistryUnavailable(
            "Broker monitoring registration command type is invalid"
        )
    try:
        RegisterR8BrokerMonitoringPeriodCommand.__post_init__(command)
        rebuilt = RegisterR8BrokerMonitoringPeriodCommand(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            as_of=command.as_of,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringRegistryUnavailable(
            "Broker monitoring registration command is invalid"
        ) from error
    if rebuilt != command:
        raise R8BrokerMonitoringRegistryUnavailable(
            "Broker monitoring registration command failed live validation"
        )


def _require_aware(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R8BrokerMonitoringRegistryUnavailable(f"{label} is invalid")


def _shared_uow_key(participants: tuple[_UnitOfWorkBound, ...]) -> str:
    try:
        keys = {item.unit_of_work_key for item in participants}
    except Exception as error:
        raise R8BrokerMonitoringRegistryUnavailable(
            "Broker monitoring registry UoW identity is unavailable"
        ) from error
    if len(keys) != 1:
        raise R8BrokerMonitoringRegistryUnavailable(
            "Broker monitoring registry owners use different units of work"
        )
    key = next(iter(keys))
    if type(key) is not str or not key.strip():
        raise R8BrokerMonitoringRegistryUnavailable(
            "Broker monitoring registry UoW identity is invalid"
        )
    return key


__all__ = [
    "R8BrokerMonitoringPeriodReceiptProvider",
    "R8BrokerMonitoringPeriodStore",
    "R8BrokerMonitoringRegistryClock",
    "R8BrokerMonitoringRegistryUnavailable",
    "R8BrokerReconciliationDefinitionProvider",
    "R8BrokerReconciliationSourceProvider",
    "RegisterR8BrokerMonitoringPeriod",
    "RegisterR8BrokerMonitoringPeriodCommand",
]
