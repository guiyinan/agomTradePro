"""ID-only registration for the Portfolio-owned R8 monitoring calendar."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain._optimization_canonical import require_aware, require_token
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringCalendar,
)
from apps.portfolio.domain.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarDefinition,
    R8MonitoringCalendarSourceReceipt,
)


class R8MonitoringCalendarRegistryUnavailable(RuntimeError):
    """One exact Portfolio calendar owner dependency is unavailable."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one stable shared transaction identity."""


class R8MonitoringCalendarDefinitionProvider(_UnitOfWorkBound, Protocol):
    """Canonical complete-membership definition provider."""

    def get_exact(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        as_of: datetime,
    ) -> R8MonitoringCalendarDefinition | None:
        """Return an exact complete definition or explicit absence."""


class R8MonitoringCalendarSourceProvider(_UnitOfWorkBound, Protocol):
    """Canonical Portfolio source-authorization provider."""

    def get_exact(
        self,
        *,
        source_receipt_id: str,
        source_receipt_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R8MonitoringCalendarSourceReceipt | None:
        """Return an exact source receipt or explicit absence."""


class R8MonitoringCalendarStore(_UnitOfWorkBound, Protocol):
    """Private append-only calendar persistence port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared Portfolio owner transaction."""

    def append(
        self,
        calendar: GovernedOptimizationMonitoringCalendar,
        *,
        definition: R8MonitoringCalendarDefinition,
        source_receipt: R8MonitoringCalendarSourceReceipt,
    ) -> GovernedOptimizationMonitoringCalendar:
        """Append one exact source-backed owner calendar."""


class R8MonitoringCalendarRegistryClock(_UnitOfWorkBound, Protocol):
    """Trusted server clock bound to the owner transaction."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


@dataclass(frozen=True)
class RegisterR8MonitoringCalendarCommand:
    """Calendar/source identity plus PIT cutoff; never accepts membership."""

    calendar_id: str
    calendar_version: str
    source_receipt_id: str
    source_receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("calendar_id", self.calendar_id),
            ("calendar_version", self.calendar_version),
            ("source_receipt_id", self.source_receipt_id),
            ("source_receipt_version", self.source_receipt_version),
        ):
            require_token(value, f"R8 calendar registration {label}")
        require_aware(self.as_of, "R8 calendar registration as_of")


class RegisterR8MonitoringCalendar:
    """Double-read canonical membership and append a server-clocked calendar."""

    def __init__(
        self,
        *,
        definition_provider: R8MonitoringCalendarDefinitionProvider,
        source_provider: R8MonitoringCalendarSourceProvider,
        store: R8MonitoringCalendarStore,
        clock: R8MonitoringCalendarRegistryClock,
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
        command: RegisterR8MonitoringCalendarCommand,
    ) -> GovernedOptimizationMonitoringCalendar:
        """Append only one stable exact owner graph, otherwise write nothing."""

        try:
            _validate_command(command)
            self._require_unchanged_participants()
            with self._store.atomic():
                self._require_unchanged_participants()
                now = self._clock.now()
                require_aware(now, "R8 calendar registry clock")
                if command.as_of > now:
                    raise R8MonitoringCalendarRegistryUnavailable(
                        "future R8 calendar registration cutoff"
                    )
                first_definition = self._read_definition(command)
                first_source = self._read_source(command, first_definition)
                self._require_unchanged_participants()
                second_definition = self._read_definition(command)
                second_source = self._read_source(command, second_definition)
                self._require_unchanged_participants()
                if first_definition != second_definition or first_source != second_source:
                    raise R8MonitoringCalendarRegistryUnavailable(
                        "R8 calendar owner graph changed during reread"
                    )
                calendar = second_definition.build(owner_recorded_at=now)
                result = self._store.append(
                    calendar,
                    definition=second_definition,
                    source_receipt=second_source,
                )
                if type(result) is not GovernedOptimizationMonitoringCalendar:
                    raise R8MonitoringCalendarRegistryUnavailable(
                        "R8 calendar store returned an invalid Domain type"
                    )
                GovernedOptimizationMonitoringCalendar.__post_init__(result)
                if result != calendar:
                    raise R8MonitoringCalendarRegistryUnavailable(
                        "R8 calendar store substituted the owner record"
                    )
                self._require_unchanged_participants()
                return result
        except R8MonitoringCalendarRegistryUnavailable:
            raise
        except Exception as error:
            raise R8MonitoringCalendarRegistryUnavailable(
                "R8 monitoring calendar registration is unavailable"
            ) from error

    def _read_definition(
        self,
        command: RegisterR8MonitoringCalendarCommand,
    ) -> R8MonitoringCalendarDefinition:
        value = self._definition_provider.get_exact(
            calendar_id=command.calendar_id,
            calendar_version=command.calendar_version,
            as_of=command.as_of,
        )
        if type(value) is not R8MonitoringCalendarDefinition:
            raise R8MonitoringCalendarRegistryUnavailable(
                "exact R8 calendar definition is unavailable"
            )
        definition = value.validated_copy()
        if (
            definition.calendar_id != command.calendar_id
            or definition.calendar_version != command.calendar_version
            or not definition.available_at <= command.as_of < definition.valid_until
        ):
            raise R8MonitoringCalendarRegistryUnavailable(
                "R8 calendar definition is substituted, future, or stale"
            )
        return definition

    def _read_source(
        self,
        command: RegisterR8MonitoringCalendarCommand,
        definition: R8MonitoringCalendarDefinition,
    ) -> R8MonitoringCalendarSourceReceipt:
        value = self._source_provider.get_exact(
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            as_of=command.as_of,
        )
        if type(value) is not R8MonitoringCalendarSourceReceipt:
            raise R8MonitoringCalendarRegistryUnavailable(
                "exact R8 calendar source receipt is unavailable"
            )
        source = value.validated_copy()
        if (
            source.source_receipt_id != command.source_receipt_id
            or source.source_receipt_version != command.source_receipt_version
            or source.definition_hash != definition.content_hash
            or not source.available_at <= command.as_of < source.valid_until
            or source.valid_until < definition.valid_until
        ):
            raise R8MonitoringCalendarRegistryUnavailable(
                "R8 calendar source receipt is substituted, future, or stale"
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
            raise R8MonitoringCalendarRegistryUnavailable(
                "R8 calendar registry participant was replaced"
            )
        if _shared_uow_key(current) != self._expected_uow_key:
            raise R8MonitoringCalendarRegistryUnavailable(
                "R8 calendar registry UoW identity changed"
            )


def _validate_command(command: RegisterR8MonitoringCalendarCommand) -> None:
    if type(command) is not RegisterR8MonitoringCalendarCommand:
        raise R8MonitoringCalendarRegistryUnavailable(
            "R8 calendar registration command type is invalid"
        )
    try:
        RegisterR8MonitoringCalendarCommand.__post_init__(command)
        rebuilt = RegisterR8MonitoringCalendarCommand(
            calendar_id=command.calendar_id,
            calendar_version=command.calendar_version,
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            as_of=command.as_of,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringCalendarRegistryUnavailable(
            "R8 calendar registration command is invalid"
        ) from error
    if rebuilt != command:
        raise R8MonitoringCalendarRegistryUnavailable(
            "R8 calendar registration command failed live validation"
        )


def _shared_uow_key(participants: tuple[_UnitOfWorkBound, ...]) -> str:
    try:
        keys = {item.unit_of_work_key for item in participants}
    except Exception as error:
        raise R8MonitoringCalendarRegistryUnavailable(
            "R8 calendar registry UoW identity is unavailable"
        ) from error
    if len(keys) != 1:
        raise R8MonitoringCalendarRegistryUnavailable(
            "R8 calendar registry owners use different units of work"
        )
    key = next(iter(keys))
    if type(key) is not str or not key.strip():
        raise R8MonitoringCalendarRegistryUnavailable(
            "R8 calendar registry UoW identity is invalid"
        )
    return key


__all__ = [
    "R8MonitoringCalendarDefinitionProvider",
    "R8MonitoringCalendarRegistryClock",
    "R8MonitoringCalendarRegistryUnavailable",
    "R8MonitoringCalendarSourceProvider",
    "R8MonitoringCalendarStore",
    "RegisterR8MonitoringCalendar",
    "RegisterR8MonitoringCalendarCommand",
]
