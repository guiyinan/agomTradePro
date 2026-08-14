"""ID-only workflow for inactive Portfolio/Broker account namespace bindings."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.broker_execution.domain.portfolio_broker_account_binding import (
    ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    ACCOUNT_BINDING_SOURCE_OWNER,
    BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    BROKER_ACCOUNT_BINDING_SOURCE_OWNER,
    BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION,
    BrokerPortfolioAccountBindingActor,
    BrokerPortfolioAccountNamespaceBinding,
    validate_broker_portfolio_account_binding_successor,
)


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


class BrokerPortfolioAccountBindingUnavailable(ValueError):
    """An exact current owner source or inactive binding is unavailable."""


class BrokerPortfolioAccountBindingConflict(ValueError):
    """An immutable identity or logical head has another first winner."""


class BrokerPortfolioAccountBindingCorruption(ValueError):
    """A trusted source or persisted binding failed exact validation."""


@dataclass(frozen=True, slots=True)
class BrokerAccountNamespaceSourceDefinition:
    """Consumer-owned projection of one exact current Broker account source."""

    source_id: str
    source_version: str
    content_hash: str
    account_namespace: str
    account_id: int
    owner_user_id: int
    account_type: str
    is_active: bool
    recorded_at: datetime
    valid_until: datetime
    owner: str = BROKER_ACCOUNT_BINDING_SOURCE_OWNER
    artifact_type: str = BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("Broker source account_id must be a positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("Broker source owner_user_id must be a positive integer")
        if self.account_type != "real" or self.is_active is not True:
            raise ValueError("Broker source must be an active real account")
        if (
            self.owner != BROKER_ACCOUNT_BINDING_SOURCE_OWNER
            or self.artifact_type != BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("Broker source authority or artifact type is invalid")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("Broker source validity window is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the exact owner source is knowable and current."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class PortfolioAccountNamespaceSourceDefinition:
    """Consumer projection of one exact Account-owned Portfolio-namespace identity."""

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
    owner: str = ACCOUNT_BINDING_SOURCE_OWNER
    artifact_type: str = ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("Account source owner_user_id must be a positive integer")
        if self.account_type != "real" or self.is_active is not True:
            raise ValueError("Account source must be an active real account")
        if (
            self.owner != ACCOUNT_BINDING_SOURCE_OWNER
            or self.artifact_type != ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("Portfolio source authority or artifact type is invalid")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("Portfolio source validity window is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the exact owner source is knowable and current."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class RegisterBrokerPortfolioAccountBindingCommand:
    """ID-only selector; caller cannot submit accounts, seals, clocks, or authority."""

    binding_id: str
    broker_source_id: str
    broker_source_version: str
    portfolio_source_id: str
    portfolio_source_version: str
    binding_version: str = BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "broker_source_id",
            "broker_source_version",
            "portfolio_source_id",
            "portfolio_source_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if self.binding_version != BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION:
            raise ValueError("binding_version is fixed")


@dataclass(frozen=True, slots=True)
class GetExactBrokerPortfolioAccountBindingCommand:
    """Exact identity/hash/PIT selector for one inactive binding."""

    binding_id: str
    expected_content_hash: str
    as_of: datetime
    binding_version: str = BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION

    def __post_init__(self) -> None:
        _require_token(self.binding_id, "binding_id")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")
        if self.binding_version != BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION:
            raise ValueError("binding_version is fixed")


@dataclass(frozen=True, slots=True)
class GetCurrentBrokerPortfolioAccountBindingCommand:
    """Closed selector for the inactive logical head with both owner sources."""

    binding_id: str
    expected_content_hash: str
    broker_source_owner: str
    broker_source_artifact_type: str
    broker_source_id: str
    broker_source_version: str
    broker_source_content_hash: str
    broker_account_namespace: str
    broker_account_id: int
    owner_user_id: int
    account_type: str
    source_accounts_active: bool
    portfolio_source_owner: str
    portfolio_source_artifact_type: str
    portfolio_source_id: str
    portfolio_source_version: str
    portfolio_source_content_hash: str
    portfolio_account_namespace: str
    portfolio_account_id: str
    as_of: datetime
    binding_version: str = BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "broker_source_owner",
            "broker_source_artifact_type",
            "broker_source_id",
            "broker_source_version",
            "broker_account_namespace",
            "portfolio_source_owner",
            "portfolio_source_artifact_type",
            "portfolio_source_id",
            "portfolio_source_version",
            "portfolio_account_namespace",
            "portfolio_account_id",
            "account_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "expected_content_hash",
            "broker_source_content_hash",
            "portfolio_source_content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise ValueError("broker_account_id must be a positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if self.account_type != "real" or self.source_accounts_active is not True:
            raise ValueError("current selector requires active real source accounts")
        _require_aware(self.as_of, "as_of")
        if self.binding_version != BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION:
            raise ValueError("binding_version is fixed")


class ExactCurrentBrokerAccountNamespaceSourceProvider(Protocol):
    """Broker owner public port projected for this consumer."""

    def get_exact_current(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> BrokerAccountNamespaceSourceDefinition | None:
        """Return one exact current Broker account source."""


class ExactCurrentPortfolioAccountNamespaceSourceProvider(Protocol):
    """Account owner port for an identity consumed by the Portfolio namespace."""

    def get_exact_current(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PortfolioAccountNamespaceSourceDefinition | None:
        """Return one exact current Account-owned Portfolio-namespace source."""


class BrokerPortfolioAccountBindingRepository(Protocol):
    """Private first-winner store and exact inactive PIT read authority."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Broker server clock."""

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return the immutable identity winner."""

    def get_current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return the logical head for one exact Broker namespace identity."""

    def append(
        self,
        binding: BrokerPortfolioAccountNamespaceBinding,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding:
        """Append or return one first winner using predecessor CAS."""

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return one exact inactive binding knowable at the cutoff."""


class RegisterBrokerPortfolioAccountBinding:
    """Seal one inactive assertion from two exact-current owner sources."""

    def __init__(
        self,
        *,
        broker_source_provider: ExactCurrentBrokerAccountNamespaceSourceProvider,
        portfolio_source_provider: ExactCurrentPortfolioAccountNamespaceSourceProvider,
        repository: BrokerPortfolioAccountBindingRepository,
        actor: BrokerPortfolioAccountBindingActor,
    ) -> None:
        BrokerPortfolioAccountBindingActor.__post_init__(actor)
        self._broker_source_provider = broker_source_provider
        self._portfolio_source_provider = portfolio_source_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: RegisterBrokerPortfolioAccountBindingCommand
    ) -> BrokerPortfolioAccountNamespaceBinding:
        """Double-read both sources and CAS-append one inactive first winner."""

        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Broker server clock")
            first = self._read_sources(command, recorded_at)
            broker_source, portfolio_source = first
            winner = self._repository.get_binding_winner(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                broker_account_namespace=broker_source.account_namespace,
                broker_account_id=broker_source.account_id,
                as_of=recorded_at,
            )
            final = self._read_sources(command, recorded_at)
            if first != final:
                raise BrokerPortfolioAccountBindingCorruption(
                    "account namespace owner sources changed during registration"
                )
            broker_source, portfolio_source = final
            if broker_source.owner_user_id != portfolio_source.owner_user_id:
                raise BrokerPortfolioAccountBindingCorruption(
                    "account namespace sources have different owner identities"
                )
            if winner is not None:
                self._validate_winner(
                    winner,
                    command,
                    broker_source,
                    portfolio_source,
                    head,
                    recorded_at,
                )
                return winner
            candidate = self._build_binding(
                command,
                broker_source,
                portfolio_source,
                actor=self._actor,
                issued_at=recorded_at,
                recorded_at=recorded_at,
                supersedes_binding_hash=head.content_hash if head else None,
            )
            if head is not None:
                try:
                    validate_broker_portfolio_account_binding_successor(head, candidate)
                except (TypeError, ValueError) as error:
                    raise BrokerPortfolioAccountBindingCorruption(
                        "account namespace binding successor is invalid"
                    ) from error
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=head.content_hash if head else None,
                recorded_at=recorded_at,
            )
            self._require_exact_binding(persisted)
            if persisted != candidate:
                raise BrokerPortfolioAccountBindingConflict(
                    "concurrent account namespace binding first winner differs"
                )
            return persisted

    def _read_sources(
        self,
        command: RegisterBrokerPortfolioAccountBindingCommand,
        as_of: datetime,
    ) -> tuple[
        BrokerAccountNamespaceSourceDefinition,
        PortfolioAccountNamespaceSourceDefinition,
    ]:
        broker_source = self._broker_source_provider.get_exact_current(
            source_id=command.broker_source_id,
            source_version=command.broker_source_version,
            as_of=as_of,
        )
        portfolio_source = self._portfolio_source_provider.get_exact_current(
            source_id=command.portfolio_source_id,
            source_version=command.portfolio_source_version,
            as_of=as_of,
        )
        return (
            self._require_broker_source(broker_source, command, as_of),
            self._require_portfolio_source(portfolio_source, command, as_of),
        )

    @staticmethod
    def _require_broker_source(
        value: BrokerAccountNamespaceSourceDefinition | None,
        command: RegisterBrokerPortfolioAccountBindingCommand,
        as_of: datetime,
    ) -> BrokerAccountNamespaceSourceDefinition:
        if value is None:
            raise BrokerPortfolioAccountBindingUnavailable(
                "exact current Broker account source is unavailable"
            )
        if type(value) is not BrokerAccountNamespaceSourceDefinition:
            raise BrokerPortfolioAccountBindingCorruption("Broker account source type substitution")
        BrokerAccountNamespaceSourceDefinition.__post_init__(value)
        if (
            value.source_id != command.broker_source_id
            or value.source_version != command.broker_source_version
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "Broker account source identity substitution"
            )
        if not value.is_current_at(as_of):
            raise BrokerPortfolioAccountBindingUnavailable(
                "exact current Broker account source is unavailable"
            )
        return value

    @staticmethod
    def _require_portfolio_source(
        value: PortfolioAccountNamespaceSourceDefinition | None,
        command: RegisterBrokerPortfolioAccountBindingCommand,
        as_of: datetime,
    ) -> PortfolioAccountNamespaceSourceDefinition:
        if value is None:
            raise BrokerPortfolioAccountBindingUnavailable(
                "exact current Account-owned Portfolio namespace source is unavailable"
            )
        if type(value) is not PortfolioAccountNamespaceSourceDefinition:
            raise BrokerPortfolioAccountBindingCorruption(
                "Account-owned Portfolio namespace source type substitution"
            )
        PortfolioAccountNamespaceSourceDefinition.__post_init__(value)
        if (
            value.source_id != command.portfolio_source_id
            or value.source_version != command.portfolio_source_version
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "Account-owned Portfolio namespace source identity substitution"
            )
        if not value.is_current_at(as_of):
            raise BrokerPortfolioAccountBindingUnavailable(
                "exact current Account-owned Portfolio namespace source is unavailable"
            )
        return value

    @staticmethod
    def _build_binding(
        command: RegisterBrokerPortfolioAccountBindingCommand,
        broker_source: BrokerAccountNamespaceSourceDefinition,
        portfolio_source: PortfolioAccountNamespaceSourceDefinition,
        *,
        actor: BrokerPortfolioAccountBindingActor,
        issued_at: datetime,
        recorded_at: datetime,
        supersedes_binding_hash: str | None,
    ) -> BrokerPortfolioAccountNamespaceBinding:
        return BrokerPortfolioAccountNamespaceBinding(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            broker_account_namespace=broker_source.account_namespace,
            broker_account_id=broker_source.account_id,
            portfolio_account_namespace=portfolio_source.account_namespace,
            portfolio_account_id=portfolio_source.account_id,
            owner_user_id=broker_source.owner_user_id,
            broker_source_owner=broker_source.owner,
            broker_source_artifact_type=broker_source.artifact_type,
            broker_source_id=broker_source.source_id,
            broker_source_version=broker_source.source_version,
            broker_source_content_hash=broker_source.content_hash,
            portfolio_source_owner=portfolio_source.owner,
            portfolio_source_artifact_type=portfolio_source.artifact_type,
            portfolio_source_id=portfolio_source.source_id,
            portfolio_source_version=portfolio_source.source_version,
            portfolio_source_content_hash=portfolio_source.content_hash,
            asserted_by=actor,
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=min(broker_source.valid_until, portfolio_source.valid_until),
            supersedes_binding_hash=supersedes_binding_hash,
            account_type="real",
            source_accounts_active=True,
        )

    def _validate_winner(
        self,
        winner: BrokerPortfolioAccountNamespaceBinding,
        command: RegisterBrokerPortfolioAccountBindingCommand,
        broker_source: BrokerAccountNamespaceSourceDefinition,
        portfolio_source: PortfolioAccountNamespaceSourceDefinition,
        head: BrokerPortfolioAccountNamespaceBinding | None,
        as_of: datetime,
    ) -> None:
        value = self._require_exact_binding(winner)
        if not value.is_knowable_at(as_of):
            raise BrokerPortfolioAccountBindingUnavailable(
                "persisted account namespace binding is unavailable"
            )
        if value.asserted_by != self._actor:
            raise BrokerPortfolioAccountBindingConflict(
                "account namespace binding identity belongs to another actor"
            )
        stable = self._build_binding(
            command,
            broker_source,
            portfolio_source,
            actor=value.asserted_by,
            issued_at=value.issued_at,
            recorded_at=value.recorded_at,
            supersedes_binding_hash=value.supersedes_binding_hash,
        )
        if stable != value:
            raise BrokerPortfolioAccountBindingConflict(
                "account namespace binding identity has another first winner"
            )
        if head is None or self._require_exact_binding(head) != value:
            raise BrokerPortfolioAccountBindingConflict(
                "account namespace binding is no longer the logical current head"
            )

    @staticmethod
    def _require_exact_binding(
        value: object,
    ) -> BrokerPortfolioAccountNamespaceBinding:
        if type(value) is not BrokerPortfolioAccountNamespaceBinding:
            raise BrokerPortfolioAccountBindingCorruption(
                "account namespace binding type substitution"
            )
        BrokerPortfolioAccountNamespaceBinding.__post_init__(value)
        return value


class GetExactBrokerPortfolioAccountBinding:
    """Expose exact inactive identity/hash/PIT reads."""

    def __init__(self, repository: BrokerPortfolioAccountBindingRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactBrokerPortfolioAccountBindingCommand
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return only the exact knowable inactive binding."""

        value = self._repository.get_exact_by_hash(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = RegisterBrokerPortfolioAccountBinding._require_exact_binding(value)
        if (
            checked.binding_id != command.binding_id
            or checked.binding_version != command.binding_version
            or checked.content_hash != command.expected_content_hash
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "account namespace binding exact identity substitution"
            )
        if not checked.is_knowable_at(command.as_of):
            return None
        if (
            checked.activation_available
            or not checked.must_not_execute
            or checked.permission != "inactive"
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "account namespace binding execution state substitution"
            )
        return checked


class GetCurrentBrokerPortfolioAccountBinding:
    """Return only the exact inactive logical head matching both owner sources."""

    def __init__(self, repository: BrokerPortfolioAccountBindingRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetCurrentBrokerPortfolioAccountBindingCommand
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Reject historical heads and every owner-source selector substitution."""

        value = GetExactBrokerPortfolioAccountBinding(self._repository).execute(
            GetExactBrokerPortfolioAccountBindingCommand(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if value is None:
            return None
        if not (
            value.broker_source_owner == command.broker_source_owner
            and value.broker_source_artifact_type == command.broker_source_artifact_type
            and value.broker_source_id == command.broker_source_id
            and value.broker_source_version == command.broker_source_version
            and value.broker_source_content_hash == command.broker_source_content_hash
            and value.broker_account_namespace == command.broker_account_namespace
            and value.broker_account_id == command.broker_account_id
            and value.owner_user_id == command.owner_user_id
            and value.account_type == command.account_type
            and value.source_accounts_active == command.source_accounts_active
            and value.portfolio_source_owner == command.portfolio_source_owner
            and value.portfolio_source_artifact_type == command.portfolio_source_artifact_type
            and value.portfolio_source_id == command.portfolio_source_id
            and value.portfolio_source_version == command.portfolio_source_version
            and value.portfolio_source_content_hash == command.portfolio_source_content_hash
            and value.portfolio_account_namespace == command.portfolio_account_namespace
            and value.portfolio_account_id == command.portfolio_account_id
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "account namespace binding current selector substitution"
            )
        head = self._repository.get_current_head(
            broker_account_namespace=value.broker_account_namespace,
            broker_account_id=value.broker_account_id,
            as_of=command.as_of,
        )
        if head is None:
            return None
        checked_head = RegisterBrokerPortfolioAccountBinding._require_exact_binding(head)
        return value if checked_head == value else None


__all__ = [
    "BrokerAccountNamespaceSourceDefinition",
    "BrokerPortfolioAccountBindingConflict",
    "BrokerPortfolioAccountBindingCorruption",
    "BrokerPortfolioAccountBindingRepository",
    "BrokerPortfolioAccountBindingUnavailable",
    "ExactCurrentBrokerAccountNamespaceSourceProvider",
    "ExactCurrentPortfolioAccountNamespaceSourceProvider",
    "GetCurrentBrokerPortfolioAccountBinding",
    "GetCurrentBrokerPortfolioAccountBindingCommand",
    "GetExactBrokerPortfolioAccountBinding",
    "GetExactBrokerPortfolioAccountBindingCommand",
    "PortfolioAccountNamespaceSourceDefinition",
    "RegisterBrokerPortfolioAccountBinding",
    "RegisterBrokerPortfolioAccountBindingCommand",
]
