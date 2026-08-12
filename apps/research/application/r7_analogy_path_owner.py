"""ID-only application boundaries for R7 analogy and path owners."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from apps.research.domain.r7_analogy_path_owner import (
    HistoricalAnalogyDefinition,
    HistoricalAnalogyRawSource,
    HistoricalAnalogyReceipt,
    ScenarioPathDefinition,
    ScenarioPathRawSource,
    ScenarioPathReceipt,
)


class R7AnalogyPathOwnerUnavailable(RuntimeError):
    """The exact canonical owner graph or its shared transaction is unavailable."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the dynamic shared transaction identity."""


class R7AnalogyPathOwnerClock(_UowBound, Protocol):
    """Trusted clock participating in the owner unit of work."""

    def now(self) -> datetime:
        """Return the exact server-side registration clock."""


@dataclass(frozen=True)
class RegisterHistoricalAnalogyDefinitionCommand:
    """Historical analogy definition identity and requested PIT only."""

    definition_id: str
    definition_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.definition_id, "analogy definition_id")
        _token(self.definition_version, "analogy definition_version")
        _aware(self.as_of, "analogy definition as_of")


@dataclass(frozen=True)
class RegisterHistoricalAnalogyReceiptCommand:
    """Historical analogy receipt identity and requested PIT only."""

    definition_id: str
    definition_version: str
    receipt_id: str
    receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.definition_id, "analogy definition_id")
        _token(self.definition_version, "analogy definition_version")
        _token(self.receipt_id, "analogy receipt_id")
        _token(self.receipt_version, "analogy receipt_version")
        _aware(self.as_of, "analogy receipt as_of")


@dataclass(frozen=True)
class RegisterScenarioPathDefinitionCommand:
    """Scenario-path definition identity and requested PIT only."""

    definition_id: str
    definition_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.definition_id, "path definition_id")
        _token(self.definition_version, "path definition_version")
        _aware(self.as_of, "path definition as_of")


@dataclass(frozen=True)
class RegisterScenarioPathReceiptCommand:
    """Scenario-path receipt identity and requested PIT only."""

    definition_id: str
    definition_version: str
    receipt_id: str
    receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.definition_id, "path definition_id")
        _token(self.definition_version, "path definition_version")
        _token(self.receipt_id, "path receipt_id")
        _token(self.receipt_version, "path receipt_version")
        _aware(self.as_of, "path receipt as_of")


class HistoricalAnalogyDefinitionSource(_UowBound, Protocol):
    """Canonical source for exact analogy definitions."""

    def get_exact(
        self, *, definition_id: str, definition_version: str, as_of: datetime
    ) -> HistoricalAnalogyDefinition | None:
        """Return one exact definition or explicit absence."""


class HistoricalAnalogyRawSourceProvider(_UowBound, Protocol):
    """Canonical source for analogy raw feature graphs."""

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> HistoricalAnalogyRawSource | None:
        """Return one raw graph; never accept or return a caller score."""


class ScenarioPathDefinitionSource(_UowBound, Protocol):
    """Canonical source for exact path definitions."""

    def get_exact(
        self, *, definition_id: str, definition_version: str, as_of: datetime
    ) -> ScenarioPathDefinition | None:
        """Return one exact definition or explicit absence."""


class ScenarioPathRawSourceProvider(_UowBound, Protocol):
    """Canonical source for expected-member raw path graphs."""

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> ScenarioPathRawSource | None:
        """Return raw member facts; never accept or return a caller probability."""


class HistoricalAnalogyDefinitionStore(_UowBound, Protocol):
    """Private append capability for analogy definitions."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the owner transaction."""

    def append(self, definition: HistoricalAnalogyDefinition) -> HistoricalAnalogyDefinition:
        """Append or replay one exact definition winner."""


class HistoricalAnalogyReceiptStore(_UowBound, Protocol):
    """Private append capability for analogy receipts."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the owner transaction."""

    def append(self, receipt: HistoricalAnalogyReceipt) -> HistoricalAnalogyReceipt:
        """Append or replay one exact receipt winner."""


class ScenarioPathDefinitionStore(_UowBound, Protocol):
    """Private append capability for path definitions."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the owner transaction."""

    def append(self, definition: ScenarioPathDefinition) -> ScenarioPathDefinition:
        """Append or replay one exact definition winner."""


class ScenarioPathReceiptStore(_UowBound, Protocol):
    """Private append capability for path receipts."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the owner transaction."""

    def append(self, receipt: ScenarioPathReceipt) -> ScenarioPathReceipt:
        """Append or replay one exact receipt winner."""


class RegisterHistoricalAnalogyDefinition:
    """Double-read and append one exact analogy definition."""

    def __init__(
        self,
        *,
        source: HistoricalAnalogyDefinitionSource,
        store: HistoricalAnalogyDefinitionStore,
        clock: R7AnalogyPathOwnerClock,
    ) -> None:
        self._source = source
        self._store = store
        self._clock = clock
        self._guard = _ParticipantGuard((source, store, clock))

    def execute(
        self, command: RegisterHistoricalAnalogyDefinitionCommand
    ) -> HistoricalAnalogyDefinition:
        """Append only a stable, live-valid definition graph."""

        _validate_analogy_definition_command(command)
        try:
            with self._store.atomic():
                self._guard.require_unchanged((self._source, self._store, self._clock))
                now = _trusted_now(self._clock, command.as_of)
                first = self._read(command)
                self._guard.require_unchanged((self._source, self._store, self._clock))
                second = self._read(command)
                if first != second:
                    raise ValueError("analogy definition changed during reread")
                winner = self._store.append(second)
                self._guard.require_unchanged((self._source, self._store, self._clock))
                exact = _exact_analogy_definition(winner)
                if exact != second or not exact.activated_at <= now < exact.valid_until:
                    raise ValueError("analogy definition winner or validity differs")
                return exact
        except R7AnalogyPathOwnerUnavailable:
            raise
        except Exception as error:
            raise R7AnalogyPathOwnerUnavailable(
                "historical analogy definition registration is unavailable"
            ) from error

    def _read(
        self, command: RegisterHistoricalAnalogyDefinitionCommand
    ) -> HistoricalAnalogyDefinition:
        value = self._source.get_exact(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            as_of=command.as_of,
        )
        result = _exact_analogy_definition(value)
        if (
            result.definition_id != command.definition_id
            or result.definition_version != command.definition_version
            or not result.activated_at <= command.as_of < result.valid_until
        ):
            raise ValueError("analogy definition identity or PIT validity differs")
        return result


class RegisterScenarioPathDefinition:
    """Double-read and append one exact path definition."""

    def __init__(
        self,
        *,
        source: ScenarioPathDefinitionSource,
        store: ScenarioPathDefinitionStore,
        clock: R7AnalogyPathOwnerClock,
    ) -> None:
        self._source = source
        self._store = store
        self._clock = clock
        self._guard = _ParticipantGuard((source, store, clock))

    def execute(self, command: RegisterScenarioPathDefinitionCommand) -> ScenarioPathDefinition:
        """Append only a stable, live-valid definition graph."""

        _validate_path_definition_command(command)
        try:
            with self._store.atomic():
                self._guard.require_unchanged((self._source, self._store, self._clock))
                now = _trusted_now(self._clock, command.as_of)
                first = self._read(command)
                self._guard.require_unchanged((self._source, self._store, self._clock))
                second = self._read(command)
                if first != second:
                    raise ValueError("path definition changed during reread")
                winner = self._store.append(second)
                self._guard.require_unchanged((self._source, self._store, self._clock))
                exact = _exact_path_definition(winner)
                if exact != second or not exact.activated_at <= now < exact.valid_until:
                    raise ValueError("path definition winner or validity differs")
                return exact
        except R7AnalogyPathOwnerUnavailable:
            raise
        except Exception as error:
            raise R7AnalogyPathOwnerUnavailable(
                "scenario path definition registration is unavailable"
            ) from error

    def _read(self, command: RegisterScenarioPathDefinitionCommand) -> ScenarioPathDefinition:
        value = self._source.get_exact(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            as_of=command.as_of,
        )
        result = _exact_path_definition(value)
        if (
            result.definition_id != command.definition_id
            or result.definition_version != command.definition_version
            or not result.activated_at <= command.as_of < result.valid_until
        ):
            raise ValueError("path definition identity or PIT validity differs")
        return result


class RegisterHistoricalAnalogyReceipt:
    """Build a receipt from stable canonical raw facts and a trusted clock."""

    def __init__(
        self,
        *,
        definition_source: HistoricalAnalogyDefinitionSource,
        raw_source: HistoricalAnalogyRawSourceProvider,
        store: HistoricalAnalogyReceiptStore,
        clock: R7AnalogyPathOwnerClock,
    ) -> None:
        self._definition_source = definition_source
        self._raw_source = raw_source
        self._store = store
        self._clock = clock
        self._guard = _ParticipantGuard((definition_source, raw_source, store, clock))

    def execute(self, command: RegisterHistoricalAnalogyReceiptCommand) -> HistoricalAnalogyReceipt:
        """Append only a stable definition/raw graph; absence remains zero-write."""

        _validate_analogy_receipt_command(command)
        participants = (self._definition_source, self._raw_source, self._store, self._clock)
        try:
            with self._store.atomic():
                self._guard.require_unchanged(participants)
                recorded_at = _trusted_now(self._clock, command.as_of)
                first = self._read(command, recorded_at)
                self._guard.require_unchanged(participants)
                second = self._read(command, recorded_at)
                if first != second:
                    raise ValueError("analogy receipt owner graph changed during reread")
                definition, raw = self._read(command, recorded_at)
                if (definition, raw) != second:
                    raise ValueError("analogy receipt owner graph changed before append")
                receipt = HistoricalAnalogyReceipt.create(
                    receipt_id=command.receipt_id,
                    receipt_version=command.receipt_version,
                    definition=definition,
                    source=raw,
                    recorded_at=recorded_at,
                )
                winner = _exact_analogy_receipt(self._store.append(receipt))
                self._guard.require_unchanged(participants)
                if winner != receipt:
                    raise ValueError("analogy receipt winner differs")
                return winner
        except R7AnalogyPathOwnerUnavailable:
            raise
        except Exception as error:
            raise R7AnalogyPathOwnerUnavailable(
                "historical analogy receipt registration is unavailable"
            ) from error

    def _read(
        self,
        command: RegisterHistoricalAnalogyReceiptCommand,
        recorded_at: datetime,
    ) -> tuple[HistoricalAnalogyDefinition, HistoricalAnalogyRawSource]:
        definition = _exact_analogy_definition(
            self._definition_source.get_exact(
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                as_of=command.as_of,
            )
        )
        if (
            definition.definition_id != command.definition_id
            or definition.definition_version != command.definition_version
            or not definition.activated_at <= command.as_of < definition.valid_until
            or recorded_at >= definition.valid_until
        ):
            raise ValueError("analogy receipt definition differs")
        raw = _exact_analogy_raw_source(
            self._raw_source.get_exact(
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                as_of=command.as_of,
            )
        )
        if raw.query_manifest.as_of != command.as_of or raw.available_at > recorded_at:
            raise ValueError("analogy raw source PIT or availability differs")
        return definition, raw


class RegisterScenarioPathReceipt:
    """Build a path receipt from stable raw membership and a trusted clock."""

    def __init__(
        self,
        *,
        definition_source: ScenarioPathDefinitionSource,
        raw_source: ScenarioPathRawSourceProvider,
        store: ScenarioPathReceiptStore,
        clock: R7AnalogyPathOwnerClock,
    ) -> None:
        self._definition_source = definition_source
        self._raw_source = raw_source
        self._store = store
        self._clock = clock
        self._guard = _ParticipantGuard((definition_source, raw_source, store, clock))

    def execute(self, command: RegisterScenarioPathReceiptCommand) -> ScenarioPathReceipt:
        """Append only a stable definition/raw graph; absence remains zero-write."""

        _validate_path_receipt_command(command)
        participants = (self._definition_source, self._raw_source, self._store, self._clock)
        try:
            with self._store.atomic():
                self._guard.require_unchanged(participants)
                recorded_at = _trusted_now(self._clock, command.as_of)
                first = self._read(command, recorded_at)
                self._guard.require_unchanged(participants)
                second = self._read(command, recorded_at)
                if first != second:
                    raise ValueError("path receipt owner graph changed during reread")
                definition, raw = self._read(command, recorded_at)
                if (definition, raw) != second:
                    raise ValueError("path receipt owner graph changed before append")
                receipt = ScenarioPathReceipt.create(
                    receipt_id=command.receipt_id,
                    receipt_version=command.receipt_version,
                    definition=definition,
                    source=raw,
                    recorded_at=recorded_at,
                )
                winner = _exact_path_receipt(self._store.append(receipt))
                self._guard.require_unchanged(participants)
                if winner != receipt:
                    raise ValueError("path receipt winner differs")
                return winner
        except R7AnalogyPathOwnerUnavailable:
            raise
        except Exception as error:
            raise R7AnalogyPathOwnerUnavailable(
                "scenario path receipt registration is unavailable"
            ) from error

    def _read(
        self,
        command: RegisterScenarioPathReceiptCommand,
        recorded_at: datetime,
    ) -> tuple[ScenarioPathDefinition, ScenarioPathRawSource]:
        definition = _exact_path_definition(
            self._definition_source.get_exact(
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                as_of=command.as_of,
            )
        )
        if (
            definition.definition_id != command.definition_id
            or definition.definition_version != command.definition_version
            or not definition.activated_at <= command.as_of < definition.valid_until
            or recorded_at >= definition.valid_until
        ):
            raise ValueError("path receipt definition differs")
        raw = _exact_path_raw_source(
            self._raw_source.get_exact(
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                as_of=command.as_of,
            )
        )
        if raw.pit_manifest.as_of != command.as_of or raw.available_at > recorded_at:
            raise ValueError("path raw source PIT or availability differs")
        return definition, raw


_CommandT = TypeVar(
    "_CommandT",
    RegisterHistoricalAnalogyDefinitionCommand,
    RegisterHistoricalAnalogyReceiptCommand,
    RegisterScenarioPathDefinitionCommand,
    RegisterScenarioPathReceiptCommand,
)


class _ParticipantGuard:
    def __init__(self, participants: tuple[_UowBound, ...]) -> None:
        self._ids = tuple(id(item) for item in participants)
        self._uow = _shared_uow(participants)

    def require_unchanged(self, participants: tuple[_UowBound, ...]) -> None:
        if tuple(id(item) for item in participants) != self._ids:
            raise R7AnalogyPathOwnerUnavailable("R7 owner participant was replaced")
        if _shared_uow(participants) != self._uow:
            raise R7AnalogyPathOwnerUnavailable("R7 owner UoW identity changed")


def _shared_uow(participants: tuple[_UowBound, ...]) -> str:
    values = {_token(item.unit_of_work_key, "R7 owner unit_of_work_key") for item in participants}
    if len(values) != 1:
        raise R7AnalogyPathOwnerUnavailable("R7 owner participants use different UoWs")
    return next(iter(values))


def _trusted_now(clock: R7AnalogyPathOwnerClock, as_of: datetime) -> datetime:
    now = clock.now()
    _aware(now, "R7 owner trusted clock")
    if as_of > now:
        raise ValueError("R7 owner as_of cannot exceed trusted clock")
    return now


def _validated_command(command: object, expected: type[_CommandT]) -> _CommandT:
    try:
        if type(command) is not expected:
            raise TypeError("R7 owner command type differs")
        expected.__post_init__(command)
        values = {item: getattr(command, item) for item in command.__dataclass_fields__}
        rebuilt = expected(**values)
        if rebuilt != command:
            raise ValueError("R7 owner command differs after replay")
        return rebuilt
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerUnavailable("R7 owner command is malformed") from error


def _validate_analogy_definition_command(command: object) -> None:
    _validated_command(command, RegisterHistoricalAnalogyDefinitionCommand)


def _validate_analogy_receipt_command(command: object) -> None:
    _validated_command(command, RegisterHistoricalAnalogyReceiptCommand)


def _validate_path_definition_command(command: object) -> None:
    _validated_command(command, RegisterScenarioPathDefinitionCommand)


def _validate_path_receipt_command(command: object) -> None:
    _validated_command(command, RegisterScenarioPathReceiptCommand)


def _exact_analogy_definition(value: object) -> HistoricalAnalogyDefinition:
    if type(value) is not HistoricalAnalogyDefinition:
        raise TypeError("historical analogy definition is unavailable")
    return HistoricalAnalogyDefinition.validated_copy(value)


def _exact_analogy_raw_source(value: object) -> HistoricalAnalogyRawSource:
    if type(value) is not HistoricalAnalogyRawSource:
        raise TypeError("historical analogy raw source is unavailable")
    return HistoricalAnalogyRawSource.validated_copy(value)


def _exact_analogy_receipt(value: object) -> HistoricalAnalogyReceipt:
    if type(value) is not HistoricalAnalogyReceipt:
        raise TypeError("historical analogy receipt winner type differs")
    return HistoricalAnalogyReceipt.validated_copy(value)


def _exact_path_definition(value: object) -> ScenarioPathDefinition:
    if type(value) is not ScenarioPathDefinition:
        raise TypeError("scenario path definition is unavailable")
    return ScenarioPathDefinition.validated_copy(value)


def _exact_path_raw_source(value: object) -> ScenarioPathRawSource:
    if type(value) is not ScenarioPathRawSource:
        raise TypeError("scenario path raw source is unavailable")
    return ScenarioPathRawSource.validated_copy(value)


def _exact_path_receipt(value: object) -> ScenarioPathReceipt:
    if type(value) is not ScenarioPathReceipt:
        raise TypeError("scenario path receipt winner type differs")
    return ScenarioPathReceipt.validated_copy(value)


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be a non-empty exact token")
    return value


def _aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


__all__ = [
    "HistoricalAnalogyDefinitionSource",
    "HistoricalAnalogyRawSourceProvider",
    "R7AnalogyPathOwnerClock",
    "R7AnalogyPathOwnerUnavailable",
    "RegisterHistoricalAnalogyDefinition",
    "RegisterHistoricalAnalogyDefinitionCommand",
    "RegisterHistoricalAnalogyReceipt",
    "RegisterHistoricalAnalogyReceiptCommand",
    "RegisterScenarioPathDefinition",
    "RegisterScenarioPathDefinitionCommand",
    "RegisterScenarioPathReceipt",
    "RegisterScenarioPathReceiptCommand",
    "ScenarioPathDefinitionSource",
    "ScenarioPathRawSourceProvider",
]
