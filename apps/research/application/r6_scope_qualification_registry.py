"""ID-only registration for the canonical R6 scope-qualification owner."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r6_scope_qualification_registry import (
    R6ScopeQualificationBindingDefinition,
    R6ScopeQualificationSourceReceipt,
)


class R6ScopeQualificationRegistryUnavailable(RuntimeError):
    """The binding definition, source, clock, or UoW is unavailable."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""


class R6ScopeQualificationDefinitionProvider(_UowBound, Protocol):
    """Independent Research binding-definition source."""

    def get_exact(
        self,
        *,
        binding_id: str,
        binding_version: str,
        as_of: datetime,
    ) -> R6ScopeQualificationBindingDefinition | None:
        """Return one exact definition by identity and cutoff."""


class R6ScopeQualificationSourceProvider(_UowBound, Protocol):
    """Independent Research receipt source for one exact definition."""

    def get_exact(
        self,
        *,
        binding_id: str,
        binding_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R6ScopeQualificationSourceReceipt | None:
        """Return one source receipt bound to the exact definition."""


class R6ScopeQualificationRegistryStore(_UowBound, Protocol):
    """Private append authority retained outside production composition."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared owner transaction."""

    def append(
        self,
        *,
        definition: R6ScopeQualificationBindingDefinition,
        source: R6ScopeQualificationSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R6ScopeQualificationBindingDefinition:
        """Append or replay one exact definition winner."""


class R6ScopeQualificationRegistryClock(_UowBound, Protocol):
    """Trusted server clock inside the shared UoW."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


@dataclass(frozen=True)
class RegisterR6ScopeQualificationBindingCommand:
    """Binding identity only; no scope, qualification, source, or clock."""

    binding_id: str
    binding_version: str

    def __post_init__(self) -> None:
        _token(self.binding_id, "R6 binding registration binding_id")
        _token(self.binding_version, "R6 binding registration binding_version")


class RegisterR6ScopeQualificationBinding:
    """Double-read the owner graph before one trusted append."""

    def __init__(
        self,
        *,
        definition_provider: R6ScopeQualificationDefinitionProvider,
        source_provider: R6ScopeQualificationSourceProvider,
        store: R6ScopeQualificationRegistryStore,
        clock: R6ScopeQualificationRegistryClock,
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
        self._participant_ids = tuple(id(item) for item in self._participants)
        self._expected_uow_key = _shared_uow(self._participants)

    def execute(
        self,
        command: RegisterR6ScopeQualificationBindingCommand,
    ) -> R6ScopeQualificationBindingDefinition:
        """Append only a stable owner graph; every failure remains zero-write."""

        try:
            _validate_command(command)
            self._require_unchanged()
            with self._store.atomic():
                self._require_unchanged()
                now = self._clock.now()
                _aware(now, "R6 binding trusted clock")
                first = self._read(command, now=now)
                self._require_unchanged()
                second = self._read(command, now=now)
                self._require_unchanged()
                if first != second:
                    raise R6ScopeQualificationRegistryUnavailable(
                        "R6 binding owner graph changed during reread"
                    )
                definition, source = second
                result = self._store.append(
                    definition=definition,
                    source=source,
                    ledger_recorded_at=now,
                )
                self._require_unchanged()
                if type(result) is not R6ScopeQualificationBindingDefinition:
                    raise TypeError("R6 binding store returned another type")
                canonical = R6ScopeQualificationBindingDefinition.validated_copy(result)
                if canonical != definition:
                    raise ValueError("R6 binding winner differs")
                return canonical
        except R6ScopeQualificationRegistryUnavailable:
            raise
        except Exception as error:
            raise R6ScopeQualificationRegistryUnavailable(
                "R6 scope-qualification registration is unavailable"
            ) from error

    def _read(
        self,
        command: RegisterR6ScopeQualificationBindingCommand,
        *,
        now: datetime,
    ) -> tuple[
        R6ScopeQualificationBindingDefinition,
        R6ScopeQualificationSourceReceipt,
    ]:
        definition_value = self._definition_provider.get_exact(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            as_of=now,
        )
        if type(definition_value) is not R6ScopeQualificationBindingDefinition:
            raise TypeError("R6 binding definition is unavailable")
        definition = R6ScopeQualificationBindingDefinition.validated_copy(definition_value)
        if not (
            definition.binding_id == command.binding_id
            and definition.binding_version == command.binding_version
            and definition.effective_at <= now < definition.valid_until
        ):
            raise ValueError("R6 binding definition identity or window differs")
        source_value = self._source_provider.get_exact(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        if type(source_value) is not R6ScopeQualificationSourceReceipt:
            raise TypeError("R6 binding source receipt is unavailable")
        source = R6ScopeQualificationSourceReceipt.validated_copy(source_value)
        if not (
            source.binding_id == command.binding_id
            and source.binding_version == command.binding_version
            and source.definition_hash == definition.content_hash
            and source.available_at <= now < source.valid_until
            and source.valid_until >= definition.valid_until
        ):
            raise ValueError("R6 binding source receipt differs")
        return definition, source

    def _require_unchanged(self) -> None:
        current: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if tuple(id(item) for item in current) != self._participant_ids:
            raise R6ScopeQualificationRegistryUnavailable(
                "R6 binding registry participant was replaced"
            )
        if _shared_uow(current) != self._expected_uow_key:
            raise R6ScopeQualificationRegistryUnavailable(
                "R6 binding registry UoW identity changed"
            )


def _validate_command(command: object) -> None:
    try:
        if type(command) is not RegisterR6ScopeQualificationBindingCommand:
            raise TypeError("R6 binding command type differs")
        RegisterR6ScopeQualificationBindingCommand.__post_init__(command)
        rebuilt = RegisterR6ScopeQualificationBindingCommand(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R6ScopeQualificationRegistryUnavailable(
            "R6 binding registration command is malformed"
        ) from error
    if rebuilt != command:
        raise R6ScopeQualificationRegistryUnavailable("R6 binding command failed live validation")


def _shared_uow(participants: tuple[_UowBound, ...]) -> str:
    keys = {_uow_key(item) for item in participants}
    if len(keys) != 1:
        raise R6ScopeQualificationRegistryUnavailable(
            "R6 binding owners use different units of work"
        )
    return next(iter(keys))


def _uow_key(value: _UowBound) -> str:
    return _token(value.unit_of_work_key, "R6 binding UoW key")


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


__all__ = [
    "R6ScopeQualificationDefinitionProvider",
    "R6ScopeQualificationRegistryClock",
    "R6ScopeQualificationRegistryStore",
    "R6ScopeQualificationRegistryUnavailable",
    "R6ScopeQualificationSourceProvider",
    "RegisterR6ScopeQualificationBinding",
    "RegisterR6ScopeQualificationBindingCommand",
]
