"""ID-only registration and read ports for canonical R3 PIT sources."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.data_center.domain.macro_factor_research_source import (
    CanonicalMacroFactorPITProjection,
    MacroFactorResearchSourceDefinition,
    PersistedMacroFactorResearchSourceDefinition,
)


class MacroFactorResearchSourceUnavailable(RuntimeError):
    """A canonical owner, trusted clock, shared UoW, or strict row is unavailable."""


class MacroFactorResearchSourceConflict(RuntimeError):
    """One immutable source identity has conflicting evidence."""


class ExactMacroFactorResearchSourceDefinitionOwner(Protocol):
    """Read an owner-authored source definition without accepting its body."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared registration transaction identity."""

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> MacroFactorResearchSourceDefinition | None:
        """Return the exact live owner definition known at the cutoff."""


class MacroFactorResearchSourceStore(Protocol):
    """Private append capability kept out of production runtime graphs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared registration transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared atomic owner-read/write boundary."""

    def append_source_definition(
        self,
        record: PersistedMacroFactorResearchSourceDefinition,
    ) -> PersistedMacroFactorResearchSourceDefinition:
        """Append or exactly replay one immutable definition receipt."""


class MacroFactorResearchSourceClock(Protocol):
    """Caller-independent server clock for the append-only ledger."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared registration transaction identity."""

    def now(self) -> datetime:
        """Return one timezone-aware trusted server time."""


class ExactMacroFactorResearchSourceRepository(Protocol):
    """Exact PIT reads over persisted source definitions."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database/snapshot identity."""

    def get_exact_source_definition(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedMacroFactorResearchSourceDefinition | None:
        """Return one exact active source definition at the PIT cutoff."""


class ExactMacroFactorPITProjectionProvider(Protocol):
    """Strictly rebuild one R3 projection from Data Center owner rows."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database/snapshot identity."""

    def get_exact_projection(
        self,
        *,
        manifest_id: str,
        expected_manifest_hash: str | None = None,
    ) -> CanonicalMacroFactorPITProjection | None:
        """Return a complete projection or ``None`` without filling missing evidence."""


@dataclass(frozen=True)
class RegisterMacroFactorResearchSourceCommand:
    """Identity and expected seal only; no caller-authored definition body."""

    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.source_id, "macro-factor registration source_id")
        _require_token(self.source_version, "macro-factor registration source_version")
        _require_hash(
            self.expected_content_hash,
            "macro-factor registration expected_content_hash",
        )
        _require_aware(self.as_of, "macro-factor registration as_of")


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one exact UoW key."""


class RegisterMacroFactorResearchSource:
    """Register an owner definition after complete in-UoW live rereads."""

    def __init__(
        self,
        *,
        definition_provider: ExactMacroFactorResearchSourceDefinitionOwner,
        store: MacroFactorResearchSourceStore,
        clock: MacroFactorResearchSourceClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._store = store
        self._clock = clock
        self._participant_seal = self._current_participants()
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source shared unit of work is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source registration requires one shared unit of work"
            )
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: RegisterMacroFactorResearchSourceCommand,
    ) -> PersistedMacroFactorResearchSourceDefinition:
        """Append one exact definition without accepting caller evidence or clocks."""

        _require_live_command(command)
        try:
            self._require_live_uow()
            with self._store.atomic():
                self._require_live_uow()
                server_now = _require_aware(
                    self._clock.now(),
                    "macro-factor registration server clock",
                )
                self._require_live_uow()
                if command.as_of > server_now:
                    raise MacroFactorResearchSourceUnavailable(
                        "macro-factor registration cutoff is in the future"
                    )
                first = self._read_owner(command, as_of=command.as_of)
                second = self._read_owner(command, as_of=server_now)
                if first != second:
                    raise MacroFactorResearchSourceUnavailable(
                        "macro-factor source owner graph changed before construction"
                    )
                record = PersistedMacroFactorResearchSourceDefinition.create(
                    definition=second,
                    ledger_recorded_at=server_now,
                )
                third = self._read_owner(command, as_of=server_now)
                if third != second:
                    raise MacroFactorResearchSourceUnavailable(
                        "macro-factor source owner graph changed before append"
                    )
                self._require_live_uow()
                winner_value = self._store.append_source_definition(record)
                if type(winner_value) is not PersistedMacroFactorResearchSourceDefinition:
                    raise TypeError("macro-factor source winner type differs")
                winner = winner_value.validated_copy()
                fourth = self._read_owner(command, as_of=server_now)
                self._require_live_uow()
                if fourth != second or winner != record:
                    raise MacroFactorResearchSourceUnavailable(
                        "macro-factor source owner graph changed after append"
                    )
                return winner
        except (MacroFactorResearchSourceConflict, MacroFactorResearchSourceUnavailable):
            raise
        except Exception as error:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source owner, clock, transaction, or store is unavailable"
            ) from error

    def _read_owner(
        self,
        command: RegisterMacroFactorResearchSourceCommand,
        *,
        as_of: datetime,
    ) -> MacroFactorResearchSourceDefinition:
        self._require_live_uow()
        value = self._definition_provider.get_exact(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=as_of,
        )
        self._require_live_uow()
        if value is None:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source owner definition is unavailable"
            )
        if type(value) is not MacroFactorResearchSourceDefinition:
            raise TypeError("macro-factor source owner definition type differs")
        definition = value.validated_copy()
        if (
            definition.source_id != command.source_id
            or definition.source_version != command.source_version
            or definition.content_hash.lower() != command.expected_content_hash.lower()
            or not definition.is_active_at(as_of)
        ):
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source owner definition identity or validity differs"
            )
        return definition

    def _current_uow_keys(self) -> tuple[str, ...]:
        return tuple(
            _exact_uow_key(participant.unit_of_work_key)
            for participant in self._current_participants()
        )

    def _current_participants(self) -> tuple[_UnitOfWorkBound, ...]:
        return (self._definition_provider, self._store, self._clock)

    def _require_live_uow(self) -> None:
        participants = self._current_participants()
        if any(
            participant is not sealed
            for participant, sealed in zip(
                participants,
                self._participant_seal,
                strict=True,
            )
        ):
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source unit of work participant changed"
            )
        keys = tuple(_exact_uow_key(participant.unit_of_work_key) for participant in participants)
        if any(key != self._expected_uow_key for key in keys):
            raise MacroFactorResearchSourceUnavailable("macro-factor source unit of work changed")


def _require_live_command(command: object) -> None:
    try:
        if type(command) is not RegisterMacroFactorResearchSourceCommand:
            raise TypeError("macro-factor registration command type differs")
        RegisterMacroFactorResearchSourceCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise MacroFactorResearchSourceUnavailable(
            "macro-factor source registration command is malformed"
        ) from error


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 192:
        raise ValueError("macro-factor source unit_of_work_key must be exact")
    return value


def _require_token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact bounded token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return value.lower()


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


__all__ = [
    "ExactMacroFactorPITProjectionProvider",
    "ExactMacroFactorResearchSourceDefinitionOwner",
    "ExactMacroFactorResearchSourceRepository",
    "MacroFactorResearchSourceClock",
    "MacroFactorResearchSourceConflict",
    "MacroFactorResearchSourceStore",
    "MacroFactorResearchSourceUnavailable",
    "RegisterMacroFactorResearchSource",
    "RegisterMacroFactorResearchSourceCommand",
]
