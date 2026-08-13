"""ID-only issuance workflow for inactive Account-owned identity evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.account_identity_snapshot import (
    ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE,
    ACCOUNT_IDENTITY_SNAPSHOT_OWNER,
    ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA,
    ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE,
    ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER,
    AccountIdentitySnapshot,
    validate_account_identity_snapshot_successor,
)

TRUSTED_RAW_ACCOUNT_SOURCE_OWNER = "account"
TRUSTED_RAW_ACCOUNT_SOURCE_ARTIFACT_TYPE = "account_identity_raw_source"


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


class AccountIdentitySnapshotUnavailable(ValueError):
    """Required exact-current Account identity evidence is unavailable."""


class AccountIdentitySnapshotConflict(ValueError):
    """An immutable identity or logical head has another first winner."""


class AccountIdentitySnapshotCorruption(ValueError):
    """A trusted provider or repository returned substituted evidence."""


@dataclass(frozen=True, slots=True)
class AccountIdentitySnapshotActor:
    """Server-authenticated human staff identity issuing the evidence."""

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
            raise ValueError("account identity snapshot actor must be human staff")


@dataclass(frozen=True, slots=True)
class TrustedRawAccountIdentitySource:
    """Consumer-owned exact projection of one raw unified account source."""

    source_id: str
    source_version: str
    content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    owner_user_id: int | None
    account_type: str
    is_active: bool
    legacy_default_user_assignment: bool
    recorded_at: datetime
    valid_until: datetime
    owner: str = TRUSTED_RAW_ACCOUNT_SOURCE_OWNER
    artifact_type: str = TRUSTED_RAW_ACCOUNT_SOURCE_ARTIFACT_TYPE

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
        if self.owner_user_id is not None and (
            type(self.owner_user_id) is not int or self.owner_user_id <= 0
        ):
            raise ValueError("owner_user_id must be null or an exact positive integer")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        if type(self.legacy_default_user_assignment) is not bool:
            raise TypeError("legacy_default_user_assignment must be an exact boolean")
        if (
            self.owner != TRUSTED_RAW_ACCOUNT_SOURCE_OWNER
            or self.artifact_type != TRUSTED_RAW_ACCOUNT_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("raw account source authority or artifact type is invalid")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("raw account source validity window is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the exact raw source is knowable and current."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class ManualAccountOwnerReclaimReceipt:
    """Exact Account-owned receipt replacing an untrusted legacy default user."""

    receipt_id: str
    receipt_version: str
    content_hash: str
    raw_source_id: str
    raw_source_version: str
    raw_source_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    reclaimed_owner_user_id: int
    approved_by: AccountIdentitySnapshotActor
    recorded_at: datetime
    valid_until: datetime
    owner: str = ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER
    artifact_type: str = ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "receipt_version",
            "raw_source_id",
            "raw_source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in ("content_hash", "raw_source_content_hash"):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if type(self.reclaimed_owner_user_id) is not int:
            raise TypeError("reclaimed_owner_user_id must be an exact integer")
        if self.reclaimed_owner_user_id <= 0:
            raise ValueError("reclaimed_owner_user_id must be positive")
        if type(self.approved_by) is not AccountIdentitySnapshotActor:
            raise TypeError("approved_by must be an exact AccountIdentitySnapshotActor")
        AccountIdentitySnapshotActor.__post_init__(self.approved_by)
        if (
            self.owner != ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER
            or self.artifact_type != ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE
        ):
            raise ValueError("manual reclaim receipt authority or artifact type is invalid")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("manual reclaim receipt validity window is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the exact reclaim receipt is knowable and current."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class PersistedAccountIdentitySnapshot:
    """Repository record pairing immutable evidence with its server actor."""

    snapshot: AccountIdentitySnapshot
    issued_by: AccountIdentitySnapshotActor

    def __post_init__(self) -> None:
        if type(self.snapshot) is not AccountIdentitySnapshot:
            raise TypeError("snapshot must be an exact AccountIdentitySnapshot")
        AccountIdentitySnapshot.__post_init__(self.snapshot)
        if type(self.issued_by) is not AccountIdentitySnapshotActor:
            raise TypeError("issued_by must be an exact AccountIdentitySnapshotActor")
        AccountIdentitySnapshotActor.__post_init__(self.issued_by)


@dataclass(frozen=True, slots=True)
class IssueAccountIdentitySnapshotCommand:
    """ID-only selector for an authoritative account identity source."""

    source_id: str
    source_version: str
    raw_source_id: str
    raw_source_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "raw_source_id",
            "raw_source_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ReclaimLegacyAccountIdentitySnapshotCommand:
    """ID-only selector for an exact legacy owner reclaim receipt."""

    source_id: str
    source_version: str
    raw_source_id: str
    raw_source_version: str
    reclaim_receipt_id: str
    reclaim_receipt_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "raw_source_id",
            "raw_source_version",
            "reclaim_receipt_id",
            "reclaim_receipt_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GetExactAccountIdentitySnapshotCommand:
    """Exact identity/hash/PIT selector for inactive evidence."""

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
class GetCurrentAccountIdentitySnapshotCommand:
    """Closed logical-current selector for inactive identity evidence."""

    source_id: str
    source_version: str
    expected_content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    owner_user_id: int
    provenance_kind: str
    legacy_default_user_assignment: bool
    underlying_source_id: str
    underlying_source_version: str
    underlying_source_content_hash: str
    reclaim_receipt_owner: str | None
    reclaim_receipt_artifact_type: str | None
    reclaim_receipt_id: str | None
    reclaim_receipt_version: str | None
    reclaim_receipt_content_hash: str | None
    account_type: str
    is_active: bool
    as_of: datetime
    owner: str = ACCOUNT_IDENTITY_SNAPSHOT_OWNER
    artifact_type: str = ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE
    schema: str = ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "provenance_kind",
            "underlying_source_id",
            "underlying_source_version",
            "account_type",
            "owner",
            "artifact_type",
            "schema",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "expected_content_hash",
            "underlying_source_content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be an exact positive integer")
        if type(self.legacy_default_user_assignment) is not bool:
            raise TypeError("legacy_default_user_assignment must be an exact boolean")
        if self.account_type != "real" or self.is_active is not True:
            raise ValueError("current selector requires an active real account")
        if (
            self.owner != ACCOUNT_IDENTITY_SNAPSHOT_OWNER
            or self.artifact_type != ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE
            or self.schema != ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA
        ):
            raise ValueError("current selector account authority is invalid")
        receipt_values = (
            self.reclaim_receipt_owner,
            self.reclaim_receipt_artifact_type,
            self.reclaim_receipt_id,
            self.reclaim_receipt_version,
            self.reclaim_receipt_content_hash,
        )
        if self.provenance_kind == "authoritative":
            if self.legacy_default_user_assignment:
                raise ValueError("authoritative selector cannot represent a legacy account")
            if any(value is not None for value in receipt_values):
                raise ValueError("authoritative selector cannot carry a reclaim receipt")
        elif self.provenance_kind == "manual_reclaim":
            if not self.legacy_default_user_assignment:
                raise ValueError("manual reclaim selector requires a legacy account")
            if any(value is None for value in receipt_values):
                raise ValueError("manual reclaim selector requires an exact receipt")
            if (
                self.reclaim_receipt_owner != ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER
                or self.reclaim_receipt_artifact_type != ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE
            ):
                raise ValueError("manual reclaim selector receipt authority is invalid")
            for field_name in (
                "reclaim_receipt_owner",
                "reclaim_receipt_artifact_type",
                "reclaim_receipt_id",
                "reclaim_receipt_version",
            ):
                _require_token(getattr(self, field_name), field_name)
            _require_hash(self.reclaim_receipt_content_hash, "reclaim_receipt_content_hash")
        else:
            raise ValueError("current selector provenance_kind is invalid")
        _require_aware(self.as_of, "as_of")


class ExactCurrentRawAccountIdentitySourceProvider(Protocol):
    """Load one exact current Account-consumer raw account projection."""

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> TrustedRawAccountIdentitySource | None:
        """Return the exact raw account source at one server cutoff."""


class ExactCurrentManualAccountOwnerReclaimReceiptProvider(Protocol):
    """Load one exact current Account-owned manual reclaim receipt."""

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> ManualAccountOwnerReclaimReceipt | None:
        """Return the exact reclaim receipt at one server cutoff."""


class AccountIdentitySnapshotRepository(Protocol):
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
    ) -> PersistedAccountIdentitySnapshot | None:
        """Return the immutable first winner for one source identity."""

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        """Return the full-chain head recorded by the cutoff, even if expired."""

    def append(
        self,
        record: PersistedAccountIdentitySnapshot,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountIdentitySnapshot:
        """Append or return one first winner using predecessor CAS."""

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        """Return one exact inactive record knowable at the cutoff."""


class _RegisterAccountIdentitySnapshot:
    def __init__(
        self,
        *,
        raw_source_provider: ExactCurrentRawAccountIdentitySourceProvider,
        reclaim_receipt_provider: ExactCurrentManualAccountOwnerReclaimReceiptProvider | None,
        repository: AccountIdentitySnapshotRepository,
        actor: AccountIdentitySnapshotActor,
        validity_period: timedelta,
    ) -> None:
        AccountIdentitySnapshotActor.__post_init__(actor)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be a positive timedelta")
        self._raw_source_provider = raw_source_provider
        self._reclaim_receipt_provider = reclaim_receipt_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self,
        *,
        command: IssueAccountIdentitySnapshotCommand | ReclaimLegacyAccountIdentitySnapshotCommand,
        manual_reclaim: bool,
    ) -> AccountIdentitySnapshot:
        """Double-read exact evidence and CAS-append one inactive first winner."""

        with self._repository.atomic():
            cutoff = self._repository.now()
            _require_aware(cutoff, "Account server clock")
            first = self._read_evidence(command, cutoff, manual_reclaim=manual_reclaim)
            raw_source, receipt = first
            winner = self._repository.get_winner(
                source_id=command.source_id,
                source_version=command.source_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                account_namespace=raw_source.account_namespace,
                account_id=raw_source.account_id,
                as_of=cutoff,
            )
            final = self._read_evidence(command, cutoff, manual_reclaim=manual_reclaim)
            if first != final:
                raise AccountIdentitySnapshotCorruption(
                    "account identity source evidence changed during issuance"
                )
            raw_source, receipt = final
            if winner is not None:
                self._validate_winner(
                    winner,
                    command,
                    raw_source,
                    receipt,
                    head,
                    cutoff,
                    manual_reclaim=manual_reclaim,
                )
                return winner.snapshot
            candidate = self._build_snapshot(
                command,
                raw_source,
                receipt,
                issued_at=cutoff,
                recorded_at=cutoff,
                ttl_valid_until=self._ttl_valid_until(cutoff, receipt),
                supersedes_content_hash=(head.snapshot.content_hash if head else None),
                manual_reclaim=manual_reclaim,
            )
            if head is not None:
                checked_head = self._require_exact_record(head)
                try:
                    validate_account_identity_snapshot_successor(
                        checked_head.snapshot,
                        candidate,
                    )
                except (TypeError, ValueError) as error:
                    raise AccountIdentitySnapshotCorruption(
                        "account identity snapshot successor is invalid"
                    ) from error
            record = PersistedAccountIdentitySnapshot(candidate, self._actor)
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(head.snapshot.content_hash if head else None),
                recorded_at=cutoff,
            )
            checked = self._require_exact_record(persisted)
            if checked != record:
                raise AccountIdentitySnapshotConflict(
                    "concurrent account identity snapshot first winner differs"
                )
            return checked.snapshot

    def _read_evidence(
        self,
        command: IssueAccountIdentitySnapshotCommand | ReclaimLegacyAccountIdentitySnapshotCommand,
        as_of: datetime,
        *,
        manual_reclaim: bool,
    ) -> tuple[
        TrustedRawAccountIdentitySource,
        ManualAccountOwnerReclaimReceipt | None,
    ]:
        raw_value = self._raw_source_provider.get_exact_current(
            source_id=command.raw_source_id,
            source_version=command.raw_source_version,
            as_of=as_of,
        )
        raw_source = self._require_raw_source(raw_value, command, as_of)
        if manual_reclaim:
            if type(command) is not ReclaimLegacyAccountIdentitySnapshotCommand:
                raise AccountIdentitySnapshotCorruption("manual reclaim command substitution")
            if not raw_source.legacy_default_user_assignment:
                raise AccountIdentitySnapshotUnavailable(
                    "manual reclaim is available only for a legacy default-user source"
                )
            if self._reclaim_receipt_provider is None:
                raise AccountIdentitySnapshotUnavailable(
                    "exact manual account owner reclaim receipt is unavailable"
                )
            receipt_value = self._reclaim_receipt_provider.get_exact_current(
                receipt_id=command.reclaim_receipt_id,
                receipt_version=command.reclaim_receipt_version,
                as_of=as_of,
            )
            receipt = self._require_receipt(receipt_value, command, raw_source, as_of)
            return raw_source, receipt
        if type(command) is not IssueAccountIdentitySnapshotCommand:
            raise AccountIdentitySnapshotCorruption("authoritative issue command substitution")
        if raw_source.legacy_default_user_assignment:
            raise AccountIdentitySnapshotUnavailable(
                "legacy default-user source requires an exact manual reclaim receipt"
            )
        if raw_source.owner_user_id is None:
            raise AccountIdentitySnapshotUnavailable(
                "authoritative raw account owner identity is unavailable"
            )
        return raw_source, None

    @staticmethod
    def _require_raw_source(
        value: TrustedRawAccountIdentitySource | None,
        command: IssueAccountIdentitySnapshotCommand | ReclaimLegacyAccountIdentitySnapshotCommand,
        as_of: datetime,
    ) -> TrustedRawAccountIdentitySource:
        if value is None:
            raise AccountIdentitySnapshotUnavailable(
                "exact current raw account identity source is unavailable"
            )
        if type(value) is not TrustedRawAccountIdentitySource:
            raise AccountIdentitySnapshotCorruption("raw account source type substitution")
        TrustedRawAccountIdentitySource.__post_init__(value)
        if (
            value.source_id != command.raw_source_id
            or value.source_version != command.raw_source_version
        ):
            raise AccountIdentitySnapshotCorruption("raw account source identity substitution")
        if not value.is_current_at(as_of):
            raise AccountIdentitySnapshotUnavailable(
                "exact current raw account identity source is unavailable"
            )
        if value.account_type != "real" or value.is_active is not True:
            raise AccountIdentitySnapshotUnavailable(
                "account identity snapshot requires an active real raw account"
            )
        return value

    def _require_receipt(
        self,
        value: ManualAccountOwnerReclaimReceipt | None,
        command: ReclaimLegacyAccountIdentitySnapshotCommand,
        raw_source: TrustedRawAccountIdentitySource,
        as_of: datetime,
    ) -> ManualAccountOwnerReclaimReceipt:
        if value is None:
            raise AccountIdentitySnapshotUnavailable(
                "exact manual account owner reclaim receipt is unavailable"
            )
        if type(value) is not ManualAccountOwnerReclaimReceipt:
            raise AccountIdentitySnapshotCorruption("manual reclaim receipt type substitution")
        ManualAccountOwnerReclaimReceipt.__post_init__(value)
        if (
            value.receipt_id != command.reclaim_receipt_id
            or value.receipt_version != command.reclaim_receipt_version
        ):
            raise AccountIdentitySnapshotCorruption("manual reclaim receipt identity substitution")
        if not value.is_current_at(as_of):
            raise AccountIdentitySnapshotUnavailable(
                "exact manual account owner reclaim receipt is unavailable"
            )
        if value.approved_by != self._actor:
            raise AccountIdentitySnapshotConflict(
                "manual reclaim receipt belongs to another server actor"
            )
        if not (
            value.raw_source_id == raw_source.source_id
            and value.raw_source_version == raw_source.source_version
            and value.raw_source_content_hash == raw_source.content_hash
            and value.account_namespace == raw_source.account_namespace
            and value.account_id == raw_source.account_id
            and value.underlying_unified_account_namespace
            == raw_source.underlying_unified_account_namespace
            and value.underlying_unified_account_id == raw_source.underlying_unified_account_id
        ):
            raise AccountIdentitySnapshotCorruption(
                "manual reclaim receipt does not bind the exact raw account source"
            )
        return value

    def _ttl_valid_until(
        self,
        cutoff: datetime,
        receipt: ManualAccountOwnerReclaimReceipt | None,
    ) -> datetime:
        policy_limit = cutoff + self._validity_period
        return min(policy_limit, receipt.valid_until) if receipt else policy_limit

    def _build_snapshot(
        self,
        command: IssueAccountIdentitySnapshotCommand | ReclaimLegacyAccountIdentitySnapshotCommand,
        raw_source: TrustedRawAccountIdentitySource,
        receipt: ManualAccountOwnerReclaimReceipt | None,
        *,
        issued_at: datetime,
        recorded_at: datetime,
        ttl_valid_until: datetime,
        supersedes_content_hash: str | None,
        manual_reclaim: bool,
    ) -> AccountIdentitySnapshot:
        owner_user_id = (
            receipt.reclaimed_owner_user_id if receipt is not None else raw_source.owner_user_id
        )
        if owner_user_id is None:
            raise AccountIdentitySnapshotUnavailable("account owner identity is unavailable")
        return AccountIdentitySnapshot(
            source_id=command.source_id,
            source_version=command.source_version,
            account_namespace=raw_source.account_namespace,
            account_id=raw_source.account_id,
            underlying_unified_account_namespace=(raw_source.underlying_unified_account_namespace),
            underlying_unified_account_id=raw_source.underlying_unified_account_id,
            owner_user_id=owner_user_id,
            provenance_kind="manual_reclaim" if manual_reclaim else "authoritative",
            legacy_default_user_assignment=raw_source.legacy_default_user_assignment,
            underlying_source_id=raw_source.source_id,
            underlying_source_version=raw_source.source_version,
            underlying_source_content_hash=raw_source.content_hash,
            underlying_source_recorded_at=raw_source.recorded_at,
            underlying_source_valid_until=raw_source.valid_until,
            ttl_valid_until=ttl_valid_until,
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=min(raw_source.valid_until, ttl_valid_until),
            reclaim_receipt_owner=receipt.owner if receipt else None,
            reclaim_receipt_artifact_type=receipt.artifact_type if receipt else None,
            reclaim_receipt_id=receipt.receipt_id if receipt else None,
            reclaim_receipt_version=receipt.receipt_version if receipt else None,
            reclaim_receipt_content_hash=receipt.content_hash if receipt else None,
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        winner: PersistedAccountIdentitySnapshot,
        command: IssueAccountIdentitySnapshotCommand | ReclaimLegacyAccountIdentitySnapshotCommand,
        raw_source: TrustedRawAccountIdentitySource,
        receipt: ManualAccountOwnerReclaimReceipt | None,
        head: PersistedAccountIdentitySnapshot | None,
        as_of: datetime,
        *,
        manual_reclaim: bool,
    ) -> None:
        record = self._require_exact_record(winner)
        value = record.snapshot
        if not value.is_knowable_at(as_of):
            raise AccountIdentitySnapshotUnavailable(
                "persisted account identity snapshot is unavailable"
            )
        if record.issued_by != self._actor:
            raise AccountIdentitySnapshotConflict(
                "account identity snapshot identity belongs to another actor"
            )
        stable = self._build_snapshot(
            command,
            raw_source,
            receipt,
            issued_at=value.issued_at,
            recorded_at=value.recorded_at,
            ttl_valid_until=value.ttl_valid_until,
            supersedes_content_hash=value.supersedes_content_hash,
            manual_reclaim=manual_reclaim,
        )
        if stable != value:
            raise AccountIdentitySnapshotConflict(
                "account identity snapshot identity has another first winner"
            )
        if head is None or self._require_exact_record(head) != record:
            raise AccountIdentitySnapshotConflict(
                "account identity snapshot is no longer the logical current head"
            )

    @staticmethod
    def _require_exact_record(value: object) -> PersistedAccountIdentitySnapshot:
        if type(value) is not PersistedAccountIdentitySnapshot:
            raise AccountIdentitySnapshotCorruption(
                "account identity snapshot record type substitution"
            )
        PersistedAccountIdentitySnapshot.__post_init__(value)
        return value


class IssueAccountIdentitySnapshot:
    """Issue Account identity evidence from one authoritative raw source."""

    def __init__(
        self,
        *,
        raw_source_provider: ExactCurrentRawAccountIdentitySourceProvider,
        repository: AccountIdentitySnapshotRepository,
        actor: AccountIdentitySnapshotActor,
        validity_period: timedelta,
    ) -> None:
        self._register = _RegisterAccountIdentitySnapshot(
            raw_source_provider=raw_source_provider,
            reclaim_receipt_provider=None,
            repository=repository,
            actor=actor,
            validity_period=validity_period,
        )

    def execute(self, command: IssueAccountIdentitySnapshotCommand) -> AccountIdentitySnapshot:
        """Issue or replay one authoritative inactive source identity."""

        return self._register.execute(command=command, manual_reclaim=False)


class ReclaimLegacyAccountIdentitySnapshot:
    """Issue identity evidence only after an exact legacy owner reclaim receipt."""

    def __init__(
        self,
        *,
        raw_source_provider: ExactCurrentRawAccountIdentitySourceProvider,
        reclaim_receipt_provider: ExactCurrentManualAccountOwnerReclaimReceiptProvider,
        repository: AccountIdentitySnapshotRepository,
        actor: AccountIdentitySnapshotActor,
        validity_period: timedelta,
    ) -> None:
        self._register = _RegisterAccountIdentitySnapshot(
            raw_source_provider=raw_source_provider,
            reclaim_receipt_provider=reclaim_receipt_provider,
            repository=repository,
            actor=actor,
            validity_period=validity_period,
        )

    def execute(
        self,
        command: ReclaimLegacyAccountIdentitySnapshotCommand,
    ) -> AccountIdentitySnapshot:
        """Reclaim or replay one legacy inactive source identity."""

        return self._register.execute(command=command, manual_reclaim=True)


class GetExactAccountIdentitySnapshot:
    """Expose exact identity/hash/PIT reads of inactive evidence."""

    def __init__(self, repository: AccountIdentitySnapshotRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactAccountIdentitySnapshotCommand,
    ) -> AccountIdentitySnapshot | None:
        """Return only the exact knowable inactive identity evidence."""

        value = self._repository.get_exact_by_hash(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = _RegisterAccountIdentitySnapshot._require_exact_record(value)
        snapshot = record.snapshot
        if (
            snapshot.source_id != command.source_id
            or snapshot.source_version != command.source_version
            or snapshot.content_hash != command.expected_content_hash
        ):
            raise AccountIdentitySnapshotCorruption(
                "account identity snapshot exact identity substitution"
            )
        if not snapshot.is_knowable_at(command.as_of):
            return None
        if (
            snapshot.activation_available
            or not snapshot.must_not_execute
            or snapshot.permission != "identity_evidence_only"
            or snapshot.status != "inactive"
        ):
            raise AccountIdentitySnapshotCorruption(
                "account identity snapshot execution state substitution"
            )
        return snapshot


class GetCurrentAccountIdentitySnapshot:
    """Return only an exact inactive logical head matching all identity selectors."""

    def __init__(self, repository: AccountIdentitySnapshotRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentAccountIdentitySnapshotCommand,
    ) -> AccountIdentitySnapshot | None:
        """Reject superseded heads and every semantic selector substitution."""

        snapshot = GetExactAccountIdentitySnapshot(self._repository).execute(
            GetExactAccountIdentitySnapshotCommand(
                source_id=command.source_id,
                source_version=command.source_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if snapshot is None:
            return None
        if not (
            snapshot.owner == command.owner
            and snapshot.artifact_type == command.artifact_type
            and snapshot.schema == command.schema
            and snapshot.account_namespace == command.account_namespace
            and snapshot.account_id == command.account_id
            and snapshot.underlying_unified_account_namespace
            == command.underlying_unified_account_namespace
            and snapshot.underlying_unified_account_id == command.underlying_unified_account_id
            and snapshot.owner_user_id == command.owner_user_id
            and snapshot.provenance_kind == command.provenance_kind
            and snapshot.legacy_default_user_assignment == command.legacy_default_user_assignment
            and snapshot.underlying_source_id == command.underlying_source_id
            and snapshot.underlying_source_version == command.underlying_source_version
            and snapshot.underlying_source_content_hash == command.underlying_source_content_hash
            and snapshot.reclaim_receipt_owner == command.reclaim_receipt_owner
            and snapshot.reclaim_receipt_artifact_type == command.reclaim_receipt_artifact_type
            and snapshot.reclaim_receipt_id == command.reclaim_receipt_id
            and snapshot.reclaim_receipt_version == command.reclaim_receipt_version
            and snapshot.reclaim_receipt_content_hash == command.reclaim_receipt_content_hash
            and snapshot.account_type == command.account_type
            and snapshot.is_active == command.is_active
        ):
            raise AccountIdentitySnapshotCorruption(
                "account identity snapshot current selector substitution"
            )
        head = self._repository.get_current_head(
            account_namespace=snapshot.account_namespace,
            account_id=snapshot.account_id,
            as_of=command.as_of,
        )
        if head is None:
            return None
        checked = _RegisterAccountIdentitySnapshot._require_exact_record(head)
        return snapshot if checked.snapshot == snapshot else None


__all__ = [
    "AccountIdentitySnapshotActor",
    "AccountIdentitySnapshotConflict",
    "AccountIdentitySnapshotCorruption",
    "AccountIdentitySnapshotRepository",
    "AccountIdentitySnapshotUnavailable",
    "ExactCurrentManualAccountOwnerReclaimReceiptProvider",
    "ExactCurrentRawAccountIdentitySourceProvider",
    "GetCurrentAccountIdentitySnapshot",
    "GetCurrentAccountIdentitySnapshotCommand",
    "GetExactAccountIdentitySnapshot",
    "GetExactAccountIdentitySnapshotCommand",
    "IssueAccountIdentitySnapshot",
    "IssueAccountIdentitySnapshotCommand",
    "ManualAccountOwnerReclaimReceipt",
    "PersistedAccountIdentitySnapshot",
    "ReclaimLegacyAccountIdentitySnapshot",
    "ReclaimLegacyAccountIdentitySnapshotCommand",
    "TRUSTED_RAW_ACCOUNT_SOURCE_ARTIFACT_TYPE",
    "TRUSTED_RAW_ACCOUNT_SOURCE_OWNER",
    "TrustedRawAccountIdentitySource",
]
