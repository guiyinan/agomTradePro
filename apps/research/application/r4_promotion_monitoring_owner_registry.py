"""ID-only registration of canonical Research R4 monitoring owner records."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
)
from apps.research.domain.r4_promotion_monitoring_owner_registry import (
    R4MonitoringCalendarDefinition,
    R4MonitoringOwnerRecordKind,
    R4MonitoringOwnerSourceReceipt,
    R4MonitoringPolicyDefinition,
)


class R4MonitoringOwnerRegistryUnavailable(RuntimeError):
    """An exact owner definition/source/UoW was unavailable or substituted."""


def _require_token(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one stable shared transaction identity."""


class R4MonitoringPolicyDefinitionProvider(_UowBound, Protocol):
    """Trusted Research policy definition source."""

    def get_exact(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> R4MonitoringPolicyDefinition | None:
        """Return the exact definition or explicit absence."""


class R4MonitoringCalendarDefinitionProvider(_UowBound, Protocol):
    """Trusted Research calendar definition source."""

    def get_exact(
        self, *, calendar_id: str, calendar_version: str, as_of: datetime
    ) -> R4MonitoringCalendarDefinition | None:
        """Return the exact definition or explicit absence."""


class R4MonitoringOwnerSourceProvider(_UowBound, Protocol):
    """Trusted Research receipt source binding one exact definition."""

    def get_exact(
        self,
        *,
        record_kind: R4MonitoringOwnerRecordKind,
        source_receipt_id: str,
        source_receipt_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R4MonitoringOwnerSourceReceipt | None:
        """Return the exact source receipt or explicit absence."""


class R4MonitoringOwnerRegistryStore(_UowBound, Protocol):
    """Private append-only store capability retained only by composition."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared owner transaction."""

    def append_policy(
        self,
        policy: R4MonitoringPolicy,
        *,
        definition_hash: str,
        source_receipt: R4MonitoringOwnerSourceReceipt,
    ) -> R4MonitoringPolicy:
        """Append one exact Research-owned policy."""

    def append_calendar(
        self,
        calendar: R4MonitoringPeriodCalendar,
        *,
        definition_hash: str,
        source_receipt: R4MonitoringOwnerSourceReceipt,
    ) -> R4MonitoringPeriodCalendar:
        """Append one exact Research-owned calendar."""


class R4MonitoringOwnerRegistryClock(_UowBound, Protocol):
    """Trusted server clock for owner recording times."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""


@dataclass(frozen=True)
class RegisterR4MonitoringPolicyCommand:
    """Policy registration identity; no thresholds or finished policy accepted."""

    policy_id: str
    policy_version: str
    source_receipt_id: str
    source_receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for name in (
            "policy_id",
            "policy_version",
            "source_receipt_id",
            "source_receipt_version",
        ):
            _require_token(getattr(self, name), name)
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class RegisterR4MonitoringCalendarCommand:
    """Calendar registration identity; no entries or finished calendar accepted."""

    calendar_id: str
    calendar_version: str
    source_receipt_id: str
    source_receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for name in (
            "calendar_id",
            "calendar_version",
            "source_receipt_id",
            "source_receipt_version",
        ):
            _require_token(getattr(self, name), name)
        _require_aware(self.as_of, "as_of")


def _uow_key(value: _UowBound) -> str:
    key = value.unit_of_work_key
    if type(key) is not str or not key.strip():
        raise R4MonitoringOwnerRegistryUnavailable("owner unit of work is unavailable")
    return key


class RegisterR4MonitoringPolicy:
    """Double-read owner inputs and build a policy with the server clock."""

    def __init__(
        self,
        *,
        definition_provider: R4MonitoringPolicyDefinitionProvider,
        source_provider: R4MonitoringOwnerSourceProvider,
        store: R4MonitoringOwnerRegistryStore,
        clock: R4MonitoringOwnerRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._source_provider = source_provider
        self._store = store
        self._clock = clock
        self._participant_identities = (
            definition_provider,
            source_provider,
            store,
            clock,
        )
        self._expected_uow_key = _capture_shared_uow(self._participant_identities)
        self._require_unchanged_participants()

    def execute(self, command: RegisterR4MonitoringPolicyCommand) -> R4MonitoringPolicy:
        """Append one exact source-backed policy or fail without a write."""

        try:
            _validate_policy_command(command)
            self._require_unchanged_participants()
            with self._store.atomic():
                self._require_unchanged_participants()
                now = self._clock.now()
                _require_aware(now, "clock.now")
                self._require_unchanged_participants()
                if command.as_of > now:
                    raise R4MonitoringOwnerRegistryUnavailable("future registration cutoff")
                definition = self._read_definition(command)
                self._require_unchanged_participants()
                source = self._read_source(command, definition, now)
                self._require_unchanged_participants()
                second_definition = self._read_definition(command)
                self._require_unchanged_participants()
                if second_definition != definition:
                    raise R4MonitoringOwnerRegistryUnavailable("policy definition changed")
                second_source = self._read_source(command, definition, now)
                self._require_unchanged_participants()
                if second_source != source:
                    raise R4MonitoringOwnerRegistryUnavailable("policy source changed")
                policy = definition.build(recorded_at=now)
                self._require_unchanged_participants()
                result = self._store.append_policy(
                    policy,
                    definition_hash=definition.content_hash,
                    source_receipt=source,
                )
                self._require_unchanged_participants()
                if type(result) is not R4MonitoringPolicy or result != policy:
                    raise R4MonitoringOwnerRegistryUnavailable(
                        "policy store substituted the owner record"
                    )
                R4MonitoringPolicy.__post_init__(result)
                return result
        except R4MonitoringOwnerRegistryUnavailable:
            raise
        except Exception as error:
            raise R4MonitoringOwnerRegistryUnavailable(
                "policy owner registration is unavailable"
            ) from error

    def _require_unchanged_participants(self) -> None:
        _require_participant_identity(
            self._participant_identities,
            (
                self._definition_provider,
                self._source_provider,
                self._store,
                self._clock,
            ),
        )
        _require_expected_uow(self._participant_identities, self._expected_uow_key)

    def _read_definition(
        self, command: RegisterR4MonitoringPolicyCommand
    ) -> R4MonitoringPolicyDefinition:
        value = self._definition_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            as_of=command.as_of,
        )
        if type(value) is not R4MonitoringPolicyDefinition:
            raise R4MonitoringOwnerRegistryUnavailable("exact policy definition unavailable")
        R4MonitoringPolicyDefinition.__post_init__(value)
        if value.policy_id != command.policy_id or value.policy_version != command.policy_version:
            raise R4MonitoringOwnerRegistryUnavailable("policy definition substitution")
        return value

    def _read_source(
        self,
        command: RegisterR4MonitoringPolicyCommand,
        definition: R4MonitoringPolicyDefinition,
        now: datetime,
    ) -> R4MonitoringOwnerSourceReceipt:
        value = self._source_provider.get_exact(
            record_kind=R4MonitoringOwnerRecordKind.POLICY,
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        return _validated_source(
            value,
            expected_kind=R4MonitoringOwnerRecordKind.POLICY,
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            now=now,
        )


class RegisterR4MonitoringCalendar:
    """Double-read owner inputs and build a calendar with the server clock."""

    def __init__(
        self,
        *,
        definition_provider: R4MonitoringCalendarDefinitionProvider,
        source_provider: R4MonitoringOwnerSourceProvider,
        store: R4MonitoringOwnerRegistryStore,
        clock: R4MonitoringOwnerRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._source_provider = source_provider
        self._store = store
        self._clock = clock
        self._participant_identities = (
            definition_provider,
            source_provider,
            store,
            clock,
        )
        self._expected_uow_key = _capture_shared_uow(self._participant_identities)
        self._require_unchanged_participants()

    def execute(self, command: RegisterR4MonitoringCalendarCommand) -> R4MonitoringPeriodCalendar:
        """Append one exact source-backed calendar or fail without a write."""

        try:
            _validate_calendar_command(command)
            self._require_unchanged_participants()
            with self._store.atomic():
                self._require_unchanged_participants()
                now = self._clock.now()
                _require_aware(now, "clock.now")
                self._require_unchanged_participants()
                if command.as_of > now:
                    raise R4MonitoringOwnerRegistryUnavailable("future registration cutoff")
                definition = self._read_definition(command)
                self._require_unchanged_participants()
                source = self._read_source(command, definition, now)
                self._require_unchanged_participants()
                second_definition = self._read_definition(command)
                self._require_unchanged_participants()
                if second_definition != definition:
                    raise R4MonitoringOwnerRegistryUnavailable("calendar definition changed")
                second_source = self._read_source(command, definition, now)
                self._require_unchanged_participants()
                if second_source != source:
                    raise R4MonitoringOwnerRegistryUnavailable("calendar source changed")
                calendar = definition.build(recorded_at=now)
                self._require_unchanged_participants()
                result = self._store.append_calendar(
                    calendar,
                    definition_hash=definition.content_hash,
                    source_receipt=source,
                )
                self._require_unchanged_participants()
                if type(result) is not R4MonitoringPeriodCalendar or result != calendar:
                    raise R4MonitoringOwnerRegistryUnavailable(
                        "calendar store substituted the owner record"
                    )
                R4MonitoringPeriodCalendar.__post_init__(result)
                return result
        except R4MonitoringOwnerRegistryUnavailable:
            raise
        except Exception as error:
            raise R4MonitoringOwnerRegistryUnavailable(
                "calendar owner registration is unavailable"
            ) from error

    def _require_unchanged_participants(self) -> None:
        _require_participant_identity(
            self._participant_identities,
            (
                self._definition_provider,
                self._source_provider,
                self._store,
                self._clock,
            ),
        )
        _require_expected_uow(self._participant_identities, self._expected_uow_key)

    def _read_definition(
        self, command: RegisterR4MonitoringCalendarCommand
    ) -> R4MonitoringCalendarDefinition:
        value = self._definition_provider.get_exact(
            calendar_id=command.calendar_id,
            calendar_version=command.calendar_version,
            as_of=command.as_of,
        )
        if type(value) is not R4MonitoringCalendarDefinition:
            raise R4MonitoringOwnerRegistryUnavailable("exact calendar definition unavailable")
        R4MonitoringCalendarDefinition.__post_init__(value)
        if (
            value.calendar_id != command.calendar_id
            or value.calendar_version != command.calendar_version
        ):
            raise R4MonitoringOwnerRegistryUnavailable("calendar definition substitution")
        return value

    def _read_source(
        self,
        command: RegisterR4MonitoringCalendarCommand,
        definition: R4MonitoringCalendarDefinition,
        now: datetime,
    ) -> R4MonitoringOwnerSourceReceipt:
        value = self._source_provider.get_exact(
            record_kind=R4MonitoringOwnerRecordKind.CALENDAR,
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        return _validated_source(
            value,
            expected_kind=R4MonitoringOwnerRecordKind.CALENDAR,
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            now=now,
        )


def _validated_source(
    value: object,
    *,
    expected_kind: R4MonitoringOwnerRecordKind,
    source_receipt_id: str,
    source_receipt_version: str,
    definition_hash: str,
    now: datetime,
) -> R4MonitoringOwnerSourceReceipt:
    if type(value) is not R4MonitoringOwnerSourceReceipt:
        raise R4MonitoringOwnerRegistryUnavailable("exact owner source unavailable")
    R4MonitoringOwnerSourceReceipt.__post_init__(value)
    if (
        value.record_kind is not expected_kind
        or value.source_receipt_id != source_receipt_id
        or value.source_receipt_version != source_receipt_version
        or value.definition_hash.lower() != definition_hash.lower()
        or not value.available_at <= now < value.valid_until
    ):
        raise R4MonitoringOwnerRegistryUnavailable("owner source substitution or stale receipt")
    return value


def _capture_shared_uow(participants: tuple[_UowBound, ...]) -> str:
    try:
        keys = {_uow_key(participant) for participant in participants}
    except R4MonitoringOwnerRegistryUnavailable:
        raise
    except Exception as error:
        raise R4MonitoringOwnerRegistryUnavailable("owner unit of work is unavailable") from error
    if len(keys) != 1:
        raise R4MonitoringOwnerRegistryUnavailable("owners use different unit of work")
    return next(iter(keys))


def _require_expected_uow(participants: tuple[_UowBound, ...], expected_uow_key: str) -> None:
    if _capture_shared_uow(participants) != expected_uow_key:
        raise R4MonitoringOwnerRegistryUnavailable("owner unit of work changed")


def _require_participant_identity(
    expected: tuple[object, ...], current: tuple[object, ...]
) -> None:
    if len(expected) != len(current) or any(
        expected_item is not current_item
        for expected_item, current_item in zip(expected, current, strict=True)
    ):
        raise R4MonitoringOwnerRegistryUnavailable("owner participant was replaced")


def _validate_policy_command(command: RegisterR4MonitoringPolicyCommand) -> None:
    if type(command) is not RegisterR4MonitoringPolicyCommand:
        raise R4MonitoringOwnerRegistryUnavailable("policy command type is invalid")
    rebuilt = RegisterR4MonitoringPolicyCommand(
        command.policy_id,
        command.policy_version,
        command.source_receipt_id,
        command.source_receipt_version,
        command.as_of,
    )
    if rebuilt != command:
        raise R4MonitoringOwnerRegistryUnavailable("policy command failed live validation")


def _validate_calendar_command(command: RegisterR4MonitoringCalendarCommand) -> None:
    if type(command) is not RegisterR4MonitoringCalendarCommand:
        raise R4MonitoringOwnerRegistryUnavailable("calendar command type is invalid")
    rebuilt = RegisterR4MonitoringCalendarCommand(
        command.calendar_id,
        command.calendar_version,
        command.source_receipt_id,
        command.source_receipt_version,
        command.as_of,
    )
    if rebuilt != command:
        raise R4MonitoringOwnerRegistryUnavailable("calendar command failed live validation")


__all__ = [
    "R4MonitoringCalendarDefinitionProvider",
    "R4MonitoringOwnerRegistryUnavailable",
    "R4MonitoringOwnerRegistryStore",
    "R4MonitoringOwnerSourceProvider",
    "R4MonitoringPolicyDefinitionProvider",
    "RegisterR4MonitoringCalendar",
    "RegisterR4MonitoringCalendarCommand",
    "RegisterR4MonitoringPolicy",
    "RegisterR4MonitoringPolicyCommand",
]
