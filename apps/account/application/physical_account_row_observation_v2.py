"""Raw-bound Account v2 capture and exact-read application contracts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.physical_account_row_observation_v2 import (
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA,
    PhysicalAccountRowObservationV2,
    validate_physical_account_row_observation_v2_root,
    validate_physical_account_row_observation_v2_successor,
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


class PhysicalAccountRowObservationV2Unavailable(ValueError):
    """Required exact-final source-v2 evidence is unavailable."""


class PhysicalAccountRowObservationV2Conflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class PhysicalAccountRowObservationV2Corruption(ValueError):
    """A provider or repository substituted raw-bound Account evidence."""


@dataclass(frozen=True, slots=True)
class PhysicalAccountRowObservationV2Recorder:
    """Authenticated service identity that materializes Account v2 evidence."""

    recorder_id: str
    service_name: str
    role: str = "evidence_projector"
    kind: str = "service"
    is_automated: bool = True

    def __post_init__(self) -> None:
        _require_token(self.recorder_id, "recorder_id")
        _require_token(self.service_name, "service_name")
        if self.role != "evidence_projector":
            raise ValueError("recorder role is fixed")
        if self.kind != "service":
            raise ValueError("recorder kind is fixed")
        if self.is_automated is not True:
            raise ValueError("recorder is_automated is fixed")


@dataclass(frozen=True, slots=True)
class ExactPhysicalSimulatedAccountRowV2:
    """Consumer-owned exact projection of source v2 plus its raw seal."""

    source_id: str
    source_version: str
    identity_hash: str
    content_hash: str
    source_supersedes_content_hash: str | None
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
    raw_observation_id: str
    raw_observation_version: str
    raw_observation_identity_hash: str
    raw_observation_content_hash: str
    raw_observation_supersedes_content_hash: str | None
    raw_observation_observed_at: datetime
    raw_observation_valid_until: datetime
    owner_assignment_state: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE
    owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER
    artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE
    schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA
    raw_observation_owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER
    raw_observation_artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE
    raw_observation_schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_account_type",
            "raw_observation_id",
            "raw_observation_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "identity_hash",
            "content_hash",
            "raw_observation_identity_hash",
            "raw_observation_content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in (
            "source_supersedes_content_hash",
            "raw_observation_supersedes_content_hash",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_hash(value, field_name)
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )
        if self.row_user_id is not None:
            _require_positive_integer(self.row_user_id, "row_user_id")
        for field_name in ("is_active", "is_present", "is_tombstone"):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be an exact boolean")
        if self.is_present == self.is_tombstone:
            raise ValueError("is_present and is_tombstone must be exact opposites")
        for field_name in (
            "row_created_at",
            "row_updated_at",
            "observed_at",
            "recorded_at",
            "source_valid_until",
            "ttl_valid_until",
            "valid_until",
            "raw_observation_observed_at",
            "raw_observation_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if (
            self.owner != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER
            or self.artifact_type != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE
            or self.schema != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA
            or self.raw_observation_owner != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER
            or self.raw_observation_artifact_type
            != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE
            or self.raw_observation_schema != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA
            or self.owner_assignment_state
            != PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE
        ):
            raise ValueError("physical simulated account row v2 authority is invalid")
        if self.source_id != self.raw_observation_id:
            raise ValueError("source_id must equal raw observation id")
        if self.source_version != self.raw_observation_version:
            raise ValueError("source_version must equal raw observation version")
        if self.observed_at != self.raw_observation_observed_at:
            raise ValueError("source and raw observation clocks differ")
        if self.source_valid_until != self.raw_observation_valid_until:
            raise ValueError("source and raw observation validity differ")
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("physical simulated account row v2 clock sequence is invalid")
        if not self.observed_at <= self.recorded_at < self.valid_until:
            raise ValueError("physical simulated account row v2 recording is invalid")
        if self.valid_until != min(self.source_valid_until, self.ttl_valid_until):
            raise ValueError("physical simulated account row v2 validity is invalid")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the exact final source is visible and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact final source represents a live row."""

        return (
            self.is_knowable_at(as_of)
            and self.is_active
            and self.is_present
            and not self.is_tombstone
        )


@dataclass(frozen=True, slots=True)
class PersistedPhysicalAccountRowObservationV2:
    """Repository record pairing v2 evidence with its service recorder."""

    observation: PhysicalAccountRowObservationV2
    recorded_by: PhysicalAccountRowObservationV2Recorder

    def __post_init__(self) -> None:
        if type(self.observation) is not PhysicalAccountRowObservationV2:
            raise TypeError("observation must be an exact PhysicalAccountRowObservationV2")
        PhysicalAccountRowObservationV2.__post_init__(self.observation)
        if type(self.recorded_by) is not PhysicalAccountRowObservationV2Recorder:
            raise TypeError("recorded_by must be an exact PhysicalAccountRowObservationV2Recorder")
        PhysicalAccountRowObservationV2Recorder.__post_init__(self.recorded_by)


@dataclass(frozen=True, slots=True)
class CapturePhysicalAccountRowObservationV2Command:
    """ID/hash-only selector for one Account capture and exact source seal."""

    observation_id: str
    observation_version: str
    source_id: str
    source_version: str
    expected_source_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(
            self.expected_source_content_hash,
            "expected_source_content_hash",
        )
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )


@dataclass(frozen=True, slots=True)
class GetExactPhysicalAccountRowObservationV2Command:
    """Exact Account v2 identity/hash historical PIT selector."""

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
class GetCurrentPhysicalAccountRowObservationV2Command:
    """Closed current selector carrying every expected sealed fact."""

    expected_observation: PhysicalAccountRowObservationV2
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_observation) is not PhysicalAccountRowObservationV2:
            raise TypeError("expected_observation must be an exact PhysicalAccountRowObservationV2")
        PhysicalAccountRowObservationV2.__post_init__(self.expected_observation)
        _require_aware(self.as_of, "as_of")


class ExactPhysicalSimulatedAccountRowV2Provider(Protocol):
    """Owner provider separating final evidence from live decision reads."""

    def get_exact_final(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRowV2 | None: ...

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRowV2 | None: ...


class PhysicalAccountRowObservationV2Repository(Protocol):
    """Independent v2 first-winner, logical-head, and exact-PIT store."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None: ...

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        source_id: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None: ...

    def append(
        self,
        record: PersistedPhysicalAccountRowObservationV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2: ...

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None: ...


class CapturePhysicalAccountRowObservationV2:
    """Capture Account v2 evidence from one exact-final source-v2 seal."""

    def __init__(
        self,
        *,
        row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
        repository: PhysicalAccountRowObservationV2Repository,
        recorder: PhysicalAccountRowObservationV2Recorder,
        validity_period: timedelta,
    ) -> None:
        if type(recorder) is not PhysicalAccountRowObservationV2Recorder:
            raise TypeError("recorder must be an exact PhysicalAccountRowObservationV2Recorder")
        PhysicalAccountRowObservationV2Recorder.__post_init__(recorder)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._row_provider = row_provider
        self._repository = repository
        self._recorder = recorder
        self._validity_period = validity_period

    def execute(
        self,
        command: CapturePhysicalAccountRowObservationV2Command,
    ) -> PhysicalAccountRowObservationV2:
        """Capture or replay one raw-bound Account first winner."""

        if type(command) is not CapturePhysicalAccountRowObservationV2Command:
            raise TypeError(
                "command must be an exact CapturePhysicalAccountRowObservationV2Command"
            )
        CapturePhysicalAccountRowObservationV2Command.__post_init__(command)
        cutoff = self._repository.now()
        _require_repository_clock(cutoff, "repository cutoff")
        first = self._read_source(command, cutoff, current=False)
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
                source_id=command.source_id,
                as_of=cutoff,
            )
            final = self._read_source(command, cutoff, current=False)
            if final != first:
                raise PhysicalAccountRowObservationV2Conflict(
                    "source v2 changed during Account capture"
                )
            if winner is not None:
                checked = _require_record(winner)
                self._validate_winner(checked, command, final, head, cutoff)
                return checked.observation
            recorded_at = self._repository.now()
            _require_repository_clock(recorded_at, "repository recorded_at")
            if recorded_at < cutoff:
                raise PhysicalAccountRowObservationV2Corruption("repository clock moved backwards")
            ttl_valid_until = cutoff + self._validity_period
            if recorded_at >= min(final.valid_until, ttl_valid_until):
                raise PhysicalAccountRowObservationV2Unavailable(
                    "source v2 expired before Account recording"
                )
            predecessor = _require_record(head).observation if head is not None else None
            if predecessor is not None and (
                final.source_supersedes_content_hash != predecessor.source_content_hash
                or final.raw_observation_supersedes_content_hash
                != predecessor.raw_observation_content_hash
            ):
                raise PhysicalAccountRowObservationV2Conflict(
                    "source v2 does not bind both previous upstream seals"
                )
            observation = self._build_observation(
                command,
                final,
                recorded_at=recorded_at,
                ttl_valid_until=ttl_valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            if predecessor is None:
                validate_physical_account_row_observation_v2_root(observation)
            else:
                validate_physical_account_row_observation_v2_successor(
                    predecessor,
                    observation,
                )
            record = PersistedPhysicalAccountRowObservationV2(
                observation=observation,
                recorded_by=self._recorder,
            )
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
                recorded_at=recorded_at,
            )
            checked = _require_record(persisted)
            if checked != record:
                raise PhysicalAccountRowObservationV2Conflict(
                    "concurrent Account v2 first winner differs"
                )
            return checked.observation

    def _read_source(
        self,
        command: CapturePhysicalAccountRowObservationV2Command,
        cutoff: datetime,
        *,
        current: bool,
    ) -> ExactPhysicalSimulatedAccountRowV2:
        method = (
            self._row_provider.get_exact_current if current else self._row_provider.get_exact_final
        )
        value = method(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_source_content_hash,
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
            as_of=cutoff,
        )
        return _require_source(
            value,
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_source_content_hash,
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
            as_of=cutoff,
            require_current=current,
        )

    @staticmethod
    def _build_observation(
        command: CapturePhysicalAccountRowObservationV2Command,
        source: ExactPhysicalSimulatedAccountRowV2,
        *,
        recorded_at: datetime,
        ttl_valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> PhysicalAccountRowObservationV2:
        return PhysicalAccountRowObservationV2(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            underlying_unified_account_namespace=(source.underlying_unified_account_namespace),
            underlying_unified_account_id=source.underlying_unified_account_id,
            row_user_id=source.row_user_id,
            raw_account_type=source.raw_account_type,
            is_active=source.is_active,
            row_created_at=source.row_created_at,
            row_updated_at=source.row_updated_at,
            is_present=source.is_present,
            is_tombstone=source.is_tombstone,
            source_id=source.source_id,
            source_version=source.source_version,
            source_identity_hash=source.identity_hash,
            source_content_hash=source.content_hash,
            source_supersedes_content_hash=source.source_supersedes_content_hash,
            source_observed_at=source.observed_at,
            source_recorded_at=source.recorded_at,
            source_valid_until=source.source_valid_until,
            source_ttl_valid_until=source.ttl_valid_until,
            source_effective_valid_until=source.valid_until,
            raw_observation_id=source.raw_observation_id,
            raw_observation_version=source.raw_observation_version,
            raw_observation_identity_hash=source.raw_observation_identity_hash,
            raw_observation_content_hash=source.raw_observation_content_hash,
            raw_observation_supersedes_content_hash=(
                source.raw_observation_supersedes_content_hash
            ),
            raw_observation_observed_at=source.raw_observation_observed_at,
            raw_observation_valid_until=source.raw_observation_valid_until,
            recorded_at=recorded_at,
            ttl_valid_until=ttl_valid_until,
            valid_until=min(source.valid_until, ttl_valid_until),
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        record: PersistedPhysicalAccountRowObservationV2,
        command: CapturePhysicalAccountRowObservationV2Command,
        source: ExactPhysicalSimulatedAccountRowV2,
        head: PersistedPhysicalAccountRowObservationV2 | None,
        cutoff: datetime,
    ) -> None:
        observation = record.observation
        if not observation.is_knowable_at(cutoff):
            raise PhysicalAccountRowObservationV2Unavailable(
                "persisted Account v2 observation is unavailable"
            )
        stable = self._build_observation(
            command,
            source,
            recorded_at=observation.recorded_at,
            ttl_valid_until=observation.ttl_valid_until,
            supersedes_content_hash=observation.supersedes_content_hash,
        )
        if stable != observation:
            raise PhysicalAccountRowObservationV2Conflict(
                "Account v2 identity has another first winner"
            )
        if head is None or _require_record(head) != record:
            raise PhysicalAccountRowObservationV2Conflict(
                "Account v2 observation is no longer the logical head"
            )


class GetExactPhysicalAccountRowObservationV2:
    """Expose exact identity/hash historical Account v2 evidence."""

    def __init__(self, repository: PhysicalAccountRowObservationV2Repository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactPhysicalAccountRowObservationV2Command,
    ) -> PhysicalAccountRowObservationV2 | None:
        if type(command) is not GetExactPhysicalAccountRowObservationV2Command:
            raise TypeError(
                "command must be an exact GetExactPhysicalAccountRowObservationV2Command"
            )
        GetExactPhysicalAccountRowObservationV2Command.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        observation = _require_record(value).observation
        if (
            observation.observation_id != command.observation_id
            or observation.observation_version != command.observation_version
            or observation.content_hash != command.expected_content_hash
        ):
            raise PhysicalAccountRowObservationV2Corruption(
                "exact Account v2 selector substitution"
            )
        return observation if observation.is_knowable_at(command.as_of) else None


class GetCurrentPhysicalAccountRowObservationV2:
    """Return a live Account v2 head only while its source remains current."""

    def __init__(
        self,
        *,
        repository: PhysicalAccountRowObservationV2Repository,
        row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
    ) -> None:
        self._repository = repository
        self._row_provider = row_provider

    def execute(
        self,
        command: GetCurrentPhysicalAccountRowObservationV2Command,
    ) -> PhysicalAccountRowObservationV2 | None:
        if type(command) is not GetCurrentPhysicalAccountRowObservationV2Command:
            raise TypeError(
                "command must be an exact GetCurrentPhysicalAccountRowObservationV2Command"
            )
        GetCurrentPhysicalAccountRowObservationV2Command.__post_init__(command)
        expected = command.expected_observation
        exact = GetExactPhysicalAccountRowObservationV2(self._repository).execute(
            GetExactPhysicalAccountRowObservationV2Command(
                observation_id=expected.observation_id,
                observation_version=expected.observation_version,
                expected_content_hash=expected.content_hash,
                as_of=command.as_of,
            )
        )
        if exact is None or exact != expected:
            return None
        head = self._repository.get_current_head(
            account_namespace=expected.account_namespace,
            account_id=expected.account_id,
            underlying_unified_account_namespace=(expected.underlying_unified_account_namespace),
            underlying_unified_account_id=expected.underlying_unified_account_id,
            source_id=expected.source_id,
            as_of=command.as_of,
        )
        if head is None or _require_record(head).observation != expected:
            return None
        source_value = self._row_provider.get_exact_current(
            source_id=expected.source_id,
            source_version=expected.source_version,
            expected_content_hash=expected.source_content_hash,
            account_namespace=expected.account_namespace,
            account_id=expected.account_id,
            underlying_unified_account_namespace=(expected.underlying_unified_account_namespace),
            underlying_unified_account_id=expected.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if source_value is None:
            return None
        source = _require_source(
            source_value,
            source_id=expected.source_id,
            source_version=expected.source_version,
            expected_content_hash=expected.source_content_hash,
            account_namespace=expected.account_namespace,
            account_id=expected.account_id,
            underlying_unified_account_namespace=(expected.underlying_unified_account_namespace),
            underlying_unified_account_id=expected.underlying_unified_account_id,
            as_of=command.as_of,
            require_current=True,
        )
        if not _source_matches_observation(source, expected):
            raise PhysicalAccountRowObservationV2Corruption(
                "Account v2 observation does not match its exact source"
            )
        return expected if expected.is_current_at(command.as_of) else None


def _require_repository_clock(value: object, field_name: str) -> None:
    try:
        _require_aware(value, field_name)
    except ValueError as error:
        raise PhysicalAccountRowObservationV2Corruption(f"{field_name} is invalid") from error


def _require_source(
    value: ExactPhysicalSimulatedAccountRowV2 | None,
    *,
    source_id: str,
    source_version: str,
    expected_content_hash: str,
    account_namespace: str,
    account_id: str,
    underlying_unified_account_namespace: str,
    underlying_unified_account_id: int,
    as_of: datetime,
    require_current: bool,
) -> ExactPhysicalSimulatedAccountRowV2:
    if value is None:
        raise PhysicalAccountRowObservationV2Unavailable("exact source v2 evidence is unavailable")
    if type(value) is not ExactPhysicalSimulatedAccountRowV2:
        raise PhysicalAccountRowObservationV2Corruption("source v2 provider type substitution")
    try:
        ExactPhysicalSimulatedAccountRowV2.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PhysicalAccountRowObservationV2Corruption(
            "source v2 provider returned invalid evidence"
        ) from error
    if (
        value.source_id != source_id
        or value.source_version != source_version
        or value.content_hash != expected_content_hash
        or value.account_namespace != account_namespace
        or value.account_id != account_id
        or value.underlying_unified_account_namespace != underlying_unified_account_namespace
        or value.underlying_unified_account_id != underlying_unified_account_id
    ):
        raise PhysicalAccountRowObservationV2Corruption("source v2 provider selector substitution")
    if not value.is_knowable_at(as_of) or (require_current and not value.is_current_at(as_of)):
        raise PhysicalAccountRowObservationV2Unavailable("exact source v2 evidence is unavailable")
    return value


def _require_record(value: object) -> PersistedPhysicalAccountRowObservationV2:
    if type(value) is not PersistedPhysicalAccountRowObservationV2:
        raise PhysicalAccountRowObservationV2Corruption(
            "repository substituted the Account v2 record type"
        )
    try:
        PersistedPhysicalAccountRowObservationV2.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PhysicalAccountRowObservationV2Corruption(
            "repository returned an invalid Account v2 record"
        ) from error
    return value


def _source_matches_observation(
    source: ExactPhysicalSimulatedAccountRowV2,
    observation: PhysicalAccountRowObservationV2,
) -> bool:
    return (
        source.source_id,
        source.source_version,
        source.identity_hash,
        source.content_hash,
        source.source_supersedes_content_hash,
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
        source.raw_observation_id,
        source.raw_observation_version,
        source.raw_observation_identity_hash,
        source.raw_observation_content_hash,
        source.raw_observation_supersedes_content_hash,
        source.raw_observation_observed_at,
        source.raw_observation_valid_until,
    ) == (
        observation.source_id,
        observation.source_version,
        observation.source_identity_hash,
        observation.source_content_hash,
        observation.source_supersedes_content_hash,
        observation.account_namespace,
        observation.account_id,
        observation.underlying_unified_account_namespace,
        observation.underlying_unified_account_id,
        observation.row_user_id,
        observation.raw_account_type,
        observation.is_active,
        observation.row_created_at,
        observation.row_updated_at,
        observation.is_present,
        observation.is_tombstone,
        observation.source_observed_at,
        observation.source_recorded_at,
        observation.source_valid_until,
        observation.source_ttl_valid_until,
        observation.source_effective_valid_until,
        observation.raw_observation_id,
        observation.raw_observation_version,
        observation.raw_observation_identity_hash,
        observation.raw_observation_content_hash,
        observation.raw_observation_supersedes_content_hash,
        observation.raw_observation_observed_at,
        observation.raw_observation_valid_until,
    )


__all__ = [
    "CapturePhysicalAccountRowObservationV2",
    "CapturePhysicalAccountRowObservationV2Command",
    "ExactPhysicalSimulatedAccountRowV2",
    "ExactPhysicalSimulatedAccountRowV2Provider",
    "GetCurrentPhysicalAccountRowObservationV2",
    "GetCurrentPhysicalAccountRowObservationV2Command",
    "GetExactPhysicalAccountRowObservationV2",
    "GetExactPhysicalAccountRowObservationV2Command",
    "PersistedPhysicalAccountRowObservationV2",
    "PhysicalAccountRowObservationV2",
    "PhysicalAccountRowObservationV2Recorder",
    "PhysicalAccountRowObservationV2Conflict",
    "PhysicalAccountRowObservationV2Corruption",
    "PhysicalAccountRowObservationV2Repository",
    "PhysicalAccountRowObservationV2Unavailable",
]
