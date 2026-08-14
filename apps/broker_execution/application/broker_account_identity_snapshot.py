"""ID-only issuance workflow for inactive Broker account identity snapshots."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.broker_execution.domain.broker_account_identity_snapshot import (
    ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE,
    ACCOUNT_IDENTITY_SOURCE_OWNER,
    AccountIdentitySourceRef,
    BrokerAccountIdentitySnapshot,
    KeyedBrokerAccountReferenceDigest,
    validate_broker_account_identity_snapshot_successor,
)


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
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


class BrokerAccountIdentitySnapshotUnavailable(ValueError):
    """An exact owner source or inactive snapshot is unavailable."""


class BrokerAccountIdentitySnapshotConflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class BrokerAccountIdentitySnapshotCorruption(ValueError):
    """A trusted source or persisted snapshot failed exact validation."""


@dataclass(frozen=True, slots=True)
class AccountIdentitySourceDefinition:
    """Consumer-owned projection of an exact current Account identity source."""

    source_id: str
    source_version: str
    content_hash: str
    account_namespace: str
    account_id: str
    owner_user_id: int
    account_type: str
    is_active: bool
    recorded_at: datetime
    valid_until: datetime
    is_current: bool = True
    owner: str = ACCOUNT_IDENTITY_SOURCE_OWNER
    artifact_type: str = ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        if self.owner != ACCOUNT_IDENTITY_SOURCE_OWNER:
            raise ValueError("Account source owner is fixed")
        if self.artifact_type != ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE:
            raise ValueError("Account source artifact_type is fixed")
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if self.account_type != "real":
            raise ValueError("Account source account_type must be real")
        if self.is_active is not True or self.is_current is not True:
            raise ValueError("Account source must be exact active and current")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("Account source validity window is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact current source is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return bool(
            self.is_current
            and self.is_active
            and self.account_type == "real"
            and self.recorded_at <= as_of < self.valid_until
        )

    def to_domain_ref(self) -> AccountIdentitySourceRef:
        """Project the validated consumer DTO into the Broker Domain reference."""

        return AccountIdentitySourceRef(
            source_id=self.source_id,
            source_version=self.source_version,
            content_hash=self.content_hash,
            account_namespace=self.account_namespace,
            account_id=self.account_id,
            owner_user_id=self.owner_user_id,
            account_type=self.account_type,
            is_active=self.is_active,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        )


@dataclass(frozen=True, slots=True)
class BrokerBindingAgentRawProjection:
    """Trusted current Broker binding and Agent facts with an opaque QMT reference."""

    broker_account_namespace: str
    broker_account_id: int
    binding_revision: int
    binding_content_hash: str
    binding_owner_user_id: int
    agent_id: str
    agent_version: str
    agent_content_hash: str
    agent_owner_user_id: int
    broker_account_category: str
    qmt_account_ref_opaque: bytes
    recorded_at: datetime
    is_current: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "broker_account_namespace",
            "agent_id",
            "agent_version",
            "broker_account_category",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise TypeError("broker_account_id must be an exact positive integer")
        if type(self.binding_revision) is not int or self.binding_revision <= 0:
            raise ValueError("binding_revision must be a positive integer")
        for field_name in ("binding_content_hash", "agent_content_hash"):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in ("binding_owner_user_id", "agent_owner_user_id"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if type(self.qmt_account_ref_opaque) is not bytes or not self.qmt_account_ref_opaque:
            raise TypeError("qmt_account_ref_opaque must be non-empty exact bytes")
        if len(self.qmt_account_ref_opaque) > 4096:
            raise ValueError("qmt_account_ref_opaque exceeds its maximum length")
        _require_aware(self.recorded_at, "recorded_at")
        if self.is_current is not True:
            raise ValueError("Broker binding and Agent projection must be current")


@dataclass(frozen=True, slots=True)
class BrokerAccountIdentityIssuanceActor:
    """Server-authenticated human staff actor allowed to issue identity evidence."""

    actor_id: str
    user_id: int
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("actor user_id must be a positive integer")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("identity snapshot issuer must be human staff")


@dataclass(frozen=True, slots=True)
class PersistedBrokerAccountIdentitySnapshot:
    """Actor-bound immutable record stored by the private Broker repository."""

    snapshot: BrokerAccountIdentitySnapshot
    issued_by: BrokerAccountIdentityIssuanceActor

    def __post_init__(self) -> None:
        if type(self.snapshot) is not BrokerAccountIdentitySnapshot:
            raise TypeError("snapshot must be an exact Broker account identity snapshot")
        BrokerAccountIdentitySnapshot.__post_init__(self.snapshot)
        if type(self.issued_by) is not BrokerAccountIdentityIssuanceActor:
            raise TypeError("issued_by must be an exact issuance actor")
        BrokerAccountIdentityIssuanceActor.__post_init__(self.issued_by)


@dataclass(frozen=True, slots=True)
class IssueBrokerAccountIdentitySnapshotCommand:
    """ID-only selector with no caller-supplied hashes, clocks, or QMT reference."""

    snapshot_id: str
    snapshot_version: str
    account_source_id: str
    account_source_version: str
    broker_account_namespace: str
    broker_account_id: int

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "snapshot_version",
            "account_source_id",
            "account_source_version",
            "broker_account_namespace",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise TypeError("broker_account_id must be an exact positive integer")


@dataclass(frozen=True, slots=True)
class GetExactBrokerAccountIdentitySnapshotCommand:
    """Exact identity/hash/PIT selector for one inactive snapshot."""

    snapshot_id: str
    snapshot_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.snapshot_id, "snapshot_id")
        _require_token(self.snapshot_version, "snapshot_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentBrokerAccountIdentitySnapshotCommand:
    """Closed selector for one exact inactive Broker-account logical head."""

    snapshot_id: str
    snapshot_version: str
    expected_content_hash: str
    broker_account_namespace: str
    broker_account_id: int
    account_source_id: str
    account_source_version: str
    account_source_content_hash: str
    account_namespace: str
    account_id: str
    owner_user_id: int
    account_type: str
    is_active: bool
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "snapshot_version",
            "broker_account_namespace",
            "account_source_id",
            "account_source_version",
            "account_namespace",
            "account_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_hash(self.account_source_content_hash, "account_source_content_hash")
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise TypeError("broker_account_id must be an exact positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if self.account_type != "real" or self.is_active is not True:
            raise ValueError("current selector requires an exact active real Account")
        _require_aware(self.as_of, "as_of")


class ExactCurrentAccountIdentitySourceProvider(Protocol):
    """Account Application public port projected for Broker consumption."""

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> AccountIdentitySourceDefinition | None:
        """Return one exact current Account identity at the cutoff."""


class ExactCurrentBrokerBindingAgentProvider(Protocol):
    """Broker-owned trusted projection port for current binding and Agent facts."""

    def get_exact_current(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> BrokerBindingAgentRawProjection | None:
        """Return exact current Broker binding and Agent raw facts."""


class BrokerAccountReferenceKeyedDigestService(Protocol):
    """One-way keyed digest boundary for opaque QMT account references."""

    def digest(self, *, opaque_reference: bytes) -> KeyedBrokerAccountReferenceDigest:
        """Return approved keyed digest metadata without exposing the input."""


class BrokerAccountIdentitySnapshotRepository(Protocol):
    """Private first-winner store and exact inactive PIT read authority."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Broker server clock."""

    def get_identity_winner(
        self, *, snapshot_id: str, snapshot_version: str, as_of: datetime
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        """Return one immutable snapshot identity winner."""

    def get_current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        """Return one inactive Broker-account logical head."""

    def append(
        self,
        record: PersistedBrokerAccountIdentitySnapshot,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot:
        """Append or return the exact first winner using predecessor CAS."""

    def get_exact_by_hash(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        """Return one exact inactive snapshot knowable at the cutoff."""


class IssueBrokerAccountIdentitySnapshot:
    """Issue one inactive identity snapshot from double-read trusted sources."""

    def __init__(
        self,
        *,
        account_provider: ExactCurrentAccountIdentitySourceProvider,
        broker_provider: ExactCurrentBrokerBindingAgentProvider,
        digest_service: BrokerAccountReferenceKeyedDigestService,
        actor: BrokerAccountIdentityIssuanceActor,
        repository: BrokerAccountIdentitySnapshotRepository,
        ttl: timedelta,
    ) -> None:
        if type(actor) is not BrokerAccountIdentityIssuanceActor:
            raise TypeError("actor must be an exact issuance actor")
        BrokerAccountIdentityIssuanceActor.__post_init__(actor)
        if type(ttl) is not timedelta or ttl <= timedelta(0):
            raise ValueError("snapshot ttl must be a positive timedelta")
        self._account_provider = account_provider
        self._broker_provider = broker_provider
        self._digest_service = digest_service
        self._actor = actor
        self._repository = repository
        self._ttl = ttl

    def execute(
        self, command: IssueBrokerAccountIdentitySnapshotCommand
    ) -> BrokerAccountIdentitySnapshot:
        """Double-read exact current sources and persist one inactive first winner."""

        with self._repository.atomic():
            BrokerAccountIdentityIssuanceActor.__post_init__(self._actor)
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Broker server clock")
            first = self._read_sources(command, recorded_at)
            account, broker = first
            winner = self._repository.get_identity_winner(
                snapshot_id=command.snapshot_id,
                snapshot_version=command.snapshot_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                broker_account_namespace=broker.broker_account_namespace,
                broker_account_id=broker.broker_account_id,
                as_of=recorded_at,
            )
            checked_head = self._require_exact_record(head) if head is not None else None
            final = self._read_sources(command, recorded_at)
            if first != final:
                raise BrokerAccountIdentitySnapshotCorruption(
                    "account identity owner sources changed during issuance"
                )
            digest = self._digest(final[1].qmt_account_ref_opaque)
            if winner is not None:
                self._validate_winner(
                    winner,
                    command,
                    final,
                    digest,
                    checked_head,
                    recorded_at,
                )
                return winner.snapshot
            candidate = self._build_snapshot(
                command,
                account,
                broker,
                digest,
                recorded_at=recorded_at,
                supersedes_snapshot_hash=(
                    checked_head.snapshot.content_hash if checked_head else None
                ),
            )
            if checked_head is not None:
                try:
                    validate_broker_account_identity_snapshot_successor(
                        checked_head.snapshot, candidate
                    )
                except (TypeError, ValueError) as error:
                    raise BrokerAccountIdentitySnapshotCorruption(
                        "Broker account identity successor is invalid"
                    ) from error
            record = PersistedBrokerAccountIdentitySnapshot(candidate, self._actor)
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(
                    checked_head.snapshot.content_hash if checked_head else None
                ),
                recorded_at=recorded_at,
            )
            checked = self._require_exact_record(persisted)
            if checked != record:
                raise BrokerAccountIdentitySnapshotConflict(
                    "concurrent account identity first winner differs"
                )
            return checked.snapshot

    def _read_sources(
        self,
        command: IssueBrokerAccountIdentitySnapshotCommand,
        as_of: datetime,
    ) -> tuple[AccountIdentitySourceDefinition, BrokerBindingAgentRawProjection]:
        account = self._account_provider.get_exact_current(
            source_id=command.account_source_id,
            source_version=command.account_source_version,
            as_of=as_of,
        )
        broker = self._broker_provider.get_exact_current(
            broker_account_namespace=command.broker_account_namespace,
            broker_account_id=command.broker_account_id,
            as_of=as_of,
        )
        checked_account = self._require_account(account, command, as_of)
        checked_broker = self._require_broker(broker, command, as_of)
        if checked_broker.binding_owner_user_id != checked_account.owner_user_id:
            raise BrokerAccountIdentitySnapshotCorruption(
                "Broker binding owner does not match the Account owner"
            )
        if checked_broker.agent_owner_user_id != checked_account.owner_user_id:
            raise BrokerAccountIdentitySnapshotCorruption(
                "Broker Agent owner does not match the Account owner"
            )
        return checked_account, checked_broker

    @staticmethod
    def _require_account(
        value: AccountIdentitySourceDefinition | None,
        command: IssueBrokerAccountIdentitySnapshotCommand,
        as_of: datetime,
    ) -> AccountIdentitySourceDefinition:
        if value is None:
            raise BrokerAccountIdentitySnapshotUnavailable(
                "exact current Account identity source is unavailable"
            )
        if type(value) is not AccountIdentitySourceDefinition:
            raise BrokerAccountIdentitySnapshotCorruption("Account source type substitution")
        AccountIdentitySourceDefinition.__post_init__(value)
        if (
            value.source_id != command.account_source_id
            or value.source_version != command.account_source_version
        ):
            raise BrokerAccountIdentitySnapshotCorruption("Account source identity substitution")
        if not value.is_active_at(as_of):
            raise BrokerAccountIdentitySnapshotUnavailable(
                "exact current Account identity source is unavailable"
            )
        return value

    @staticmethod
    def _require_broker(
        value: BrokerBindingAgentRawProjection | None,
        command: IssueBrokerAccountIdentitySnapshotCommand,
        as_of: datetime,
    ) -> BrokerBindingAgentRawProjection:
        if value is None:
            raise BrokerAccountIdentitySnapshotUnavailable(
                "exact current Broker binding and Agent source is unavailable"
            )
        if type(value) is not BrokerBindingAgentRawProjection:
            raise BrokerAccountIdentitySnapshotCorruption("Broker source type substitution")
        BrokerBindingAgentRawProjection.__post_init__(value)
        if (
            value.broker_account_namespace != command.broker_account_namespace
            or value.broker_account_id != command.broker_account_id
        ):
            raise BrokerAccountIdentitySnapshotCorruption("Broker source identity substitution")
        if value.recorded_at > as_of or value.is_current is not True:
            raise BrokerAccountIdentitySnapshotUnavailable(
                "exact current Broker binding and Agent source is unavailable"
            )
        return value

    def _digest(self, opaque_reference: bytes) -> KeyedBrokerAccountReferenceDigest:
        value = self._digest_service.digest(opaque_reference=opaque_reference)
        if type(value) is not KeyedBrokerAccountReferenceDigest:
            raise BrokerAccountIdentitySnapshotCorruption("keyed digest type substitution")
        KeyedBrokerAccountReferenceDigest.__post_init__(value)
        return value

    def _build_snapshot(
        self,
        command: IssueBrokerAccountIdentitySnapshotCommand,
        account: AccountIdentitySourceDefinition,
        broker: BrokerBindingAgentRawProjection,
        digest: KeyedBrokerAccountReferenceDigest,
        *,
        recorded_at: datetime,
        supersedes_snapshot_hash: str | None,
    ) -> BrokerAccountIdentitySnapshot:
        ttl_valid_until = recorded_at + self._ttl
        return BrokerAccountIdentitySnapshot(
            snapshot_id=command.snapshot_id,
            snapshot_version=command.snapshot_version,
            broker_account_namespace=broker.broker_account_namespace,
            broker_account_id=broker.broker_account_id,
            owner_user_id=account.owner_user_id,
            account_type=account.account_type,
            is_active=account.is_active,
            account_source_ref=account.to_domain_ref(),
            binding_revision=broker.binding_revision,
            binding_owner_user_id=broker.binding_owner_user_id,
            binding_content_hash=broker.binding_content_hash,
            agent_id=broker.agent_id,
            agent_version=broker.agent_version,
            agent_owner_user_id=broker.agent_owner_user_id,
            agent_content_hash=broker.agent_content_hash,
            qmt_account_ref_digest=digest,
            broker_account_category=broker.broker_account_category,
            issued_at=recorded_at,
            recorded_at=recorded_at,
            ttl_valid_until=ttl_valid_until,
            valid_until=min(account.valid_until, ttl_valid_until),
            supersedes_snapshot_hash=supersedes_snapshot_hash,
        )

    def _validate_winner(
        self,
        winner: PersistedBrokerAccountIdentitySnapshot,
        command: IssueBrokerAccountIdentitySnapshotCommand,
        sources: tuple[AccountIdentitySourceDefinition, BrokerBindingAgentRawProjection],
        digest: KeyedBrokerAccountReferenceDigest,
        head: PersistedBrokerAccountIdentitySnapshot | None,
        as_of: datetime,
    ) -> None:
        record = self._require_exact_record(winner)
        value = record.snapshot
        if not value.is_knowable_at(as_of):
            raise BrokerAccountIdentitySnapshotUnavailable(
                "persisted Broker account identity snapshot is unavailable"
            )
        if record.issued_by != self._actor:
            raise BrokerAccountIdentitySnapshotConflict(
                "Broker account identity belongs to another server actor"
            )
        stable = self._build_snapshot(
            command,
            sources[0],
            sources[1],
            digest,
            recorded_at=value.recorded_at,
            supersedes_snapshot_hash=value.supersedes_snapshot_hash,
        )
        if stable != value:
            raise BrokerAccountIdentitySnapshotConflict(
                "Broker account identity has another first winner"
            )
        if head is None or self._require_exact_record(head) != record:
            raise BrokerAccountIdentitySnapshotConflict(
                "Broker account identity is no longer the logical current head"
            )

    @staticmethod
    def _require_exact_snapshot(value: object) -> BrokerAccountIdentitySnapshot:
        if type(value) is not BrokerAccountIdentitySnapshot:
            raise BrokerAccountIdentitySnapshotCorruption("snapshot type substitution")
        BrokerAccountIdentitySnapshot.__post_init__(value)
        return value

    @staticmethod
    def _require_exact_record(value: object) -> PersistedBrokerAccountIdentitySnapshot:
        if type(value) is not PersistedBrokerAccountIdentitySnapshot:
            raise BrokerAccountIdentitySnapshotCorruption("snapshot record type substitution")
        PersistedBrokerAccountIdentitySnapshot.__post_init__(value)
        return value


class GetExactBrokerAccountIdentitySnapshot:
    """Expose exact inactive identity/hash/PIT reads."""

    def __init__(self, repository: BrokerAccountIdentitySnapshotRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactBrokerAccountIdentitySnapshotCommand
    ) -> BrokerAccountIdentitySnapshot | None:
        """Return only the exact knowable inactive snapshot."""

        value = self._repository.get_exact_by_hash(
            snapshot_id=command.snapshot_id,
            snapshot_version=command.snapshot_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = IssueBrokerAccountIdentitySnapshot._require_exact_record(value)
        checked = record.snapshot
        if (
            checked.snapshot_id != command.snapshot_id
            or checked.snapshot_version != command.snapshot_version
            or checked.content_hash != command.expected_content_hash
        ):
            raise BrokerAccountIdentitySnapshotCorruption("snapshot exact identity substitution")
        if not checked.is_knowable_at(command.as_of):
            return None
        if (
            checked.authority_scope != "identity_evidence_only"
            or checked.permission != "inactive"
            or checked.activation_available
            or not checked.must_not_execute
        ):
            raise BrokerAccountIdentitySnapshotCorruption("snapshot authority substitution")
        return checked


class GetCurrentBrokerAccountIdentitySnapshot:
    """Return only one exact inactive logical head matching a closed selector."""

    def __init__(self, repository: BrokerAccountIdentitySnapshotRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetCurrentBrokerAccountIdentitySnapshotCommand
    ) -> BrokerAccountIdentitySnapshot | None:
        """Reject historical heads and Account/Broker source substitution."""

        value = GetExactBrokerAccountIdentitySnapshot(self._repository).execute(
            GetExactBrokerAccountIdentitySnapshotCommand(
                snapshot_id=command.snapshot_id,
                snapshot_version=command.snapshot_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if value is None:
            return None
        source = value.account_source_ref
        if not (
            value.broker_account_namespace == command.broker_account_namespace
            and value.broker_account_id == command.broker_account_id
            and source.source_id == command.account_source_id
            and source.source_version == command.account_source_version
            and source.content_hash == command.account_source_content_hash
            and source.account_namespace == command.account_namespace
            and source.account_id == command.account_id
            and source.owner_user_id == command.owner_user_id
            and source.account_type == command.account_type
            and source.is_active is command.is_active
            and value.owner_user_id == command.owner_user_id
            and value.account_type == command.account_type
            and value.is_active is command.is_active
        ):
            raise BrokerAccountIdentitySnapshotCorruption("snapshot current selector substitution")
        head = self._repository.get_current_head(
            broker_account_namespace=value.broker_account_namespace,
            broker_account_id=value.broker_account_id,
            as_of=command.as_of,
        )
        if head is None:
            return None
        checked_head = IssueBrokerAccountIdentitySnapshot._require_exact_record(head)
        return value if checked_head.snapshot == value else None


__all__ = [
    "AccountIdentitySourceDefinition",
    "BrokerAccountIdentityIssuanceActor",
    "BrokerAccountIdentitySnapshotConflict",
    "BrokerAccountIdentitySnapshotCorruption",
    "BrokerAccountIdentitySnapshotRepository",
    "BrokerAccountIdentitySnapshotUnavailable",
    "BrokerAccountReferenceKeyedDigestService",
    "BrokerBindingAgentRawProjection",
    "ExactCurrentAccountIdentitySourceProvider",
    "ExactCurrentBrokerBindingAgentProvider",
    "GetCurrentBrokerAccountIdentitySnapshot",
    "GetCurrentBrokerAccountIdentitySnapshotCommand",
    "GetExactBrokerAccountIdentitySnapshot",
    "GetExactBrokerAccountIdentitySnapshotCommand",
    "IssueBrokerAccountIdentitySnapshot",
    "IssueBrokerAccountIdentitySnapshotCommand",
    "PersistedBrokerAccountIdentitySnapshot",
]
