"""ID-only capture workflow for inactive Account raw identity source evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.account_identity_raw_source import (
    ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE,
    ACCOUNT_IDENTITY_RAW_SOURCE_OWNER,
    ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA,
    ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE,
    AccountIdentityRawSource,
    validate_account_identity_raw_source_successor,
)

UNIFIED_ACCOUNT_ROW_OBSERVATION_OWNER = "simulated_trading"
UNIFIED_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE = "unified_account_row_observation"
ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER = "account"


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
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


class AccountIdentityRawSourceUnavailable(ValueError):
    """Required exact-current source or assignment evidence is unavailable."""


class AccountIdentityRawSourceConflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class AccountIdentityRawSourceCorruption(ValueError):
    """A provider or repository returned substituted evidence."""


@dataclass(frozen=True, slots=True)
class AccountIdentityRawSourceActor:
    """Server-authenticated human staff identity capturing raw evidence."""

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
            raise ValueError("account identity raw source actor must be human staff")


@dataclass(frozen=True, slots=True)
class ExactUnifiedAccountRowObservation:
    """Consumer-owned exact projection of one physical unified account row."""

    source_id: str
    source_version: str
    content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_owner_user_id: int | None
    account_type: str
    is_active: bool
    observed_at: datetime
    valid_until: datetime
    owner: str = UNIFIED_ACCOUNT_ROW_OBSERVATION_OWNER
    artifact_type: str = UNIFIED_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE

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
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if self.row_owner_user_id is not None and (
            type(self.row_owner_user_id) is not int or self.row_owner_user_id <= 0
        ):
            raise ValueError("row_owner_user_id must be null or an exact positive integer")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        if (
            self.owner != UNIFIED_ACCOUNT_ROW_OBSERVATION_OWNER
            or self.artifact_type != UNIFIED_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE
        ):
            raise ValueError("unified account row observation authority is invalid")
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.valid_until, "valid_until")
        if self.observed_at >= self.valid_until:
            raise ValueError("unified account row observation validity is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact row observation is current at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.observed_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class ExactAccountOwnerAssignmentEvidence:
    """Account-owned authority binding one exact row to an assignment state."""

    evidence_id: str
    evidence_version: str
    content_hash: str
    assignment_state: str
    assigned_owner_user_id: int | None
    row_source_id: str
    row_source_version: str
    row_source_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    recorded_at: datetime
    valid_until: datetime
    owner: str = ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_id",
            "evidence_version",
            "assignment_state",
            "row_source_id",
            "row_source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        _require_hash(self.row_source_content_hash, "row_source_content_hash")
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if self.owner != ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER:
            raise ValueError("assignment evidence owner is invalid")
        if self.assignment_state == "authoritative":
            if self.artifact_type != ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE:
                raise ValueError("authoritative assignment evidence type is invalid")
            if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
                raise ValueError("authoritative evidence requires an exact owner")
        elif self.assignment_state == "legacy_default":
            if self.artifact_type != ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE:
                raise ValueError("legacy assignment evidence type is invalid")
            if self.assigned_owner_user_id is not None:
                raise ValueError("legacy assignment evidence cannot claim an owner")
        else:
            raise ValueError("assignment evidence state is invalid")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("assignment evidence validity is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact assignment evidence is current at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class PersistedAccountIdentityRawSource:
    """Repository record pairing immutable source evidence with its server actor."""

    source: AccountIdentityRawSource
    captured_by: AccountIdentityRawSourceActor

    def __post_init__(self) -> None:
        if type(self.source) is not AccountIdentityRawSource:
            raise TypeError("source must be an exact AccountIdentityRawSource")
        AccountIdentityRawSource.__post_init__(self.source)
        if type(self.captured_by) is not AccountIdentityRawSourceActor:
            raise TypeError("captured_by must be an exact AccountIdentityRawSourceActor")
        AccountIdentityRawSourceActor.__post_init__(self.captured_by)


@dataclass(frozen=True, slots=True)
class CaptureAccountIdentityRawSourceCommand:
    """ID-only selector for one row observation and assignment authority."""

    source_id: str
    source_version: str
    row_source_id: str
    row_source_version: str
    assignment_evidence_id: str
    assignment_evidence_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "row_source_id",
            "row_source_version",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GetExactAccountIdentityRawSourceCommand:
    """Exact identity/hash/PIT selector for inactive raw-source evidence."""

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
class GetCurrentAccountIdentityRawSourceCommand:
    """Closed selector for one exact inactive logical head."""

    source_id: str
    source_version: str
    expected_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    owner_user_id: int | None
    assignment_state: str
    assignment_evidence_owner: str | None
    assignment_evidence_artifact_type: str | None
    assignment_evidence_id: str | None
    assignment_evidence_version: str | None
    assignment_evidence_content_hash: str | None
    row_source_owner: str
    row_source_artifact_type: str
    row_source_id: str
    row_source_version: str
    row_source_content_hash: str
    account_type: str
    is_active: bool
    as_of: datetime
    owner: str = ACCOUNT_IDENTITY_RAW_SOURCE_OWNER
    artifact_type: str = ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE
    schema: str = ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "assignment_state",
            "row_source_owner",
            "row_source_artifact_type",
            "row_source_id",
            "row_source_version",
            "account_type",
            "owner",
            "artifact_type",
            "schema",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_hash(self.row_source_content_hash, "row_source_content_hash")
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.owner_user_id is not None and (
            type(self.owner_user_id) is not int or self.owner_user_id <= 0
        ):
            raise ValueError("owner_user_id must be null or positive")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        _require_aware(self.as_of, "as_of")

    @classmethod
    def from_source(
        cls,
        source: AccountIdentityRawSource,
        *,
        as_of: datetime,
    ) -> GetCurrentAccountIdentityRawSourceCommand:
        """Build a closed selector from one trusted source value."""

        if type(source) is not AccountIdentityRawSource:
            raise TypeError("source must be an exact AccountIdentityRawSource")
        AccountIdentityRawSource.__post_init__(source)
        return cls(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            underlying_unified_account_namespace=source.underlying_unified_account_namespace,
            underlying_unified_account_id=source.underlying_unified_account_id,
            owner_user_id=source.owner_user_id,
            assignment_state=source.assignment_state,
            assignment_evidence_owner=source.assignment_evidence_owner,
            assignment_evidence_artifact_type=source.assignment_evidence_artifact_type,
            assignment_evidence_id=source.assignment_evidence_id,
            assignment_evidence_version=source.assignment_evidence_version,
            assignment_evidence_content_hash=source.assignment_evidence_content_hash,
            row_source_owner=source.row_source_owner,
            row_source_artifact_type=source.row_source_artifact_type,
            row_source_id=source.row_source_id,
            row_source_version=source.row_source_version,
            row_source_content_hash=source.row_source_content_hash,
            account_type=source.account_type,
            is_active=source.is_active,
            as_of=as_of,
        )


class ExactUnifiedAccountRowObservationProvider(Protocol):
    """Load one exact-current physical account row observation."""

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> ExactUnifiedAccountRowObservation | None:
        """Return the exact row observation at one server cutoff."""


class ExactAccountOwnerAssignmentEvidenceProvider(Protocol):
    """Load exact Account-owned assignment authority for one row."""

    def get_exact_current(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        as_of: datetime,
    ) -> ExactAccountOwnerAssignmentEvidence | None:
        """Return exact assignment evidence at one server cutoff."""


class AccountIdentityRawSourceRepository(Protocol):
    """First-winner store and exact inactive PIT read authority."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Account server clock."""

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        """Return the immutable first winner for one source identity."""

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        """Return the logical head without expiry or active-state fallback."""

    def append(
        self,
        record: PersistedAccountIdentityRawSource,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountIdentityRawSource:
        """Append under first-winner and predecessor CAS semantics."""

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        """Return exact identity/hash evidence knowable at one PIT."""


class CaptureAccountIdentityRawSource:
    """Capture raw source evidence only from two exact-current providers."""

    def __init__(
        self,
        *,
        row_provider: ExactUnifiedAccountRowObservationProvider,
        assignment_evidence_provider: ExactAccountOwnerAssignmentEvidenceProvider,
        repository: AccountIdentityRawSourceRepository,
        actor: AccountIdentityRawSourceActor,
        validity_period: timedelta,
    ) -> None:
        if type(actor) is not AccountIdentityRawSourceActor:
            raise TypeError("actor must be an exact AccountIdentityRawSourceActor")
        AccountIdentityRawSourceActor.__post_init__(actor)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._row_provider = row_provider
        self._assignment_provider = assignment_evidence_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self,
        command: CaptureAccountIdentityRawSourceCommand,
    ) -> AccountIdentityRawSource:
        """Capture or replay one actor-bound raw-source first winner."""

        if type(command) is not CaptureAccountIdentityRawSourceCommand:
            raise TypeError("command must be an exact CaptureAccountIdentityRawSourceCommand")
        CaptureAccountIdentityRawSourceCommand.__post_init__(command)
        cutoff = self._repository.now()
        _require_aware(cutoff, "repository cutoff")
        first = self._read_evidence(command, cutoff)
        with self._repository.atomic():
            winner = self._repository.get_winner(
                source_id=command.source_id,
                source_version=command.source_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                account_namespace=first[0].account_namespace,
                account_id=first[0].account_id,
                as_of=cutoff,
            )
            final = self._read_evidence(command, cutoff)
            if final != first:
                raise AccountIdentityRawSourceConflict(
                    "row observation or assignment evidence changed during capture"
                )
            row, evidence = final
            if winner is not None:
                checked = self._require_record(winner)
                self._validate_winner(checked, command, row, evidence, head, cutoff)
                return checked.source
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "repository recorded_at")
            if recorded_at < cutoff:
                raise AccountIdentityRawSourceCorruption("repository clock moved backwards")
            ttl_valid_until = min(cutoff + self._validity_period, evidence.valid_until)
            if recorded_at >= min(row.valid_until, ttl_valid_until):
                raise AccountIdentityRawSourceUnavailable(
                    "raw source evidence expired before it could be recorded"
                )
            predecessor = self._require_record(head).source if head is not None else None
            source = self._build_source(
                command,
                row,
                evidence,
                recorded_at=recorded_at,
                ttl_valid_until=ttl_valid_until,
                supersedes_content_hash=(predecessor.content_hash if predecessor else None),
            )
            if predecessor is not None:
                validate_account_identity_raw_source_successor(predecessor, source)
            record = PersistedAccountIdentityRawSource(source=source, captured_by=self._actor)
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(predecessor.content_hash if predecessor else None),
                recorded_at=recorded_at,
            )
            checked = self._require_record(persisted)
            if checked != record:
                raise AccountIdentityRawSourceConflict(
                    "concurrent account identity raw source first winner differs"
                )
            return checked.source

    def _read_evidence(
        self,
        command: CaptureAccountIdentityRawSourceCommand,
        cutoff: datetime,
    ) -> tuple[ExactUnifiedAccountRowObservation, ExactAccountOwnerAssignmentEvidence]:
        row_value = self._row_provider.get_exact_current(
            source_id=command.row_source_id,
            source_version=command.row_source_version,
            as_of=cutoff,
        )
        row = self._require_row(row_value, command, cutoff)
        evidence_value = self._assignment_provider.get_exact_current(
            evidence_id=command.assignment_evidence_id,
            evidence_version=command.assignment_evidence_version,
            as_of=cutoff,
        )
        evidence = self._require_evidence(evidence_value, command, row, cutoff)
        return row, evidence

    @staticmethod
    def _require_row(
        value: ExactUnifiedAccountRowObservation | None,
        command: CaptureAccountIdentityRawSourceCommand,
        cutoff: datetime,
    ) -> ExactUnifiedAccountRowObservation:
        if value is None:
            raise AccountIdentityRawSourceUnavailable(
                "exact current unified account row observation is unavailable"
            )
        if type(value) is not ExactUnifiedAccountRowObservation:
            raise AccountIdentityRawSourceCorruption("row observation type substitution")
        ExactUnifiedAccountRowObservation.__post_init__(value)
        if (
            value.source_id != command.row_source_id
            or value.source_version != command.row_source_version
        ):
            raise AccountIdentityRawSourceCorruption("row observation identity substitution")
        if not value.is_current_at(cutoff):
            raise AccountIdentityRawSourceUnavailable(
                "exact current unified account row observation is unavailable"
            )
        if value.account_type != "real":
            raise AccountIdentityRawSourceUnavailable("raw identity source requires a real account")
        return value

    @staticmethod
    def _require_evidence(
        value: ExactAccountOwnerAssignmentEvidence | None,
        command: CaptureAccountIdentityRawSourceCommand,
        row: ExactUnifiedAccountRowObservation,
        cutoff: datetime,
    ) -> ExactAccountOwnerAssignmentEvidence:
        if value is None:
            raise AccountIdentityRawSourceUnavailable(
                "exact Account owner assignment evidence is unavailable"
            )
        if type(value) is not ExactAccountOwnerAssignmentEvidence:
            raise AccountIdentityRawSourceCorruption("assignment evidence type substitution")
        ExactAccountOwnerAssignmentEvidence.__post_init__(value)
        if (
            value.evidence_id != command.assignment_evidence_id
            or value.evidence_version != command.assignment_evidence_version
        ):
            raise AccountIdentityRawSourceCorruption("assignment evidence identity substitution")
        if not value.is_current_at(cutoff):
            raise AccountIdentityRawSourceUnavailable(
                "exact Account owner assignment evidence is unavailable"
            )
        if not (
            value.row_source_id == row.source_id
            and value.row_source_version == row.source_version
            and value.row_source_content_hash == row.content_hash
            and value.account_namespace == row.account_namespace
            and value.account_id == row.account_id
            and value.underlying_unified_account_namespace
            == row.underlying_unified_account_namespace
            and value.underlying_unified_account_id == row.underlying_unified_account_id
        ):
            raise AccountIdentityRawSourceCorruption(
                "assignment evidence does not bind the exact row observation"
            )
        if (
            value.assignment_state == "authoritative"
            and value.assigned_owner_user_id != row.row_owner_user_id
        ):
            raise AccountIdentityRawSourceCorruption(
                "authoritative assignment evidence does not match the row owner"
            )
        return value

    def _build_source(
        self,
        command: CaptureAccountIdentityRawSourceCommand,
        row: ExactUnifiedAccountRowObservation,
        evidence: ExactAccountOwnerAssignmentEvidence,
        *,
        recorded_at: datetime,
        ttl_valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> AccountIdentityRawSource:
        return AccountIdentityRawSource(
            source_id=command.source_id,
            source_version=command.source_version,
            account_namespace=row.account_namespace,
            account_id=row.account_id,
            underlying_unified_account_namespace=row.underlying_unified_account_namespace,
            underlying_unified_account_id=row.underlying_unified_account_id,
            owner_user_id=evidence.assigned_owner_user_id,
            assignment_state=evidence.assignment_state,
            assignment_evidence_owner=evidence.owner,
            assignment_evidence_artifact_type=evidence.artifact_type,
            assignment_evidence_id=evidence.evidence_id,
            assignment_evidence_version=evidence.evidence_version,
            assignment_evidence_content_hash=evidence.content_hash,
            row_source_owner=row.owner,
            row_source_artifact_type=row.artifact_type,
            row_source_id=row.source_id,
            row_source_version=row.source_version,
            row_source_content_hash=row.content_hash,
            observed_at=row.observed_at,
            recorded_at=recorded_at,
            row_source_valid_until=row.valid_until,
            ttl_valid_until=ttl_valid_until,
            valid_until=min(row.valid_until, ttl_valid_until),
            is_active=row.is_active,
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        record: PersistedAccountIdentityRawSource,
        command: CaptureAccountIdentityRawSourceCommand,
        row: ExactUnifiedAccountRowObservation,
        evidence: ExactAccountOwnerAssignmentEvidence,
        head: PersistedAccountIdentityRawSource | None,
        cutoff: datetime,
    ) -> None:
        source = record.source
        if not source.is_knowable_at(cutoff):
            raise AccountIdentityRawSourceUnavailable(
                "persisted account identity raw source is unavailable"
            )
        if record.captured_by != self._actor:
            raise AccountIdentityRawSourceConflict(
                "account identity raw source belongs to another actor"
            )
        stable = self._build_source(
            command,
            row,
            evidence,
            recorded_at=source.recorded_at,
            ttl_valid_until=source.ttl_valid_until,
            supersedes_content_hash=source.supersedes_content_hash,
        )
        if stable != source:
            raise AccountIdentityRawSourceConflict(
                "account identity raw source identity has another first winner"
            )
        if head is None or self._require_record(head) != record:
            raise AccountIdentityRawSourceConflict(
                "account identity raw source is no longer the logical current head"
            )

    @staticmethod
    def _require_record(value: object) -> PersistedAccountIdentityRawSource:
        if type(value) is not PersistedAccountIdentityRawSource:
            raise AccountIdentityRawSourceCorruption("repository record type substitution")
        PersistedAccountIdentityRawSource.__post_init__(value)
        return value


class GetExactAccountIdentityRawSource:
    """Expose exact identity/hash/PIT reads of inactive source evidence."""

    def __init__(self, repository: AccountIdentityRawSourceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactAccountIdentityRawSourceCommand,
    ) -> AccountIdentityRawSource | None:
        """Return only the exact knowable inactive source evidence."""

        value = self._repository.get_exact_by_hash(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = CaptureAccountIdentityRawSource._require_record(value)
        source = record.source
        if (
            source.source_id != command.source_id
            or source.source_version != command.source_version
            or source.content_hash != command.expected_content_hash
        ):
            raise AccountIdentityRawSourceCorruption("exact source identity substitution")
        if not source.is_knowable_at(command.as_of):
            return None
        if source.activation_available or not source.must_not_execute:
            raise AccountIdentityRawSourceCorruption("source execution state substitution")
        return source


class GetCurrentAccountIdentityRawSource:
    """Return an exact inactive logical head matching all semantic selectors."""

    def __init__(self, repository: AccountIdentityRawSourceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentAccountIdentityRawSourceCommand,
    ) -> AccountIdentityRawSource | None:
        """Reject superseded heads and any semantic selector substitution."""

        source = GetExactAccountIdentityRawSource(self._repository).execute(
            GetExactAccountIdentityRawSourceCommand(
                source_id=command.source_id,
                source_version=command.source_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if source is None or _source_selectors(source) != _command_selectors(command):
            return None
        head = self._repository.get_current_head(
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            as_of=command.as_of,
        )
        if head is None or CaptureAccountIdentityRawSource._require_record(head).source != source:
            return None
        return source


def _source_selectors(source: AccountIdentityRawSource) -> tuple[object, ...]:
    return (
        source.owner,
        source.artifact_type,
        source.schema,
        source.account_namespace,
        source.account_id,
        source.underlying_unified_account_namespace,
        source.underlying_unified_account_id,
        source.owner_user_id,
        source.assignment_state,
        source.assignment_evidence_owner,
        source.assignment_evidence_artifact_type,
        source.assignment_evidence_id,
        source.assignment_evidence_version,
        source.assignment_evidence_content_hash,
        source.row_source_owner,
        source.row_source_artifact_type,
        source.row_source_id,
        source.row_source_version,
        source.row_source_content_hash,
        source.account_type,
        source.is_active,
    )


def _command_selectors(command: GetCurrentAccountIdentityRawSourceCommand) -> tuple[object, ...]:
    return (
        command.owner,
        command.artifact_type,
        command.schema,
        command.account_namespace,
        command.account_id,
        command.underlying_unified_account_namespace,
        command.underlying_unified_account_id,
        command.owner_user_id,
        command.assignment_state,
        command.assignment_evidence_owner,
        command.assignment_evidence_artifact_type,
        command.assignment_evidence_id,
        command.assignment_evidence_version,
        command.assignment_evidence_content_hash,
        command.row_source_owner,
        command.row_source_artifact_type,
        command.row_source_id,
        command.row_source_version,
        command.row_source_content_hash,
        command.account_type,
        command.is_active,
    )


__all__ = [
    "ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER",
    "AccountIdentityRawSourceActor",
    "AccountIdentityRawSourceConflict",
    "AccountIdentityRawSourceCorruption",
    "AccountIdentityRawSourceRepository",
    "AccountIdentityRawSourceUnavailable",
    "CaptureAccountIdentityRawSource",
    "CaptureAccountIdentityRawSourceCommand",
    "ExactAccountOwnerAssignmentEvidence",
    "ExactAccountOwnerAssignmentEvidenceProvider",
    "ExactUnifiedAccountRowObservation",
    "ExactUnifiedAccountRowObservationProvider",
    "GetCurrentAccountIdentityRawSource",
    "GetCurrentAccountIdentityRawSourceCommand",
    "GetExactAccountIdentityRawSource",
    "GetExactAccountIdentityRawSourceCommand",
    "PersistedAccountIdentityRawSource",
    "UNIFIED_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE",
    "UNIFIED_ACCOUNT_ROW_OBSERVATION_OWNER",
]
