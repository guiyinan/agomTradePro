"""ID-only registration for canonical R5 monitoring policy and calendar owners."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r5_monitoring_owner_registry import (
    R5MonitoringCalendarDefinition,
    R5MonitoringOwnerRecordKind,
    R5MonitoringOwnerSourceReceipt,
    R5MonitoringPolicyDefinition,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringCalendar,
    R5MonitoringPolicy,
    _require_aware,
    _require_token,
)


class R5MonitoringOwnerRegistryUnavailable(RuntimeError):
    """A trusted R5 owner definition, source, clock, or UoW is unavailable."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""


class R5MonitoringPolicyDefinitionProvider(_UowBound, Protocol):
    """Independent Research policy-definition source."""

    def get_exact(
        self,
        *,
        owner_id: str,
        owner_version: str,
        as_of: datetime,
    ) -> R5MonitoringPolicyDefinition | None:
        """Return one exact policy definition by identity and cutoff."""


class R5MonitoringCalendarDefinitionProvider(_UowBound, Protocol):
    """Independent Research calendar-definition source."""

    def get_exact(
        self,
        *,
        owner_id: str,
        owner_version: str,
        as_of: datetime,
    ) -> R5MonitoringCalendarDefinition | None:
        """Return one exact calendar definition by identity and cutoff."""


class R5MonitoringOwnerSourceProvider(_UowBound, Protocol):
    """Independent source-receipt reader for either owner kind."""

    def get_exact(
        self,
        *,
        record_kind: R5MonitoringOwnerRecordKind,
        owner_id: str,
        owner_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R5MonitoringOwnerSourceReceipt | None:
        """Return one source receipt bound to the exact definition."""


class R5MonitoringOwnerRegistryStore(_UowBound, Protocol):
    """Private append capability retained outside public composition."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared owner transaction."""

    def append_policy(
        self,
        *,
        definition: R5MonitoringPolicyDefinition,
        source: R5MonitoringOwnerSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R5MonitoringPolicy:
        """Append or replay one exact policy winner."""

    def append_calendar(
        self,
        *,
        definition: R5MonitoringCalendarDefinition,
        source: R5MonitoringOwnerSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R5MonitoringCalendar:
        """Append or replay one exact calendar winner."""


class R5MonitoringOwnerRegistryClock(_UowBound, Protocol):
    """Shared-UoW trusted server clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time inside the transaction."""


@dataclass(frozen=True)
class RegisterR5MonitoringPolicyCommand:
    """Policy identity only; no definition, source receipt, hash, or clock."""

    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R5 monitoring registration policy_id")
        _require_token(self.policy_version, "R5 monitoring registration policy_version")


@dataclass(frozen=True)
class RegisterR5MonitoringCalendarCommand:
    """Calendar identity only; no entries, source receipt, hash, or clock."""

    calendar_id: str
    calendar_version: str

    def __post_init__(self) -> None:
        _require_token(self.calendar_id, "R5 monitoring registration calendar_id")
        _require_token(
            self.calendar_version,
            "R5 monitoring registration calendar_version",
        )


class RegisterR5MonitoringPolicy:
    """Double-read and append one authoritative Research policy definition."""

    def __init__(
        self,
        *,
        definition_provider: R5MonitoringPolicyDefinitionProvider,
        source_provider: R5MonitoringOwnerSourceProvider,
        store: R5MonitoringOwnerRegistryStore,
        clock: R5MonitoringOwnerRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._source_provider = source_provider
        self._store = store
        self._clock = clock
        self._participants: tuple[_UowBound, ...] = (
            definition_provider,
            source_provider,
            store,
            clock,
        )
        self._expected_uow_key = _capture_shared_uow(self._participants)

    def execute(self, command: RegisterR5MonitoringPolicyCommand) -> R5MonitoringPolicy:
        """Register one exact policy without accepting caller semantics."""

        _validate_policy_command(command)
        return self._execute(command)

    def _execute(self, command: RegisterR5MonitoringPolicyCommand) -> R5MonitoringPolicy:
        try:
            self._require_bound_participants()
            with self._store.atomic():
                self._require_bound_participants()
                now = self._clock.now()
                _require_aware(now, "R5 monitoring registry server clock")
                first = self._read(command, now=now)
                self._require_bound_participants()
                second = self._read(command, now=now)
                self._require_bound_participants()
                if first != second:
                    raise R5MonitoringOwnerRegistryUnavailable(
                        "R5 monitoring policy owners changed during registration"
                    )
                definition, source = second
                persisted = self._store.append_policy(
                    definition=definition,
                    source=source,
                    ledger_recorded_at=now,
                )
                self._require_bound_participants()
                if type(persisted) is not R5MonitoringPolicy:
                    raise TypeError("R5 monitoring policy store returned another type")
                canonical = persisted.validated_copy()
                if canonical != definition.policy:
                    raise ValueError("R5 monitoring policy winner differs")
                return canonical
        except R5MonitoringOwnerRegistryUnavailable:
            raise
        except Exception as error:
            raise R5MonitoringOwnerRegistryUnavailable(
                "R5 monitoring policy registration is unavailable"
            ) from error

    def _require_bound_participants(self) -> None:
        current: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if any(
            actual is not expected
            for actual, expected in zip(current, self._participants, strict=True)
        ):
            raise R5MonitoringOwnerRegistryUnavailable(
                "R5 monitoring policy participant was replaced"
            )
        _require_expected_uow(current, self._expected_uow_key)

    def _read(
        self,
        command: RegisterR5MonitoringPolicyCommand,
        *,
        now: datetime,
    ) -> tuple[R5MonitoringPolicyDefinition, R5MonitoringOwnerSourceReceipt]:
        value = self._definition_provider.get_exact(
            owner_id=command.policy_id,
            owner_version=command.policy_version,
            as_of=now,
        )
        definition = _validated_policy_definition(value)
        policy = definition.policy
        if (
            policy.policy_id != command.policy_id
            or policy.policy_version != command.policy_version
            or not policy.recorded_at <= now < policy.valid_until
        ):
            raise ValueError("R5 monitoring policy definition identity or window differs")
        source = _validated_source(
            self._source_provider.get_exact(
                record_kind=R5MonitoringOwnerRecordKind.POLICY,
                owner_id=command.policy_id,
                owner_version=command.policy_version,
                definition_hash=definition.content_hash,
                as_of=now,
            )
        )
        _match_source(
            source,
            kind=R5MonitoringOwnerRecordKind.POLICY,
            owner_id=command.policy_id,
            owner_version=command.policy_version,
            definition_hash=definition.content_hash,
            now=now,
        )
        return definition, source


class RegisterR5MonitoringCalendar:
    """Double-read and append one authoritative Research calendar definition."""

    def __init__(
        self,
        *,
        definition_provider: R5MonitoringCalendarDefinitionProvider,
        source_provider: R5MonitoringOwnerSourceProvider,
        store: R5MonitoringOwnerRegistryStore,
        clock: R5MonitoringOwnerRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._source_provider = source_provider
        self._store = store
        self._clock = clock
        self._participants: tuple[_UowBound, ...] = (
            definition_provider,
            source_provider,
            store,
            clock,
        )
        self._expected_uow_key = _capture_shared_uow(self._participants)

    def execute(
        self,
        command: RegisterR5MonitoringCalendarCommand,
    ) -> R5MonitoringCalendar:
        """Register one exact calendar without accepting caller entries."""

        _validate_calendar_command(command)
        try:
            self._require_bound_participants()
            with self._store.atomic():
                self._require_bound_participants()
                now = self._clock.now()
                _require_aware(now, "R5 monitoring registry server clock")
                first = self._read(command, now=now)
                self._require_bound_participants()
                second = self._read(command, now=now)
                self._require_bound_participants()
                if first != second:
                    raise R5MonitoringOwnerRegistryUnavailable(
                        "R5 monitoring calendar owners changed during registration"
                    )
                definition, source = second
                persisted = self._store.append_calendar(
                    definition=definition,
                    source=source,
                    ledger_recorded_at=now,
                )
                self._require_bound_participants()
                if type(persisted) is not R5MonitoringCalendar:
                    raise TypeError("R5 monitoring calendar store returned another type")
                canonical = persisted.validated_copy()
                if canonical != definition.calendar:
                    raise ValueError("R5 monitoring calendar winner differs")
                return canonical
        except R5MonitoringOwnerRegistryUnavailable:
            raise
        except Exception as error:
            raise R5MonitoringOwnerRegistryUnavailable(
                "R5 monitoring calendar registration is unavailable"
            ) from error

    def _require_bound_participants(self) -> None:
        current: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if any(
            actual is not expected
            for actual, expected in zip(current, self._participants, strict=True)
        ):
            raise R5MonitoringOwnerRegistryUnavailable(
                "R5 monitoring calendar participant was replaced"
            )
        _require_expected_uow(current, self._expected_uow_key)

    def _read(
        self,
        command: RegisterR5MonitoringCalendarCommand,
        *,
        now: datetime,
    ) -> tuple[R5MonitoringCalendarDefinition, R5MonitoringOwnerSourceReceipt]:
        value = self._definition_provider.get_exact(
            owner_id=command.calendar_id,
            owner_version=command.calendar_version,
            as_of=now,
        )
        definition = _validated_calendar_definition(value)
        calendar = definition.calendar
        if (
            calendar.owner.owner_id != command.calendar_id
            or calendar.owner.owner_version != command.calendar_version
            or not calendar.recorded_at <= now < calendar.valid_until
        ):
            raise ValueError("R5 monitoring calendar definition identity or window differs")
        source = _validated_source(
            self._source_provider.get_exact(
                record_kind=R5MonitoringOwnerRecordKind.CALENDAR,
                owner_id=command.calendar_id,
                owner_version=command.calendar_version,
                definition_hash=definition.content_hash,
                as_of=now,
            )
        )
        _match_source(
            source,
            kind=R5MonitoringOwnerRecordKind.CALENDAR,
            owner_id=command.calendar_id,
            owner_version=command.calendar_version,
            definition_hash=definition.content_hash,
            now=now,
        )
        return definition, source


def _validated_policy_definition(value: object) -> R5MonitoringPolicyDefinition:
    if type(value) is not R5MonitoringPolicyDefinition:
        raise TypeError("R5 monitoring policy definition is unavailable")
    return value.validated_copy()


def _validated_calendar_definition(value: object) -> R5MonitoringCalendarDefinition:
    if type(value) is not R5MonitoringCalendarDefinition:
        raise TypeError("R5 monitoring calendar definition is unavailable")
    return value.validated_copy()


def _validated_source(value: object) -> R5MonitoringOwnerSourceReceipt:
    if type(value) is not R5MonitoringOwnerSourceReceipt:
        raise TypeError("R5 monitoring owner source receipt is unavailable")
    return value.validated_copy()


def _match_source(
    source: R5MonitoringOwnerSourceReceipt,
    *,
    kind: R5MonitoringOwnerRecordKind,
    owner_id: str,
    owner_version: str,
    definition_hash: str,
    now: datetime,
) -> None:
    if not (
        source.record_kind is kind
        and source.owner_id == owner_id
        and source.owner_version == owner_version
        and source.definition_hash == definition_hash
        and source.available_at <= now < source.valid_until
    ):
        raise ValueError("R5 monitoring owner source receipt differs")


def _capture_shared_uow(participants: tuple[_UowBound, ...]) -> str:
    keys = tuple(_uow_key(item) for item in participants)
    if len(set(keys)) != 1:
        raise R5MonitoringOwnerRegistryUnavailable(
            "R5 monitoring owner participants use different unit of work identities"
        )
    return keys[0]


def _require_expected_uow(
    participants: tuple[_UowBound, ...],
    expected_uow_key: str,
) -> None:
    if any(_uow_key(item) != expected_uow_key for item in participants):
        raise R5MonitoringOwnerRegistryUnavailable(
            "R5 monitoring owner unit of work identity changed"
        )


def _uow_key(value: _UowBound) -> str:
    key = value.unit_of_work_key
    if type(key) is not str or not key.strip():
        raise R5MonitoringOwnerRegistryUnavailable(
            "R5 monitoring owner unit of work identity is invalid"
        )
    return key


def _validate_policy_command(command: object) -> None:
    try:
        if type(command) is not RegisterR5MonitoringPolicyCommand:
            raise TypeError
        RegisterR5MonitoringPolicyCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringOwnerRegistryUnavailable(
            "R5 monitoring policy registration command is malformed"
        ) from error


def _validate_calendar_command(command: object) -> None:
    try:
        if type(command) is not RegisterR5MonitoringCalendarCommand:
            raise TypeError
        RegisterR5MonitoringCalendarCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringOwnerRegistryUnavailable(
            "R5 monitoring calendar registration command is malformed"
        ) from error


__all__ = [
    "R5MonitoringCalendarDefinitionProvider",
    "R5MonitoringOwnerRegistryClock",
    "R5MonitoringOwnerRegistryStore",
    "R5MonitoringOwnerRegistryUnavailable",
    "R5MonitoringOwnerSourceProvider",
    "R5MonitoringPolicyDefinitionProvider",
    "RegisterR5MonitoringCalendar",
    "RegisterR5MonitoringCalendarCommand",
    "RegisterR5MonitoringPolicy",
    "RegisterR5MonitoringPolicyCommand",
]
