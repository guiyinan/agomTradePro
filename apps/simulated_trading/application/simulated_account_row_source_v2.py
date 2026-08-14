"""Raw-hash-bound capture and exact read contracts for account-row sources."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SIMULATED_ACCOUNT_RAW_OBSERVATION_ARTIFACT_TYPE,
    SIMULATED_ACCOUNT_RAW_OBSERVATION_OWNER,
    SIMULATED_ACCOUNT_RAW_OBSERVATION_SCHEMA,
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
    validate_simulated_account_row_source_v2_root,
    validate_simulated_account_row_source_v2_successor,
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


class SimulatedAccountRowSourceV2Unavailable(ValueError):
    """Required exact raw observation or v2 source evidence is unavailable."""


class SimulatedAccountRowSourceV2Conflict(ValueError):
    """An immutable identity or predecessor claim has another first winner."""


class SimulatedAccountRowSourceV2Corruption(ValueError):
    """A provider or repository substituted v2 source evidence."""


@dataclass(frozen=True, slots=True)
class ExactRawSimulatedAccountObservationV2:
    """Consumer-owned exact projection of one logical-final raw observation."""

    observation_id: str
    observation_version: str
    identity_hash: str
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
    supersedes_content_hash: str | None
    owner: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_OWNER
    artifact_type: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_ARTIFACT_TYPE
    schema: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        self.to_observation()

    def to_observation(self) -> SimulatedAccountRawObservation:
        """Restore and validate the exact owner observation represented here."""

        return SimulatedAccountRawObservation(
            observation_id=self.observation_id,
            observation_version=self.observation_version,
            row_pk=self.row_pk,
            row_user_id=self.row_user_id,
            raw_account_type=self.raw_account_type,
            is_active=self.is_active,
            row_created_at=self.row_created_at,
            row_updated_at=self.row_updated_at,
            is_present=self.is_present,
            is_tombstone=self.is_tombstone,
            observed_at=self.observed_at,
            valid_until=self.valid_until,
            supersedes_content_hash=self.supersedes_content_hash,
            identity_hash=self.identity_hash,
            content_hash=self.content_hash,
            owner=self.owner,
            artifact_type=self.artifact_type,
            schema=self.schema,
        )


@dataclass(frozen=True, slots=True)
class PersistedSimulatedAccountRowSourceV2:
    """Repository record containing one exact deterministic v2 projection."""

    source: SimulatedAccountRowSourceV2

    def __post_init__(self) -> None:
        if type(self.source) is not SimulatedAccountRowSourceV2:
            raise TypeError("source must be an exact SimulatedAccountRowSourceV2")
        SimulatedAccountRowSourceV2.__post_init__(self.source)


@dataclass(frozen=True, slots=True)
class CaptureSimulatedAccountRowSourceV2Command:
    """ID/hash-only selector for one raw-bound v2 source revision."""

    source_id: str
    source_version: str
    expected_raw_observation_content_hash: str
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
        _require_hash(
            self.expected_raw_observation_content_hash,
            "expected_raw_observation_content_hash",
        )
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )


@dataclass(frozen=True, slots=True)
class GetExactSimulatedAccountRowSourceV2Command:
    """Exact v2 source identity, hash, and historical PIT selector."""

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
class GetCurrentSimulatedAccountRowSourceV2Command:
    """Closed selector requiring one exact source and its exact raw final head."""

    expected_source: SimulatedAccountRowSourceV2
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_source) is not SimulatedAccountRowSourceV2:
            raise TypeError("expected_source must be an exact SimulatedAccountRowSourceV2")
        SimulatedAccountRowSourceV2.__post_init__(self.expected_source)
        _require_aware(self.as_of, "as_of")


class ExactRawSimulatedAccountObservationV2Provider(Protocol):
    """Load one hash-bound raw observation only when it is the PIT final head."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        row_pk: int,
        as_of: datetime,
    ) -> ExactRawSimulatedAccountObservationV2 | None:
        """Return the exact logical-final raw fact, including a tombstone fact."""

        ...


class SimulatedAccountRowSourceV2Repository(Protocol):
    """Independent first-winner v2 store with exact PIT and head reads."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2 | None: ...

    def get_current_head(
        self,
        *,
        source_id: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2 | None: ...

    def append(
        self,
        record: PersistedSimulatedAccountRowSourceV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2: ...

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2 | None: ...


class CaptureSimulatedAccountRowSourceV2:
    """Project one exact raw final head into an immutable v2 source."""

    def __init__(
        self,
        *,
        observation_provider: ExactRawSimulatedAccountObservationV2Provider,
        repository: SimulatedAccountRowSourceV2Repository,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._observation_provider = observation_provider
        self._repository = repository
        self._validity_period = validity_period

    def execute(
        self,
        command: CaptureSimulatedAccountRowSourceV2Command,
    ) -> SimulatedAccountRowSourceV2:
        """Capture or replay one raw-hash-bound first winner."""

        if type(command) is not CaptureSimulatedAccountRowSourceV2Command:
            raise TypeError("command must be an exact CaptureSimulatedAccountRowSourceV2Command")
        CaptureSimulatedAccountRowSourceV2Command.__post_init__(command)
        cutoff = self._repository.now()
        _require_repository_clock(cutoff, "repository cutoff")
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
                raise SimulatedAccountRowSourceV2Conflict(
                    "raw observation changed during v2 source capture"
                )
            if winner is not None:
                checked = _require_record(winner)
                self._validate_winner(checked, command, final, head, cutoff)
                return checked.source

            recorded_at = self._repository.now()
            _require_repository_clock(recorded_at, "repository recorded_at")
            if recorded_at < cutoff:
                raise SimulatedAccountRowSourceV2Corruption("repository clock moved backwards")
            ttl_valid_until = cutoff + self._validity_period
            if recorded_at >= min(final.valid_until, ttl_valid_until):
                raise SimulatedAccountRowSourceV2Unavailable(
                    "raw observation expired before v2 source recording"
                )
            predecessor = _require_record(head).source if head is not None else None
            if (
                predecessor is not None
                and final.supersedes_content_hash != predecessor.raw_observation_content_hash
            ):
                raise SimulatedAccountRowSourceV2Conflict(
                    "raw observation does not bind the previous v2 raw hash"
                )
            source = self._build_source(
                command,
                final,
                recorded_at=recorded_at,
                ttl_valid_until=ttl_valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            if predecessor is None:
                validate_simulated_account_row_source_v2_root(source)
            else:
                validate_simulated_account_row_source_v2_successor(predecessor, source)
            record = PersistedSimulatedAccountRowSourceV2(source=source)
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
                recorded_at=recorded_at,
            )
            checked = _require_record(persisted)
            if checked != record:
                raise SimulatedAccountRowSourceV2Conflict(
                    "concurrent v2 source first winner differs"
                )
            return checked.source

    def _read_observation(
        self,
        command: CaptureSimulatedAccountRowSourceV2Command,
        cutoff: datetime,
    ) -> ExactRawSimulatedAccountObservationV2:
        value = self._observation_provider.get_exact_current(
            observation_id=command.source_id,
            observation_version=command.source_version,
            expected_content_hash=command.expected_raw_observation_content_hash,
            row_pk=command.underlying_unified_account_id,
            as_of=cutoff,
        )
        return _require_raw_observation(
            value,
            observation_id=command.source_id,
            observation_version=command.source_version,
            expected_content_hash=command.expected_raw_observation_content_hash,
            row_pk=command.underlying_unified_account_id,
            as_of=cutoff,
        )

    @staticmethod
    def _build_source(
        command: CaptureSimulatedAccountRowSourceV2Command,
        observation: ExactRawSimulatedAccountObservationV2,
        *,
        recorded_at: datetime,
        ttl_valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> SimulatedAccountRowSourceV2:
        return SimulatedAccountRowSourceV2(
            source_id=command.source_id,
            source_version=command.source_version,
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
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
            raw_observation_id=observation.observation_id,
            raw_observation_version=observation.observation_version,
            raw_observation_identity_hash=observation.identity_hash,
            raw_observation_content_hash=observation.content_hash,
            raw_observation_observed_at=observation.observed_at,
            raw_observation_valid_until=observation.valid_until,
            raw_observation_supersedes_content_hash=(observation.supersedes_content_hash),
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        record: PersistedSimulatedAccountRowSourceV2,
        command: CaptureSimulatedAccountRowSourceV2Command,
        observation: ExactRawSimulatedAccountObservationV2,
        head: PersistedSimulatedAccountRowSourceV2 | None,
        cutoff: datetime,
    ) -> None:
        source = record.source
        if not source.is_knowable_at(cutoff):
            raise SimulatedAccountRowSourceV2Unavailable("persisted v2 source is unavailable")
        stable = self._build_source(
            command,
            observation,
            recorded_at=source.recorded_at,
            ttl_valid_until=source.ttl_valid_until,
            supersedes_content_hash=source.supersedes_content_hash,
        )
        if stable != source:
            raise SimulatedAccountRowSourceV2Conflict("v2 source identity has another first winner")
        if head is None or _require_record(head) != record:
            raise SimulatedAccountRowSourceV2Conflict(
                "v2 source is no longer the logical current head"
            )


class GetExactSimulatedAccountRowSourceV2:
    """Expose exact identity/hash historical reads of inactive v2 evidence."""

    def __init__(self, repository: SimulatedAccountRowSourceV2Repository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactSimulatedAccountRowSourceV2Command,
    ) -> SimulatedAccountRowSourceV2 | None:
        """Return exact v2 evidence knowable at the requested PIT."""

        if type(command) is not GetExactSimulatedAccountRowSourceV2Command:
            raise TypeError("command must be an exact GetExactSimulatedAccountRowSourceV2Command")
        GetExactSimulatedAccountRowSourceV2Command.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        source = _require_record(value).source
        if (
            source.source_id != command.source_id
            or source.source_version != command.source_version
            or source.content_hash != command.expected_content_hash
        ):
            raise SimulatedAccountRowSourceV2Corruption("exact v2 source selector substitution")
        return source if source.is_knowable_at(command.as_of) else None


class GetCurrentSimulatedAccountRowSourceV2:
    """Read only a live v2 source whose bound raw fact remains the final head."""

    def __init__(
        self,
        *,
        repository: SimulatedAccountRowSourceV2Repository,
        observation_provider: ExactRawSimulatedAccountObservationV2Provider,
    ) -> None:
        self._repository = repository
        self._observation_provider = observation_provider

    def execute(
        self,
        command: GetCurrentSimulatedAccountRowSourceV2Command,
    ) -> SimulatedAccountRowSourceV2 | None:
        """Fail closed on source or raw-head supersession without fallback."""

        if type(command) is not GetCurrentSimulatedAccountRowSourceV2Command:
            raise TypeError("command must be an exact GetCurrentSimulatedAccountRowSourceV2Command")
        GetCurrentSimulatedAccountRowSourceV2Command.__post_init__(command)
        expected = command.expected_source
        exact = GetExactSimulatedAccountRowSourceV2(self._repository).execute(
            GetExactSimulatedAccountRowSourceV2Command(
                source_id=expected.source_id,
                source_version=expected.source_version,
                expected_content_hash=expected.content_hash,
                as_of=command.as_of,
            )
        )
        if exact is None or exact != expected:
            return None
        head = self._repository.get_current_head(
            source_id=expected.source_id,
            account_namespace=expected.account_namespace,
            account_id=expected.account_id,
            underlying_unified_account_namespace=(expected.underlying_unified_account_namespace),
            underlying_unified_account_id=expected.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if head is None or _require_record(head).source != expected:
            return None
        raw_value = self._observation_provider.get_exact_current(
            observation_id=expected.raw_observation_id,
            observation_version=expected.raw_observation_version,
            expected_content_hash=expected.raw_observation_content_hash,
            row_pk=expected.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if raw_value is None:
            return None
        raw = _require_raw_observation(
            raw_value,
            observation_id=expected.raw_observation_id,
            observation_version=expected.raw_observation_version,
            expected_content_hash=expected.raw_observation_content_hash,
            row_pk=expected.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if not _raw_matches_source(raw, expected):
            raise SimulatedAccountRowSourceV2Corruption(
                "v2 source does not match its exact raw observation"
            )
        return expected if expected.is_current_at(command.as_of) else None


def _require_repository_clock(value: object, field_name: str) -> None:
    try:
        _require_aware(value, field_name)
    except ValueError as error:
        raise SimulatedAccountRowSourceV2Corruption(f"{field_name} is invalid") from error


def _require_raw_observation(
    value: ExactRawSimulatedAccountObservationV2 | None,
    *,
    observation_id: str,
    observation_version: str,
    expected_content_hash: str,
    row_pk: int,
    as_of: datetime,
) -> ExactRawSimulatedAccountObservationV2:
    if value is None:
        raise SimulatedAccountRowSourceV2Unavailable("exact current raw observation is unavailable")
    if type(value) is not ExactRawSimulatedAccountObservationV2:
        raise SimulatedAccountRowSourceV2Corruption("raw observation provider type substitution")
    try:
        observation = value.to_observation()
    except (TypeError, ValueError) as error:
        raise SimulatedAccountRowSourceV2Corruption(
            "raw observation provider returned invalid evidence"
        ) from error
    if (
        observation.observation_id != observation_id
        or observation.observation_version != observation_version
        or observation.content_hash != expected_content_hash
        or observation.row_pk != row_pk
    ):
        raise SimulatedAccountRowSourceV2Corruption(
            "raw observation provider selector substitution"
        )
    if not observation.is_knowable_at(as_of):
        raise SimulatedAccountRowSourceV2Unavailable("exact current raw observation is unavailable")
    return value


def _require_record(value: object) -> PersistedSimulatedAccountRowSourceV2:
    if type(value) is not PersistedSimulatedAccountRowSourceV2:
        raise SimulatedAccountRowSourceV2Corruption(
            "repository substituted the v2 source record type"
        )
    try:
        PersistedSimulatedAccountRowSourceV2.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise SimulatedAccountRowSourceV2Corruption(
            "repository returned an invalid v2 source record"
        ) from error
    return value


def _raw_matches_source(
    raw: ExactRawSimulatedAccountObservationV2,
    source: SimulatedAccountRowSourceV2,
) -> bool:
    return (
        raw.owner,
        raw.artifact_type,
        raw.schema,
        raw.observation_id,
        raw.observation_version,
        raw.identity_hash,
        raw.content_hash,
        raw.row_pk,
        raw.row_user_id,
        raw.raw_account_type,
        raw.is_active,
        raw.row_created_at,
        raw.row_updated_at,
        raw.is_present,
        raw.is_tombstone,
        raw.observed_at,
        raw.valid_until,
        raw.supersedes_content_hash,
    ) == (
        source.raw_observation_owner,
        source.raw_observation_artifact_type,
        source.raw_observation_schema,
        source.raw_observation_id,
        source.raw_observation_version,
        source.raw_observation_identity_hash,
        source.raw_observation_content_hash,
        source.underlying_unified_account_id,
        source.row_user_id,
        source.raw_account_type,
        source.is_active,
        source.row_created_at,
        source.row_updated_at,
        source.is_present,
        source.is_tombstone,
        source.raw_observation_observed_at,
        source.raw_observation_valid_until,
        source.raw_observation_supersedes_content_hash,
    )


__all__ = [
    "CaptureSimulatedAccountRowSourceV2",
    "CaptureSimulatedAccountRowSourceV2Command",
    "ExactRawSimulatedAccountObservationV2",
    "ExactRawSimulatedAccountObservationV2Provider",
    "GetCurrentSimulatedAccountRowSourceV2",
    "GetCurrentSimulatedAccountRowSourceV2Command",
    "GetExactSimulatedAccountRowSourceV2",
    "GetExactSimulatedAccountRowSourceV2Command",
    "PersistedSimulatedAccountRowSourceV2",
    "SimulatedAccountRowSourceV2Conflict",
    "SimulatedAccountRowSourceV2Corruption",
    "SimulatedAccountRowSourceV2Repository",
    "SimulatedAccountRowSourceV2Unavailable",
]
