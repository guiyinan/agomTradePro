"""ID-only registration and materialization for canonical historical assignments."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.regime.domain.historical_assignment import (
    CanonicalRegimeSourceFact,
    HistoricalRegimeAssignmentDefinition,
    HistoricalRegimeAssignmentReceipt,
    PersistedHistoricalRegimeAssignmentDefinition,
    RegimeArtifactOOSProjection,
)


class HistoricalRegimeAssignmentUnavailable(RuntimeError):
    """A canonical owner, shared UoW, clock, or immutable record is unavailable."""


class HistoricalRegimeAssignmentConflict(HistoricalRegimeAssignmentUnavailable):
    """One immutable identity has conflicting evidence."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one exact database/snapshot identity."""


class ExactHistoricalRegimeAssignmentDefinitionOwner(_UowBound, Protocol):
    """Read a Regime-owner definition without accepting its body from a caller."""

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> HistoricalRegimeAssignmentDefinition | None:
        """Return the exact live owner definition known at the cutoff."""


class ExactHistoricalRegimeAssignmentDefinitionRepository(_UowBound, Protocol):
    """Read a persisted Regime definition receipt at an exact PIT cutoff."""

    def get_exact_definition(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedHistoricalRegimeAssignmentDefinition | None:
        """Return one exact active definition receipt or ``None``."""


class ExactRegimeArtifactOOSProvider(_UowBound, Protocol):
    """Read the narrow canonical Macro Factor OOS artifact projection."""

    def get_exact_projection(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> RegimeArtifactOOSProjection | None:
        """Return exact OOS predictions or ``None`` without filling evidence."""


class ExactCanonicalRegimeSourceFactProvider(_UowBound, Protocol):
    """Read Data Center PIT facts selected by a Regime owner definition."""

    def get_exact_facts(
        self,
        *,
        definition: HistoricalRegimeAssignmentDefinition,
        as_of: datetime,
    ) -> tuple[CanonicalRegimeSourceFact, ...] | None:
        """Return exhaustive exact facts or ``None`` without latest guessing."""


class HistoricalRegimeAssignmentStore(_UowBound, Protocol):
    """Private append capability retained only by non-public registration graphs."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared atomic owner-read/write boundary."""

    def append_definition(
        self,
        value: PersistedHistoricalRegimeAssignmentDefinition,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        """Append or exactly replay one definition receipt."""

    def append_receipt(
        self,
        value: HistoricalRegimeAssignmentReceipt,
    ) -> HistoricalRegimeAssignmentReceipt:
        """Append or exactly replay one assignment receipt."""


class HistoricalRegimeAssignmentClock(_UowBound, Protocol):
    """Caller-independent trusted server clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


@dataclass(frozen=True, slots=True)
class RegisterHistoricalRegimeAssignmentDefinitionCommand:
    """Owner definition identity and expected seal only."""

    definition_id: str
    definition_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.definition_id, "definition registration definition_id")
        _token(self.definition_version, "definition registration definition_version")
        _digest(self.expected_content_hash, "definition registration expected_content_hash")
        _aware(self.as_of, "definition registration as_of")


@dataclass(frozen=True, slots=True)
class MaterializeHistoricalRegimeAssignmentCommand:
    """Definition identity and PIT cutoff only; no caller-authored assignments."""

    definition_id: str
    definition_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.definition_id, "assignment materialization definition_id")
        _token(self.definition_version, "assignment materialization definition_version")
        _digest(self.expected_content_hash, "assignment materialization expected_content_hash")
        _aware(self.as_of, "assignment materialization as_of")


class RegisterHistoricalRegimeAssignmentDefinition:
    """Register an exact Regime owner definition after four in-UoW rereads."""

    def __init__(
        self,
        *,
        definition_provider: ExactHistoricalRegimeAssignmentDefinitionOwner,
        store: HistoricalRegimeAssignmentStore,
        clock: HistoricalRegimeAssignmentClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._store = store
        self._clock = clock
        self._participant_seal = self._participants()
        self._expected_uow_key = _shared_uow_key(self._participant_seal)

    def execute(
        self,
        command: RegisterHistoricalRegimeAssignmentDefinitionCommand,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        """Append a definition receipt without accepting caller evidence or clocks."""

        _live_command(command, RegisterHistoricalRegimeAssignmentDefinitionCommand)
        try:
            self._require_live_uow()
            with self._store.atomic():
                self._require_live_uow()
                server_now = _aware(self._clock.now(), "definition registration server clock")
                self._require_live_uow()
                if command.as_of > server_now:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment definition cutoff is in the future"
                    )
                first = self._read_owner(command, as_of=command.as_of)
                second = self._read_owner(command, as_of=server_now)
                if first != second:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment definition owner graph changed before construction"
                    )
                record = PersistedHistoricalRegimeAssignmentDefinition.create(
                    definition=second,
                    ledger_recorded_at=server_now,
                )
                third = self._read_owner(command, as_of=server_now)
                if third != second:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment definition owner graph changed before append"
                    )
                self._require_live_uow()
                winner_value = self._store.append_definition(record)
                if type(winner_value) is not PersistedHistoricalRegimeAssignmentDefinition:
                    raise TypeError("historical assignment definition winner type differs")
                winner = winner_value.validated_copy()
                fourth = self._read_owner(command, as_of=server_now)
                self._require_live_uow()
                if fourth != second or winner != record:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment definition owner graph changed after append"
                    )
                return winner
        except (HistoricalRegimeAssignmentConflict, HistoricalRegimeAssignmentUnavailable):
            raise
        except Exception as error:
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment definition owner, clock, transaction, or store unavailable"
            ) from error

    def _read_owner(
        self,
        command: RegisterHistoricalRegimeAssignmentDefinitionCommand,
        *,
        as_of: datetime,
    ) -> HistoricalRegimeAssignmentDefinition:
        self._require_live_uow()
        value = self._definition_provider.get_exact(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            expected_content_hash=command.expected_content_hash,
            as_of=as_of,
        )
        self._require_live_uow()
        if value is None:
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment definition owner is unavailable"
            )
        if type(value) is not HistoricalRegimeAssignmentDefinition:
            raise TypeError("historical assignment definition owner type differs")
        definition = value.validated_copy()
        if (
            definition.definition_id != command.definition_id
            or definition.definition_version != command.definition_version
            or definition.content_hash != command.expected_content_hash.lower()
            or not definition.is_active_at(as_of)
        ):
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment definition identity or validity differs"
            )
        return definition

    def _participants(self) -> tuple[_UowBound, ...]:
        return (self._definition_provider, self._store, self._clock)

    def _require_live_uow(self) -> None:
        _require_participant_seal(
            self._participants(),
            self._participant_seal,
            self._expected_uow_key,
        )


@dataclass(frozen=True, slots=True)
class _MaterializationGraph:
    definition: PersistedHistoricalRegimeAssignmentDefinition
    artifact: RegimeArtifactOOSProjection
    facts: tuple[CanonicalRegimeSourceFact, ...]


class MaterializeHistoricalRegimeAssignment:
    """Materialize exhaustive assignments after complete four-way owner rereads."""

    def __init__(
        self,
        *,
        definition_repository: ExactHistoricalRegimeAssignmentDefinitionRepository,
        artifact_provider: ExactRegimeArtifactOOSProvider,
        fact_provider: ExactCanonicalRegimeSourceFactProvider,
        store: HistoricalRegimeAssignmentStore,
        clock: HistoricalRegimeAssignmentClock,
    ) -> None:
        self._definition_repository = definition_repository
        self._artifact_provider = artifact_provider
        self._fact_provider = fact_provider
        self._store = store
        self._clock = clock
        self._participant_seal = self._participants()
        self._expected_uow_key = _shared_uow_key(self._participant_seal)

    def execute(
        self,
        command: MaterializeHistoricalRegimeAssignmentCommand,
    ) -> HistoricalRegimeAssignmentReceipt:
        """Append one server-derived assignment receipt in a single shared UoW."""

        _live_command(command, MaterializeHistoricalRegimeAssignmentCommand)
        try:
            self._require_live_uow()
            with self._store.atomic():
                self._require_live_uow()
                server_now = _aware(self._clock.now(), "assignment materialization server clock")
                self._require_live_uow()
                if command.as_of > server_now:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment materialization cutoff is in the future"
                    )
                first = self._read_graph(command)
                second = self._read_graph(command)
                if first != second:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment owner graph changed before construction"
                    )
                receipt = HistoricalRegimeAssignmentReceipt.create(
                    definition_record=second.definition,
                    artifact=second.artifact,
                    facts=second.facts,
                    pit_as_of=command.as_of,
                    recorded_at=server_now,
                )
                third = self._read_graph(command)
                if third != second:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment owner graph changed before append"
                    )
                self._require_live_uow()
                winner_value = self._store.append_receipt(receipt)
                if type(winner_value) is not HistoricalRegimeAssignmentReceipt:
                    raise TypeError("historical assignment receipt winner type differs")
                winner = winner_value.validated_copy()
                fourth = self._read_graph(command)
                self._require_live_uow()
                if fourth != second or winner != receipt:
                    raise HistoricalRegimeAssignmentUnavailable(
                        "historical assignment owner graph changed after append"
                    )
                return winner
        except (HistoricalRegimeAssignmentConflict, HistoricalRegimeAssignmentUnavailable):
            raise
        except Exception as error:
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment owner, clock, transaction, or store unavailable"
            ) from error

    def _read_graph(
        self,
        command: MaterializeHistoricalRegimeAssignmentCommand,
    ) -> _MaterializationGraph:
        self._require_live_uow()
        definition_value = self._definition_repository.get_exact_definition(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        self._require_live_uow()
        if definition_value is None:
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment persisted definition is unavailable"
            )
        if type(definition_value) is not PersistedHistoricalRegimeAssignmentDefinition:
            raise TypeError("historical assignment persisted definition type differs")
        definition = definition_value.validated_copy()
        if (
            definition.definition.definition_id != command.definition_id
            or definition.definition.definition_version != command.definition_version
            or definition.definition.content_hash != command.expected_content_hash.lower()
            or not definition.is_active_at(command.as_of)
        ):
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment persisted definition identity differs"
            )
        artifact_value = self._artifact_provider.get_exact_projection(
            artifact_id=definition.definition.artifact_id,
            expected_artifact_hash=definition.definition.artifact_hash,
            as_of=command.as_of,
        )
        self._require_live_uow()
        if artifact_value is None:
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment artifact projection is unavailable"
            )
        if type(artifact_value) is not RegimeArtifactOOSProjection:
            raise TypeError("historical assignment artifact projection type differs")
        RegimeArtifactOOSProjection.__post_init__(artifact_value)
        facts_value = self._fact_provider.get_exact_facts(
            definition=definition.definition,
            as_of=command.as_of,
        )
        self._require_live_uow()
        if facts_value is None or type(facts_value) is not tuple:
            raise HistoricalRegimeAssignmentUnavailable(
                "historical assignment canonical facts are unavailable"
            )
        for fact in facts_value:
            if type(fact) is not CanonicalRegimeSourceFact:
                raise TypeError("historical assignment canonical fact type differs")
            CanonicalRegimeSourceFact.__post_init__(fact)
        return _MaterializationGraph(
            definition=definition,
            artifact=artifact_value,
            facts=facts_value,
        )

    def _participants(self) -> tuple[_UowBound, ...]:
        return (
            self._definition_repository,
            self._artifact_provider,
            self._fact_provider,
            self._store,
            self._clock,
        )

    def _require_live_uow(self) -> None:
        _require_participant_seal(
            self._participants(),
            self._participant_seal,
            self._expected_uow_key,
        )


def _live_command(command: object, expected_type: type[object]) -> None:
    try:
        if type(command) is not expected_type:
            raise TypeError("historical assignment command type differs")
        expected_type.__post_init__(command)  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError) as error:
        raise HistoricalRegimeAssignmentUnavailable(
            "historical assignment command is malformed"
        ) from error


def _shared_uow_key(participants: tuple[_UowBound, ...]) -> str:
    try:
        keys = tuple(_uow_key(item.unit_of_work_key) for item in participants)
    except Exception as error:
        raise HistoricalRegimeAssignmentUnavailable(
            "historical assignment shared unit of work is unavailable"
        ) from error
    if len(set(keys)) != 1:
        raise HistoricalRegimeAssignmentUnavailable(
            "historical assignment requires one shared unit of work"
        )
    return keys[0]


def _require_participant_seal(
    participants: tuple[_UowBound, ...],
    sealed: tuple[_UowBound, ...],
    expected_key: str,
) -> None:
    if len(participants) != len(sealed) or any(
        participant is not original
        for participant, original in zip(participants, sealed, strict=True)
    ):
        raise HistoricalRegimeAssignmentUnavailable(
            "historical assignment unit of work participant changed"
        )
    if any(_uow_key(item.unit_of_work_key) != expected_key for item in participants):
        raise HistoricalRegimeAssignmentUnavailable("historical assignment unit of work changed")


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be an exact bounded token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value.lower()


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _uow_key(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 192:
        raise ValueError("historical assignment unit_of_work_key must be exact")
    return value


__all__ = [
    "ExactCanonicalRegimeSourceFactProvider",
    "ExactHistoricalRegimeAssignmentDefinitionOwner",
    "ExactHistoricalRegimeAssignmentDefinitionRepository",
    "ExactRegimeArtifactOOSProvider",
    "HistoricalRegimeAssignmentClock",
    "HistoricalRegimeAssignmentConflict",
    "HistoricalRegimeAssignmentStore",
    "HistoricalRegimeAssignmentUnavailable",
    "MaterializeHistoricalRegimeAssignment",
    "MaterializeHistoricalRegimeAssignmentCommand",
    "RegisterHistoricalRegimeAssignmentDefinition",
    "RegisterHistoricalRegimeAssignmentDefinitionCommand",
]
