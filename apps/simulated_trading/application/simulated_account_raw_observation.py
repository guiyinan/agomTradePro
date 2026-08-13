"""Owner recording and exact read contracts for raw account observations."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
    validate_simulated_account_raw_observation_root,
    validate_simulated_account_raw_observation_successor,
)


def _require_token(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class SimulatedAccountRawObservationUnavailable(ValueError):
    """The exact owner observation is not knowable at the requested cutoff."""


class SimulatedAccountRawObservationConflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class SimulatedAccountRawObservationCorruption(ValueError):
    """A repository substituted or corrupted owner observation evidence."""


@dataclass(frozen=True, slots=True)
class PersistedSimulatedAccountRawObservation:
    """Pair one owner observation with its authoritative ingestion clock."""

    observation: SimulatedAccountRawObservation
    recorded_at: datetime

    def __post_init__(self) -> None:
        if type(self.observation) is not SimulatedAccountRawObservation:
            raise TypeError("observation must be an exact SimulatedAccountRawObservation")
        SimulatedAccountRawObservation.__post_init__(self.observation)
        _require_aware(self.recorded_at, "recorded_at")
        if not self.observation.observed_at <= self.recorded_at:
            raise ValueError("recorded_at cannot precede the owner observation")
        if self.recorded_at >= self.observation.valid_until:
            raise ValueError("recorded_at must precede observation validity")


@dataclass(frozen=True, slots=True)
class GetExactSimulatedAccountRawObservationCommand:
    """Select one immutable observation identity, hash, and PIT cutoff."""

    observation_id: str
    observation_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.observation_id, "observation_id")
        _require_token(self.observation_version, "observation_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentSimulatedAccountRawObservationCommand:
    """Select one exact expected observation and require the logical final head."""

    expected_observation: SimulatedAccountRawObservation
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_observation) is not SimulatedAccountRawObservation:
            raise TypeError("expected_observation must be an exact SimulatedAccountRawObservation")
        SimulatedAccountRawObservation.__post_init__(self.expected_observation)
        _require_aware(self.as_of, "as_of")


class SimulatedAccountRawObservationRepository(Protocol):
    """Append-only owner store with historical and logical-head reads."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None: ...

    def get_current_head(
        self,
        *,
        observation_id: str,
        row_pk: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None: ...

    def append(
        self,
        record: PersistedSimulatedAccountRawObservation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRawObservation: ...

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None: ...


class RecordSimulatedAccountRawObservation:
    """Record an exact observation built inside a trusted owner mutation UOW.

    ``observation_version`` is the owner transaction/outbox event identity. A
    retry reuses that version; another committed mutation must use a new one.
    """

    def __init__(self, repository: SimulatedAccountRawObservationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        observation: SimulatedAccountRawObservation,
    ) -> SimulatedAccountRawObservation:
        """Append or replay one exact first winner without rewriting owner facts."""

        checked_observation = _require_observation(observation)
        recorded_at = self._repository.now()
        _require_aware(recorded_at, "repository recorded_at")
        if recorded_at < checked_observation.observed_at:
            raise SimulatedAccountRawObservationCorruption(
                "repository clock precedes owner observation"
            )
        if recorded_at >= checked_observation.valid_until:
            raise SimulatedAccountRawObservationUnavailable(
                "owner observation expired before recording"
            )

        with self._repository.atomic():
            winner = self._repository.get_winner(
                observation_id=checked_observation.observation_id,
                observation_version=checked_observation.observation_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                observation_id=checked_observation.observation_id,
                row_pk=checked_observation.row_pk,
                as_of=recorded_at,
            )
            if winner is not None:
                checked_winner = _require_record(winner)
                checked_head = _require_record(head) if head is not None else None
                if checked_winner.observation != checked_observation:
                    raise SimulatedAccountRawObservationConflict(
                        "raw observation identity has another first winner"
                    )
                if checked_head != checked_winner:
                    raise SimulatedAccountRawObservationConflict(
                        "raw observation winner is no longer the logical head"
                    )
                return checked_winner.observation

            predecessor = _require_record(head).observation if head is not None else None
            if predecessor is None:
                validate_simulated_account_raw_observation_root(checked_observation)
            else:
                validate_simulated_account_raw_observation_successor(
                    predecessor,
                    checked_observation,
                )
            record = PersistedSimulatedAccountRawObservation(
                observation=checked_observation,
                recorded_at=recorded_at,
            )
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
                recorded_at=recorded_at,
            )
            checked_persisted = _require_record(persisted)
            if checked_persisted != record:
                raise SimulatedAccountRawObservationConflict(
                    "concurrent raw observation first winner differs"
                )
            return checked_persisted.observation


class GetExactSimulatedAccountRawObservation:
    """Read one exact historical owner observation."""

    def __init__(self, repository: SimulatedAccountRawObservationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactSimulatedAccountRawObservationCommand,
    ) -> SimulatedAccountRawObservation | None:
        """Return one exact PIT value, including an exact tombstone fact."""

        if type(command) is not GetExactSimulatedAccountRawObservationCommand:
            raise TypeError(
                "command must be an exact GetExactSimulatedAccountRawObservationCommand"
            )
        GetExactSimulatedAccountRawObservationCommand.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = _require_record(value)
        if (
            checked.observation.observation_id != command.observation_id
            or checked.observation.observation_version != command.observation_version
            or checked.observation.content_hash != command.expected_content_hash
        ):
            raise SimulatedAccountRawObservationCorruption(
                "exact raw observation selector substitution"
            )
        if not _record_is_knowable(checked, command.as_of):
            return None
        return checked.observation


class GetCurrentSimulatedAccountRawObservation:
    """Read only the exact logical final owner observation."""

    def __init__(self, repository: SimulatedAccountRawObservationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentSimulatedAccountRawObservationCommand,
    ) -> SimulatedAccountRawObservation | None:
        """Return the expected final head without predecessor fallback."""

        if type(command) is not GetCurrentSimulatedAccountRawObservationCommand:
            raise TypeError(
                "command must be an exact GetCurrentSimulatedAccountRawObservationCommand"
            )
        GetCurrentSimulatedAccountRawObservationCommand.__post_init__(command)
        expected = command.expected_observation
        exact = self._repository.get_exact_by_hash(
            observation_id=expected.observation_id,
            observation_version=expected.observation_version,
            expected_content_hash=expected.content_hash,
            as_of=command.as_of,
        )
        head = self._repository.get_current_head(
            observation_id=expected.observation_id,
            row_pk=expected.row_pk,
            as_of=command.as_of,
        )
        if exact is None or head is None:
            return None
        checked_exact = _require_record(exact)
        checked_head = _require_record(head)
        if checked_exact.observation != expected:
            raise SimulatedAccountRawObservationCorruption(
                "current raw observation selector substitution"
            )
        if checked_head != checked_exact:
            return None
        if not _record_is_knowable(checked_exact, command.as_of):
            return None
        return checked_exact.observation


def _require_observation(value: object) -> SimulatedAccountRawObservation:
    if type(value) is not SimulatedAccountRawObservation:
        raise TypeError("observation must be an exact SimulatedAccountRawObservation")
    SimulatedAccountRawObservation.__post_init__(value)
    return value


def _require_record(value: object) -> PersistedSimulatedAccountRawObservation:
    if type(value) is not PersistedSimulatedAccountRawObservation:
        raise SimulatedAccountRawObservationCorruption(
            "repository substituted the raw observation record type"
        )
    PersistedSimulatedAccountRawObservation.__post_init__(value)
    return value


def _record_is_knowable(
    record: PersistedSimulatedAccountRawObservation,
    as_of: datetime,
) -> bool:
    _require_aware(as_of, "as_of")
    return record.recorded_at <= as_of and record.observation.is_knowable_at(as_of)


__all__ = [
    "GetCurrentSimulatedAccountRawObservation",
    "GetCurrentSimulatedAccountRawObservationCommand",
    "GetExactSimulatedAccountRawObservation",
    "GetExactSimulatedAccountRawObservationCommand",
    "PersistedSimulatedAccountRawObservation",
    "RecordSimulatedAccountRawObservation",
    "SimulatedAccountRawObservationConflict",
    "SimulatedAccountRawObservationCorruption",
    "SimulatedAccountRawObservationRepository",
    "SimulatedAccountRawObservationUnavailable",
]
