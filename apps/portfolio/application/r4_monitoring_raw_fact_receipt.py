"""ID-only registration of Portfolio-owned R4 monitoring raw facts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactReceipt,
    PortfolioR4MonitoringRawFactSourceReceipt,
    R4MonitoringRawFactDefinition,
)


class PortfolioR4MonitoringRawFactUnavailable(RuntimeError):
    """An exact Portfolio raw-fact owner dependency was unavailable."""


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


class PortfolioR4MonitoringRawFactDefinitionProvider(_UowBound, Protocol):
    def get_exact(
        self, *, observation_id: str, observation_version: str, as_of: datetime
    ) -> R4MonitoringRawFactDefinition | None:
        """Return one exact trusted definition or explicit absence."""


class PortfolioR4MonitoringRawFactSourceProvider(_UowBound, Protocol):
    def get_exact(
        self,
        *,
        source_receipt_id: str,
        source_receipt_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> PortfolioR4MonitoringRawFactSourceReceipt | None:
        """Return one exact trusted source receipt or explicit absence."""


class PortfolioR4MonitoringRawFactStore(_UowBound, Protocol):
    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared Portfolio transaction."""

    def append(
        self,
        receipt: PortfolioR4MonitoringRawFactReceipt,
        *,
        definition_hash: str,
        source_receipt: PortfolioR4MonitoringRawFactSourceReceipt,
    ) -> PortfolioR4MonitoringRawFactReceipt:
        """Append one exact Portfolio owner receipt."""


class PortfolioR4MonitoringRawFactClock(_UowBound, Protocol):
    def now(self) -> datetime:
        """Return a trusted timezone-aware server timestamp."""


@dataclass(frozen=True)
class RegisterPortfolioR4MonitoringRawFactCommand:
    """Raw-fact identity; no metrics or finished receipt accepted."""

    observation_id: str
    observation_version: str
    source_receipt_id: str
    source_receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "observation_version",
            "source_receipt_id",
            "source_receipt_version",
        ):
            _require_token(getattr(self, name), name)
        _require_aware(self.as_of, "as_of")


def _uow_key(value: _UowBound) -> str:
    key = value.unit_of_work_key
    if type(key) is not str or not key.strip():
        raise PortfolioR4MonitoringRawFactUnavailable("owner unit of work is unavailable")
    return key


class RegisterPortfolioR4MonitoringRawFact:
    """Double-read owner inputs and append a server-clocked receipt."""

    def __init__(
        self,
        *,
        definition_provider: PortfolioR4MonitoringRawFactDefinitionProvider,
        source_provider: PortfolioR4MonitoringRawFactSourceProvider,
        store: PortfolioR4MonitoringRawFactStore,
        clock: PortfolioR4MonitoringRawFactClock,
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

    def execute(
        self, command: RegisterPortfolioR4MonitoringRawFactCommand
    ) -> PortfolioR4MonitoringRawFactReceipt:
        """Append one exact source-backed receipt or fail without a write."""

        try:
            _validate_command(command)
            self._require_unchanged_participants()
            with self._store.atomic():
                self._require_unchanged_participants()
                now = self._clock.now()
                _require_aware(now, "clock.now")
                self._require_unchanged_participants()
                if command.as_of > now:
                    raise PortfolioR4MonitoringRawFactUnavailable("future registration cutoff")
                definition = self._read_definition(command)
                self._require_unchanged_participants()
                source = self._read_source(command, definition, now)
                self._require_unchanged_participants()
                second_definition = self._read_definition(command)
                self._require_unchanged_participants()
                if second_definition != definition:
                    raise PortfolioR4MonitoringRawFactUnavailable("raw definition changed")
                second_source = self._read_source(command, definition, now)
                self._require_unchanged_participants()
                if second_source != source:
                    raise PortfolioR4MonitoringRawFactUnavailable("raw source changed")
                receipt = definition.build(owner_recorded_at=now)
                self._require_unchanged_participants()
                result = self._store.append(
                    receipt,
                    definition_hash=definition.content_hash,
                    source_receipt=source,
                )
                self._require_unchanged_participants()
                if type(result) is not PortfolioR4MonitoringRawFactReceipt or result != receipt:
                    raise PortfolioR4MonitoringRawFactUnavailable(
                        "raw-fact store substituted the owner receipt"
                    )
                PortfolioR4MonitoringRawFactReceipt.__post_init__(result)
                return result
        except PortfolioR4MonitoringRawFactUnavailable:
            raise
        except Exception as error:
            raise PortfolioR4MonitoringRawFactUnavailable(
                "raw-fact owner registration is unavailable"
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
        self, command: RegisterPortfolioR4MonitoringRawFactCommand
    ) -> R4MonitoringRawFactDefinition:
        value = self._definition_provider.get_exact(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            as_of=command.as_of,
        )
        if type(value) is not R4MonitoringRawFactDefinition:
            raise PortfolioR4MonitoringRawFactUnavailable("exact raw definition unavailable")
        R4MonitoringRawFactDefinition.__post_init__(value)
        if (
            value.observation_id != command.observation_id
            or value.observation_version != command.observation_version
        ):
            raise PortfolioR4MonitoringRawFactUnavailable("raw definition substitution")
        return value

    def _read_source(
        self,
        command: RegisterPortfolioR4MonitoringRawFactCommand,
        definition: R4MonitoringRawFactDefinition,
        now: datetime,
    ) -> PortfolioR4MonitoringRawFactSourceReceipt:
        value = self._source_provider.get_exact(
            source_receipt_id=command.source_receipt_id,
            source_receipt_version=command.source_receipt_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        if type(value) is not PortfolioR4MonitoringRawFactSourceReceipt:
            raise PortfolioR4MonitoringRawFactUnavailable("exact raw source unavailable")
        PortfolioR4MonitoringRawFactSourceReceipt.__post_init__(value)
        if (
            value.source_receipt_id != command.source_receipt_id
            or value.source_receipt_version != command.source_receipt_version
            or value.definition_hash.lower() != definition.content_hash.lower()
            or not value.available_at <= now < value.valid_until
        ):
            raise PortfolioR4MonitoringRawFactUnavailable("raw source substitution or stale")
        return value


def _validate_command(command: RegisterPortfolioR4MonitoringRawFactCommand) -> None:
    if type(command) is not RegisterPortfolioR4MonitoringRawFactCommand:
        raise PortfolioR4MonitoringRawFactUnavailable("raw-fact command type is invalid")
    rebuilt = RegisterPortfolioR4MonitoringRawFactCommand(
        command.observation_id,
        command.observation_version,
        command.source_receipt_id,
        command.source_receipt_version,
        command.as_of,
    )
    if rebuilt != command:
        raise PortfolioR4MonitoringRawFactUnavailable("raw-fact command failed live validation")


def _capture_shared_uow(participants: tuple[_UowBound, ...]) -> str:
    try:
        keys = {_uow_key(participant) for participant in participants}
    except PortfolioR4MonitoringRawFactUnavailable:
        raise
    except Exception as error:
        raise PortfolioR4MonitoringRawFactUnavailable(
            "owner unit of work is unavailable"
        ) from error
    if len(keys) != 1:
        raise PortfolioR4MonitoringRawFactUnavailable("owners use different unit of work")
    return next(iter(keys))


def _require_expected_uow(participants: tuple[_UowBound, ...], expected_uow_key: str) -> None:
    if _capture_shared_uow(participants) != expected_uow_key:
        raise PortfolioR4MonitoringRawFactUnavailable("owner unit of work changed")


def _require_participant_identity(
    expected: tuple[object, ...], current: tuple[object, ...]
) -> None:
    if len(expected) != len(current) or any(
        expected_item is not current_item
        for expected_item, current_item in zip(expected, current, strict=True)
    ):
        raise PortfolioR4MonitoringRawFactUnavailable("owner participant was replaced")


__all__ = [
    "PortfolioR4MonitoringRawFactDefinitionProvider",
    "PortfolioR4MonitoringRawFactSourceProvider",
    "PortfolioR4MonitoringRawFactStore",
    "PortfolioR4MonitoringRawFactUnavailable",
    "RegisterPortfolioR4MonitoringRawFact",
    "RegisterPortfolioR4MonitoringRawFactCommand",
]
