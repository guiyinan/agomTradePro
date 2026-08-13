"""ID-only capture workflow for SimulatedTrading-owned account-row sources."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.simulated_trading.domain.simulated_account_row_source import (
    SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE,
    SIMULATED_ACCOUNT_ROW_SOURCE_OWNER,
    SIMULATED_ACCOUNT_ROW_SOURCE_OWNER_ASSIGNMENT_STATE,
    SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA,
    SimulatedAccountRowSource,
    validate_simulated_account_row_source_successor,
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


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an exact integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


class SimulatedAccountRowSourceUnavailable(ValueError):
    """Required exact owner-issued raw observation is unavailable."""


class SimulatedAccountRowSourceConflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class SimulatedAccountRowSourceCorruption(ValueError):
    """A provider or repository substituted source evidence."""


@dataclass(frozen=True, slots=True)
class SimulatedAccountRowSourceActor:
    """Server-authenticated human staff identity recording source evidence."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        _require_positive_integer(self.user_id, "user_id")
        _require_token(self.role, "role")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("simulated account row source actor must be human staff")


@dataclass(frozen=True, slots=True)
class ExactRawSimulatedAccountObservation:
    """Consumer-owned projection of one owner-issued raw row observation."""

    observation_id: str
    observation_version: str
    content_hash: str
    row_pk: int
    row_user_id: int | None
    raw_account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    is_present: bool
    is_tombstone: bool
    observed_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
            "raw_account_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        _require_positive_integer(self.row_pk, "row_pk")
        if self.row_user_id is not None and (
            type(self.row_user_id) is not int or self.row_user_id <= 0
        ):
            raise ValueError("row_user_id must be null or an exact positive integer")
        for field_name in ("is_active", "is_present", "is_tombstone"):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be an exact boolean")
        if self.is_present == self.is_tombstone:
            raise ValueError("is_present and is_tombstone must be exact opposites")
        for field_name in (
            "row_created_at",
            "row_updated_at",
            "observed_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("raw simulated account observation clock sequence is invalid")
        if self.observed_at >= self.valid_until:
            raise ValueError("raw simulated account observation validity is invalid")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the issued observation is current at one cutoff."""

        _require_aware(as_of, "as_of")
        return self.observed_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class PersistedSimulatedAccountRowSource:
    """Repository record pairing immutable source evidence with its actor."""

    source: SimulatedAccountRowSource
    captured_by: SimulatedAccountRowSourceActor

    def __post_init__(self) -> None:
        if type(self.source) is not SimulatedAccountRowSource:
            raise TypeError("source must be an exact SimulatedAccountRowSource")
        SimulatedAccountRowSource.__post_init__(self.source)
        if type(self.captured_by) is not SimulatedAccountRowSourceActor:
            raise TypeError("captured_by must be an exact SimulatedAccountRowSourceActor")
        SimulatedAccountRowSourceActor.__post_init__(self.captured_by)


@dataclass(frozen=True, slots=True)
class CaptureSimulatedAccountRowSourceCommand:
    """ID-only selector for one source revision and canonical account row."""

    source_id: str
    source_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )


@dataclass(frozen=True, slots=True)
class GetExactSimulatedAccountRowSourceCommand:
    """Exact source identity, hash, and historical PIT selector."""

    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentSimulatedAccountRowSourceCommand:
    """Closed selector for one exact live logical source head."""

    source_id: str
    source_version: str
    expected_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_user_id: int | None
    raw_account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    is_present: bool
    is_tombstone: bool
    observed_at: datetime
    recorded_at: datetime
    source_valid_until: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    owner_assignment_state: str
    as_of: datetime
    owner: str = SIMULATED_ACCOUNT_ROW_SOURCE_OWNER
    artifact_type: str = SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE
    schema: str = SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_account_type",
            "owner_assignment_state",
            "owner",
            "artifact_type",
            "schema",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )
        if self.row_user_id is not None and (
            type(self.row_user_id) is not int or self.row_user_id <= 0
        ):
            raise ValueError("row_user_id must be null or an exact positive integer")
        for field_name in ("is_active", "is_present", "is_tombstone"):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be an exact boolean")
        for field_name in (
            "row_created_at",
            "row_updated_at",
            "observed_at",
            "recorded_at",
            "source_valid_until",
            "ttl_valid_until",
            "valid_until",
            "as_of",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if (
            self.owner != SIMULATED_ACCOUNT_ROW_SOURCE_OWNER
            or self.artifact_type != SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE
            or self.schema != SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA
            or self.owner_assignment_state != SIMULATED_ACCOUNT_ROW_SOURCE_OWNER_ASSIGNMENT_STATE
        ):
            raise ValueError("simulated account row current selector authority is invalid")

    @classmethod
    def from_source(
        cls: type[GetCurrentSimulatedAccountRowSourceCommand],
        source: SimulatedAccountRowSource,
        *,
        as_of: datetime,
    ) -> GetCurrentSimulatedAccountRowSourceCommand:
        """Build a closed selector from trusted immutable source evidence."""

        if type(source) is not SimulatedAccountRowSource:
            raise TypeError("source must be an exact SimulatedAccountRowSource")
        SimulatedAccountRowSource.__post_init__(source)
        return cls(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            underlying_unified_account_namespace=source.underlying_unified_account_namespace,
            underlying_unified_account_id=source.underlying_unified_account_id,
            row_user_id=source.row_user_id,
            raw_account_type=source.raw_account_type,
            is_active=source.is_active,
            row_created_at=source.row_created_at,
            row_updated_at=source.row_updated_at,
            is_present=source.is_present,
            is_tombstone=source.is_tombstone,
            observed_at=source.observed_at,
            recorded_at=source.recorded_at,
            source_valid_until=source.source_valid_until,
            ttl_valid_until=source.ttl_valid_until,
            valid_until=source.valid_until,
            owner_assignment_state=source.owner_assignment_state,
            as_of=as_of,
        )


class ExactRawSimulatedAccountObservationProvider(Protocol):
    """Load one exact owner-issued raw SimulatedAccount observation."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        row_pk: int,
        as_of: datetime,
    ) -> ExactRawSimulatedAccountObservation | None:
        """Return typed source evidence without manufacturing clocks or hashes."""

        ...


class SimulatedAccountRowSourceRepository(Protocol):
    """First-winner store and exact inactive source read authority."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None: ...

    def get_current_head(
        self,
        *,
        source_id: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None: ...

    def append(
        self,
        record: PersistedSimulatedAccountRowSource,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRowSource: ...

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None: ...


class CaptureSimulatedAccountRowSource:
    """Capture one owner source from an exact typed raw observation."""

    def __init__(
        self,
        *,
        observation_provider: ExactRawSimulatedAccountObservationProvider,
        repository: SimulatedAccountRowSourceRepository,
        actor: SimulatedAccountRowSourceActor,
        validity_period: timedelta,
    ) -> None:
        if type(actor) is not SimulatedAccountRowSourceActor:
            raise TypeError("actor must be an exact SimulatedAccountRowSourceActor")
        SimulatedAccountRowSourceActor.__post_init__(actor)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._observation_provider = observation_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self,
        command: CaptureSimulatedAccountRowSourceCommand,
    ) -> SimulatedAccountRowSource:
        """Capture or replay one actor-bound source first winner."""

        if type(command) is not CaptureSimulatedAccountRowSourceCommand:
            raise TypeError("command must be an exact CaptureSimulatedAccountRowSourceCommand")
        CaptureSimulatedAccountRowSourceCommand.__post_init__(command)
        cutoff = self._repository.now()
        _require_aware(cutoff, "repository cutoff")
        first = self._read_observation(command, cutoff)
        with self._repository.atomic():
            winner = self._repository.get_winner(
                source_id=command.source_id,
                source_version=command.source_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                source_id=command.source_id,
                account_namespace=command.account_namespace,
                account_id=command.account_id,
                underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
                underlying_unified_account_id=command.underlying_unified_account_id,
                as_of=cutoff,
            )
            final = self._read_observation(command, cutoff)
            if final != first:
                raise SimulatedAccountRowSourceConflict(
                    "raw simulated account observation changed during capture"
                )
            if winner is not None:
                checked = self._require_record(winner)
                self._validate_winner(checked, command, final, head, cutoff)
                return checked.source
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "repository recorded_at")
            if recorded_at < cutoff:
                raise SimulatedAccountRowSourceCorruption("repository clock moved backwards")
            ttl_valid_until = cutoff + self._validity_period
            if recorded_at >= min(final.valid_until, ttl_valid_until):
                raise SimulatedAccountRowSourceUnavailable(
                    "raw simulated account observation expired before recording"
                )
            predecessor = self._require_record(head).source if head is not None else None
            source = self._build_source(
                command,
                final,
                recorded_at=recorded_at,
                ttl_valid_until=ttl_valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            if predecessor is not None:
                validate_simulated_account_row_source_successor(predecessor, source)
            record = PersistedSimulatedAccountRowSource(
                source=source,
                captured_by=self._actor,
            )
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
                recorded_at=recorded_at,
            )
            checked = self._require_record(persisted)
            if checked != record:
                raise SimulatedAccountRowSourceConflict(
                    "concurrent simulated account row source first winner differs"
                )
            return checked.source

    def _read_observation(
        self,
        command: CaptureSimulatedAccountRowSourceCommand,
        cutoff: datetime,
    ) -> ExactRawSimulatedAccountObservation:
        value = self._observation_provider.get_exact_current(
            observation_id=command.source_id,
            observation_version=command.source_version,
            row_pk=command.underlying_unified_account_id,
            as_of=cutoff,
        )
        return self._require_observation(value, command, cutoff)

    @staticmethod
    def _require_observation(
        value: ExactRawSimulatedAccountObservation | None,
        command: CaptureSimulatedAccountRowSourceCommand,
        cutoff: datetime,
    ) -> ExactRawSimulatedAccountObservation:
        if value is None:
            raise SimulatedAccountRowSourceUnavailable(
                "exact raw simulated account observation is unavailable"
            )
        if type(value) is not ExactRawSimulatedAccountObservation:
            raise SimulatedAccountRowSourceCorruption(
                "raw simulated account observation type substitution"
            )
        ExactRawSimulatedAccountObservation.__post_init__(value)
        if (
            value.observation_id != command.source_id
            or value.observation_version != command.source_version
            or value.row_pk != command.underlying_unified_account_id
        ):
            raise SimulatedAccountRowSourceCorruption(
                "raw simulated account observation identity substitution"
            )
        if not value.is_knowable_at(cutoff):
            raise SimulatedAccountRowSourceUnavailable(
                "exact raw simulated account observation is unavailable"
            )
        return value

    @staticmethod
    def _build_source(
        command: CaptureSimulatedAccountRowSourceCommand,
        observation: ExactRawSimulatedAccountObservation,
        *,
        recorded_at: datetime,
        ttl_valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> SimulatedAccountRowSource:
        return SimulatedAccountRowSource(
            source_id=command.source_id,
            source_version=command.source_version,
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=observation.row_pk,
            row_user_id=observation.row_user_id,
            raw_account_type=observation.raw_account_type,
            is_active=observation.is_active,
            row_created_at=observation.row_created_at,
            row_updated_at=observation.row_updated_at,
            is_present=observation.is_present,
            is_tombstone=observation.is_tombstone,
            observed_at=observation.observed_at,
            recorded_at=recorded_at,
            source_valid_until=observation.valid_until,
            ttl_valid_until=ttl_valid_until,
            valid_until=min(observation.valid_until, ttl_valid_until),
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        record: PersistedSimulatedAccountRowSource,
        command: CaptureSimulatedAccountRowSourceCommand,
        observation: ExactRawSimulatedAccountObservation,
        head: PersistedSimulatedAccountRowSource | None,
        cutoff: datetime,
    ) -> None:
        source = record.source
        if not source.is_knowable_at(cutoff):
            raise SimulatedAccountRowSourceUnavailable(
                "persisted simulated account row source is unavailable"
            )
        if record.captured_by != self._actor:
            raise SimulatedAccountRowSourceConflict(
                "simulated account row source belongs to another actor"
            )
        stable = self._build_source(
            command,
            observation,
            recorded_at=source.recorded_at,
            ttl_valid_until=source.ttl_valid_until,
            supersedes_content_hash=source.supersedes_content_hash,
        )
        if stable != source:
            raise SimulatedAccountRowSourceConflict(
                "simulated account row source identity has another first winner"
            )
        if head is None or self._require_record(head) != record:
            raise SimulatedAccountRowSourceConflict(
                "simulated account row source is no longer the logical current head"
            )

    @staticmethod
    def _require_record(value: object) -> PersistedSimulatedAccountRowSource:
        if type(value) is not PersistedSimulatedAccountRowSource:
            raise SimulatedAccountRowSourceCorruption("repository record type substitution")
        PersistedSimulatedAccountRowSource.__post_init__(value)
        return value


class GetExactSimulatedAccountRowSource:
    """Expose exact identity/hash historical reads of inactive source evidence."""

    def __init__(self, repository: SimulatedAccountRowSourceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactSimulatedAccountRowSourceCommand,
    ) -> SimulatedAccountRowSource | None:
        """Return exact evidence knowable at the requested PIT."""

        if type(command) is not GetExactSimulatedAccountRowSourceCommand:
            raise TypeError("command must be an exact GetExactSimulatedAccountRowSourceCommand")
        GetExactSimulatedAccountRowSourceCommand.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        source = CaptureSimulatedAccountRowSource._require_record(value).source
        if (
            source.source_id != command.source_id
            or source.source_version != command.source_version
            or source.content_hash != command.expected_content_hash
        ):
            raise SimulatedAccountRowSourceCorruption(
                "exact simulated account row source identity substitution"
            )
        if not source.is_knowable_at(command.as_of):
            return None
        if source.activation_available or not source.must_not_execute:
            raise SimulatedAccountRowSourceCorruption(
                "simulated account row source execution state substitution"
            )
        return source


class GetCurrentSimulatedAccountRowSource:
    """Return one exact live source at the final inactive-evidence head."""

    def __init__(self, repository: SimulatedAccountRowSourceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentSimulatedAccountRowSourceCommand,
    ) -> SimulatedAccountRowSource | None:
        """Use a closed selector and never fall back from a final bad head."""

        if type(command) is not GetCurrentSimulatedAccountRowSourceCommand:
            raise TypeError("command must be an exact GetCurrentSimulatedAccountRowSourceCommand")
        GetCurrentSimulatedAccountRowSourceCommand.__post_init__(command)
        source = GetExactSimulatedAccountRowSource(self._repository).execute(
            GetExactSimulatedAccountRowSourceCommand(
                source_id=command.source_id,
                source_version=command.source_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if source is None or _source_selectors(source) != _command_selectors(command):
            return None
        head = self._repository.get_current_head(
            source_id=command.source_id,
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if head is None or CaptureSimulatedAccountRowSource._require_record(head).source != source:
            return None
        return source if source.is_current_at(command.as_of) else None


def _source_selectors(source: SimulatedAccountRowSource) -> tuple[object, ...]:
    return (
        source.owner,
        source.artifact_type,
        source.schema,
        source.account_namespace,
        source.account_id,
        source.underlying_unified_account_namespace,
        source.underlying_unified_account_id,
        source.row_user_id,
        source.raw_account_type,
        source.is_active,
        source.row_created_at,
        source.row_updated_at,
        source.is_present,
        source.is_tombstone,
        source.observed_at,
        source.recorded_at,
        source.source_valid_until,
        source.ttl_valid_until,
        source.valid_until,
        source.owner_assignment_state,
    )


def _command_selectors(
    command: GetCurrentSimulatedAccountRowSourceCommand,
) -> tuple[object, ...]:
    return (
        command.owner,
        command.artifact_type,
        command.schema,
        command.account_namespace,
        command.account_id,
        command.underlying_unified_account_namespace,
        command.underlying_unified_account_id,
        command.row_user_id,
        command.raw_account_type,
        command.is_active,
        command.row_created_at,
        command.row_updated_at,
        command.is_present,
        command.is_tombstone,
        command.observed_at,
        command.recorded_at,
        command.source_valid_until,
        command.ttl_valid_until,
        command.valid_until,
        command.owner_assignment_state,
    )


__all__ = [
    "CaptureSimulatedAccountRowSource",
    "CaptureSimulatedAccountRowSourceCommand",
    "ExactRawSimulatedAccountObservation",
    "ExactRawSimulatedAccountObservationProvider",
    "GetCurrentSimulatedAccountRowSource",
    "GetCurrentSimulatedAccountRowSourceCommand",
    "GetExactSimulatedAccountRowSource",
    "GetExactSimulatedAccountRowSourceCommand",
    "PersistedSimulatedAccountRowSource",
    "SimulatedAccountRowSourceActor",
    "SimulatedAccountRowSourceConflict",
    "SimulatedAccountRowSourceCorruption",
    "SimulatedAccountRowSourceRepository",
    "SimulatedAccountRowSourceUnavailable",
]
