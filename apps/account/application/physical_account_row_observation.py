"""ID-only capture workflow for Account-owned physical-row evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.physical_account_row_observation import (
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA,
    PHYSICAL_ACCOUNT_ROW_OWNER_ASSIGNMENT_STATE,
    PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE,
    PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER,
    PhysicalAccountRowObservation,
    validate_physical_account_row_observation_successor,
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


class PhysicalAccountRowObservationUnavailable(ValueError):
    """Required exact-current physical row evidence is unavailable."""


class PhysicalAccountRowObservationConflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class PhysicalAccountRowObservationCorruption(ValueError):
    """A provider or repository returned substituted physical row evidence."""


@dataclass(frozen=True, slots=True)
class PhysicalAccountRowObservationActor:
    """Server-authenticated human staff identity recording physical evidence."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _require_token(self.role, "role")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("physical account row observation actor must be human staff")


@dataclass(frozen=True, slots=True)
class ExactPhysicalSimulatedAccountRow:
    """Consumer-owned exact projection of one physical SimulatedAccount row."""

    source_id: str
    source_version: str
    content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_user_id: int | None
    account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    observed_at: datetime
    valid_until: datetime
    owner: str = PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER
    artifact_type: str = PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "account_type",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )
        if self.row_user_id is not None and (
            type(self.row_user_id) is not int or self.row_user_id <= 0
        ):
            raise ValueError("row_user_id must be null or an exact positive integer")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        for field_name in (
            "row_created_at",
            "row_updated_at",
            "observed_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("physical simulated account row clock sequence is invalid")
        if self.observed_at >= self.valid_until:
            raise ValueError("physical simulated account row validity is invalid")
        if (
            self.owner != PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER
            or self.artifact_type != PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("physical simulated account row authority is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact physical row is current at one cutoff."""

        _require_aware(as_of, "as_of")
        return self.observed_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class PersistedPhysicalAccountRowObservation:
    """Repository record pairing immutable evidence with its server actor."""

    observation: PhysicalAccountRowObservation
    captured_by: PhysicalAccountRowObservationActor

    def __post_init__(self) -> None:
        if type(self.observation) is not PhysicalAccountRowObservation:
            raise TypeError("observation must be an exact PhysicalAccountRowObservation")
        PhysicalAccountRowObservation.__post_init__(self.observation)
        if type(self.captured_by) is not PhysicalAccountRowObservationActor:
            raise TypeError("captured_by must be an exact PhysicalAccountRowObservationActor")
        PhysicalAccountRowObservationActor.__post_init__(self.captured_by)


@dataclass(frozen=True, slots=True)
class CapturePhysicalAccountRowObservationCommand:
    """ID-only selector for one Account identity and exact physical source row."""

    observation_id: str
    observation_version: str
    raw_source_id: str
    raw_source_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
            "raw_source_id",
            "raw_source_version",
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
class GetExactPhysicalAccountRowObservationCommand:
    """Exact identity, content-hash, and historical PIT selector."""

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
class GetCurrentPhysicalAccountRowObservationCommand:
    """Closed selector for one exact active physical-row logical head."""

    observation_id: str
    observation_version: str
    expected_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    raw_source_owner: str
    raw_source_artifact_type: str
    raw_source_id: str
    raw_source_version: str
    raw_source_content_hash: str
    row_user_id: int | None
    account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    observed_at: datetime
    recorded_at: datetime
    raw_source_valid_until: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    owner_assignment_state: str
    as_of: datetime
    owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER
    artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE
    schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_source_owner",
            "raw_source_artifact_type",
            "raw_source_id",
            "raw_source_version",
            "account_type",
            "owner_assignment_state",
            "owner",
            "artifact_type",
            "schema",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_hash(self.raw_source_content_hash, "raw_source_content_hash")
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )
        if self.row_user_id is not None and (
            type(self.row_user_id) is not int or self.row_user_id <= 0
        ):
            raise ValueError("row_user_id must be null or an exact positive integer")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        for field_name in (
            "row_created_at",
            "row_updated_at",
            "observed_at",
            "recorded_at",
            "raw_source_valid_until",
            "ttl_valid_until",
            "valid_until",
            "as_of",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if (
            self.owner != PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER
            or self.artifact_type != PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE
            or self.schema != PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA
            or self.owner_assignment_state != PHYSICAL_ACCOUNT_ROW_OWNER_ASSIGNMENT_STATE
            or self.raw_source_owner != PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER
            or self.raw_source_artifact_type != PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("physical account row current selector authority is invalid")

    @classmethod
    def from_observation(
        cls: type[GetCurrentPhysicalAccountRowObservationCommand],
        observation: PhysicalAccountRowObservation,
        *,
        as_of: datetime,
    ) -> GetCurrentPhysicalAccountRowObservationCommand:
        """Build a closed current selector from trusted immutable evidence."""

        if type(observation) is not PhysicalAccountRowObservation:
            raise TypeError("observation must be an exact PhysicalAccountRowObservation")
        PhysicalAccountRowObservation.__post_init__(observation)
        return cls(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            account_namespace=observation.account_namespace,
            account_id=observation.account_id,
            underlying_unified_account_namespace=(observation.underlying_unified_account_namespace),
            underlying_unified_account_id=observation.underlying_unified_account_id,
            raw_source_owner=observation.raw_source_owner,
            raw_source_artifact_type=observation.raw_source_artifact_type,
            raw_source_id=observation.raw_source_id,
            raw_source_version=observation.raw_source_version,
            raw_source_content_hash=observation.raw_source_content_hash,
            row_user_id=observation.row_user_id,
            account_type=observation.account_type,
            is_active=observation.is_active,
            row_created_at=observation.row_created_at,
            row_updated_at=observation.row_updated_at,
            observed_at=observation.observed_at,
            recorded_at=observation.recorded_at,
            raw_source_valid_until=observation.raw_source_valid_until,
            ttl_valid_until=observation.ttl_valid_until,
            valid_until=observation.valid_until,
            owner_assignment_state=observation.owner_assignment_state,
            as_of=as_of,
        )


class ExactPhysicalSimulatedAccountRowProvider(Protocol):
    """Load one exact-current physical SimulatedAccount row projection."""

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRow | None:
        """Return the exact source row at one Account server cutoff."""

        ...


class PhysicalAccountRowObservationRepository(Protocol):
    """First-winner store and exact inactive physical-row read authority."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one first-winner transaction."""

        ...

    def now(self) -> datetime:
        """Return the authoritative Account server clock."""

        ...

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        """Return the immutable first winner for one observation identity."""

        ...

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        raw_source_id: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        """Return the final logical head without expiry or active fallback."""

        ...

    def append(
        self,
        record: PersistedPhysicalAccountRowObservation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedPhysicalAccountRowObservation:
        """Append under first-winner and predecessor-CAS semantics."""

        ...

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        """Return exact identity/hash evidence knowable at one historical PIT."""

        ...


class CapturePhysicalAccountRowObservation:
    """Capture inactive Account evidence from one exact physical row provider."""

    def __init__(
        self,
        *,
        row_provider: ExactPhysicalSimulatedAccountRowProvider,
        repository: PhysicalAccountRowObservationRepository,
        actor: PhysicalAccountRowObservationActor,
        validity_period: timedelta,
    ) -> None:
        if type(actor) is not PhysicalAccountRowObservationActor:
            raise TypeError("actor must be an exact PhysicalAccountRowObservationActor")
        PhysicalAccountRowObservationActor.__post_init__(actor)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._row_provider = row_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self,
        command: CapturePhysicalAccountRowObservationCommand,
    ) -> PhysicalAccountRowObservation:
        """Capture or replay one actor-bound physical-row first winner."""

        if type(command) is not CapturePhysicalAccountRowObservationCommand:
            raise TypeError("command must be an exact CapturePhysicalAccountRowObservationCommand")
        CapturePhysicalAccountRowObservationCommand.__post_init__(command)
        cutoff = self._repository.now()
        _require_aware(cutoff, "repository cutoff")
        first = self._read_row(command, cutoff)
        with self._repository.atomic():
            winner = self._repository.get_winner(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                account_namespace=command.account_namespace,
                account_id=command.account_id,
                underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
                underlying_unified_account_id=command.underlying_unified_account_id,
                raw_source_id=command.raw_source_id,
                as_of=cutoff,
            )
            final = self._read_row(command, cutoff)
            if final != first:
                raise PhysicalAccountRowObservationConflict(
                    "physical source row changed during capture"
                )
            if winner is not None:
                checked = self._require_record(winner)
                self._validate_winner(checked, command, final, head, cutoff)
                return checked.observation
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "repository recorded_at")
            if recorded_at < cutoff:
                raise PhysicalAccountRowObservationCorruption("repository clock moved backwards")
            ttl_valid_until = cutoff + self._validity_period
            if recorded_at >= min(final.valid_until, ttl_valid_until):
                raise PhysicalAccountRowObservationUnavailable(
                    "physical source row expired before it could be recorded"
                )
            predecessor = self._require_record(head).observation if head is not None else None
            observation = self._build_observation(
                command,
                final,
                recorded_at=recorded_at,
                ttl_valid_until=ttl_valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            if predecessor is not None:
                validate_physical_account_row_observation_successor(
                    predecessor,
                    observation,
                )
            record = PersistedPhysicalAccountRowObservation(
                observation=observation,
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
                raise PhysicalAccountRowObservationConflict(
                    "concurrent physical account row first winner differs"
                )
            return checked.observation

    def _read_row(
        self,
        command: CapturePhysicalAccountRowObservationCommand,
        cutoff: datetime,
    ) -> ExactPhysicalSimulatedAccountRow:
        value = self._row_provider.get_exact_current(
            source_id=command.raw_source_id,
            source_version=command.raw_source_version,
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
            as_of=cutoff,
        )
        return self._require_row(value, command, cutoff)

    @staticmethod
    def _require_row(
        value: ExactPhysicalSimulatedAccountRow | None,
        command: CapturePhysicalAccountRowObservationCommand,
        cutoff: datetime,
    ) -> ExactPhysicalSimulatedAccountRow:
        if value is None:
            raise PhysicalAccountRowObservationUnavailable(
                "exact current physical simulated account row is unavailable"
            )
        if type(value) is not ExactPhysicalSimulatedAccountRow:
            raise PhysicalAccountRowObservationCorruption(
                "physical simulated account row type substitution"
            )
        ExactPhysicalSimulatedAccountRow.__post_init__(value)
        if (
            value.source_id != command.raw_source_id
            or value.source_version != command.raw_source_version
            or value.account_namespace != command.account_namespace
            or value.account_id != command.account_id
            or value.underlying_unified_account_namespace
            != command.underlying_unified_account_namespace
            or value.underlying_unified_account_id != command.underlying_unified_account_id
        ):
            raise PhysicalAccountRowObservationCorruption(
                "physical simulated account row identity substitution"
            )
        if not value.is_current_at(cutoff):
            raise PhysicalAccountRowObservationUnavailable(
                "exact current physical simulated account row is unavailable"
            )
        return value

    @staticmethod
    def _build_observation(
        command: CapturePhysicalAccountRowObservationCommand,
        row: ExactPhysicalSimulatedAccountRow,
        *,
        recorded_at: datetime,
        ttl_valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> PhysicalAccountRowObservation:
        return PhysicalAccountRowObservation(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            account_namespace=row.account_namespace,
            account_id=row.account_id,
            underlying_unified_account_namespace=(row.underlying_unified_account_namespace),
            underlying_unified_account_id=row.underlying_unified_account_id,
            raw_source_owner=row.owner,
            raw_source_artifact_type=row.artifact_type,
            raw_source_id=row.source_id,
            raw_source_version=row.source_version,
            raw_source_content_hash=row.content_hash,
            row_user_id=row.row_user_id,
            account_type=row.account_type,
            is_active=row.is_active,
            row_created_at=row.row_created_at,
            row_updated_at=row.row_updated_at,
            observed_at=row.observed_at,
            recorded_at=recorded_at,
            raw_source_valid_until=row.valid_until,
            ttl_valid_until=ttl_valid_until,
            valid_until=min(row.valid_until, ttl_valid_until),
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        record: PersistedPhysicalAccountRowObservation,
        command: CapturePhysicalAccountRowObservationCommand,
        row: ExactPhysicalSimulatedAccountRow,
        head: PersistedPhysicalAccountRowObservation | None,
        cutoff: datetime,
    ) -> None:
        observation = record.observation
        if not observation.is_knowable_at(cutoff):
            raise PhysicalAccountRowObservationUnavailable(
                "persisted physical account row observation is unavailable"
            )
        if record.captured_by != self._actor:
            raise PhysicalAccountRowObservationConflict(
                "physical account row observation belongs to another actor"
            )
        stable = self._build_observation(
            command,
            row,
            recorded_at=observation.recorded_at,
            ttl_valid_until=observation.ttl_valid_until,
            supersedes_content_hash=observation.supersedes_content_hash,
        )
        if stable != observation:
            raise PhysicalAccountRowObservationConflict(
                "physical account row observation identity has another first winner"
            )
        if head is None or self._require_record(head) != record:
            raise PhysicalAccountRowObservationConflict(
                "physical account row observation is no longer the logical current head"
            )

    @staticmethod
    def _require_record(value: object) -> PersistedPhysicalAccountRowObservation:
        if type(value) is not PersistedPhysicalAccountRowObservation:
            raise PhysicalAccountRowObservationCorruption("repository record type substitution")
        PersistedPhysicalAccountRowObservation.__post_init__(value)
        return value


class GetExactPhysicalAccountRowObservation:
    """Expose exact identity/hash historical reads of inactive row evidence."""

    def __init__(self, repository: PhysicalAccountRowObservationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactPhysicalAccountRowObservationCommand,
    ) -> PhysicalAccountRowObservation | None:
        """Return only exact immutable evidence knowable at the requested PIT."""

        if type(command) is not GetExactPhysicalAccountRowObservationCommand:
            raise TypeError("command must be an exact GetExactPhysicalAccountRowObservationCommand")
        GetExactPhysicalAccountRowObservationCommand.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = CapturePhysicalAccountRowObservation._require_record(value)
        observation = record.observation
        if (
            observation.observation_id != command.observation_id
            or observation.observation_version != command.observation_version
            or observation.content_hash != command.expected_content_hash
        ):
            raise PhysicalAccountRowObservationCorruption(
                "exact physical account row identity substitution"
            )
        if not observation.is_knowable_at(command.as_of):
            return None
        if observation.activation_available or not observation.must_not_execute:
            raise PhysicalAccountRowObservationCorruption(
                "physical account row execution state substitution"
            )
        return observation


class GetCurrentPhysicalAccountRowObservation:
    """Return one exact active row at the final inactive-evidence logical head."""

    def __init__(self, repository: PhysicalAccountRowObservationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentPhysicalAccountRowObservationCommand,
    ) -> PhysicalAccountRowObservation | None:
        """Reject semantic substitutions and never fall back from a final head."""

        if type(command) is not GetCurrentPhysicalAccountRowObservationCommand:
            raise TypeError(
                "command must be an exact GetCurrentPhysicalAccountRowObservationCommand"
            )
        GetCurrentPhysicalAccountRowObservationCommand.__post_init__(command)
        observation = GetExactPhysicalAccountRowObservation(self._repository).execute(
            GetExactPhysicalAccountRowObservationCommand(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if observation is None or _observation_selectors(observation) != _command_selectors(
            command
        ):
            return None
        head = self._repository.get_current_head(
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
            raw_source_id=command.raw_source_id,
            as_of=command.as_of,
        )
        if (
            head is None
            or CapturePhysicalAccountRowObservation._require_record(head).observation != observation
        ):
            return None
        if not observation.is_active:
            return None
        return observation


def _observation_selectors(
    observation: PhysicalAccountRowObservation,
) -> tuple[object, ...]:
    return (
        observation.owner,
        observation.artifact_type,
        observation.schema,
        observation.account_namespace,
        observation.account_id,
        observation.underlying_unified_account_namespace,
        observation.underlying_unified_account_id,
        observation.raw_source_owner,
        observation.raw_source_artifact_type,
        observation.raw_source_id,
        observation.raw_source_version,
        observation.raw_source_content_hash,
        observation.row_user_id,
        observation.account_type,
        observation.is_active,
        observation.row_created_at,
        observation.row_updated_at,
        observation.observed_at,
        observation.recorded_at,
        observation.raw_source_valid_until,
        observation.ttl_valid_until,
        observation.valid_until,
        observation.owner_assignment_state,
    )


def _command_selectors(
    command: GetCurrentPhysicalAccountRowObservationCommand,
) -> tuple[object, ...]:
    return (
        command.owner,
        command.artifact_type,
        command.schema,
        command.account_namespace,
        command.account_id,
        command.underlying_unified_account_namespace,
        command.underlying_unified_account_id,
        command.raw_source_owner,
        command.raw_source_artifact_type,
        command.raw_source_id,
        command.raw_source_version,
        command.raw_source_content_hash,
        command.row_user_id,
        command.account_type,
        command.is_active,
        command.row_created_at,
        command.row_updated_at,
        command.observed_at,
        command.recorded_at,
        command.raw_source_valid_until,
        command.ttl_valid_until,
        command.valid_until,
        command.owner_assignment_state,
    )


__all__ = [
    "CapturePhysicalAccountRowObservation",
    "CapturePhysicalAccountRowObservationCommand",
    "ExactPhysicalSimulatedAccountRow",
    "ExactPhysicalSimulatedAccountRowProvider",
    "GetCurrentPhysicalAccountRowObservation",
    "GetCurrentPhysicalAccountRowObservationCommand",
    "GetExactPhysicalAccountRowObservation",
    "GetExactPhysicalAccountRowObservationCommand",
    "PersistedPhysicalAccountRowObservation",
    "PhysicalAccountRowObservationActor",
    "PhysicalAccountRowObservationConflict",
    "PhysicalAccountRowObservationCorruption",
    "PhysicalAccountRowObservationRepository",
    "PhysicalAccountRowObservationUnavailable",
]
