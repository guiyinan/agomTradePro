"""ID-only workflow for immutable inactive Broker pre-Risk scopes."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.broker_execution.domain.pre_risk_execution_scope import (
    BROKER_PRE_RISK_SCOPE_VERSION,
    BrokerPreRiskExecutionScope,
    validate_pre_risk_scope_successor,
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


class BrokerPreRiskScopeUnavailable(ValueError):
    """An exact inactive owner source or candidate is unavailable."""


class BrokerPreRiskScopeConflict(ValueError):
    """An immutable identity or logical current head has another winner."""


class BrokerPreRiskScopeCorruption(ValueError):
    """A trusted source or persisted candidate failed exact validation."""


@dataclass(frozen=True, slots=True)
class PortfolioTransitionPlanDefinition:
    """Broker-owned projection of one exact active Portfolio plan."""

    plan_id: str
    plan_version: int
    content_hash: str
    account_id: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _require_token(self.plan_id, "plan_id")
        _require_token(self.account_id, "account_id")
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("Portfolio plan validity window is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the trusted plan is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class PortfolioInactiveApprovalReceiptDefinition:
    """Broker-owned projection of one exact inactive Portfolio receipt."""

    receipt_id: str
    receipt_version: str
    content_hash: str
    subject_id: str
    subject_version: str
    subject_content_hash: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    account_id: str
    recorded_at: datetime
    issued_at: datetime
    valid_until: datetime
    execution_permission: str = "inactive"
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "receipt_version",
            "subject_id",
            "subject_version",
            "plan_id",
            "account_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        for field_name in ("content_hash", "subject_content_hash", "plan_content_hash"):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in ("recorded_at", "issued_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("Portfolio receipt clock sequence is invalid")
        if self.execution_permission != "inactive" or self.must_not_execute is not True:
            raise ValueError("Portfolio receipt must remain explicitly inactive")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the inactive receipt is exactly knowable at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class BrokerOrderApprovalArtifactDefinition:
    """Application projection of one exact inactive Broker approval artifact."""

    artifact_id: str
    artifact_version: str
    content_hash: str
    identity_hash: str
    account_id: int
    order_version: int
    approval_digest: str
    risk_policy_version: str
    recorded_at: datetime
    approved_at: datetime
    valid_until: datetime
    activation_available: bool = False
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_token(self.artifact_id, "artifact_id")
        _require_token(self.artifact_version, "artifact_version")
        _require_token(self.risk_policy_version, "risk_policy_version")
        for field_name in ("content_hash", "identity_hash", "approval_digest"):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if type(self.order_version) is not int or self.order_version <= 0:
            raise ValueError("order_version must be a positive integer")
        for field_name in ("recorded_at", "approved_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.approved_at <= self.recorded_at < self.valid_until:
            raise ValueError("Broker order artifact clock sequence is invalid")
        if self.activation_available is not False or self.must_not_execute is not True:
            raise ValueError("Broker order approval artifact must remain inactive")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the inactive artifact is exactly knowable at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class RegisterBrokerPreRiskExecutionScopeCommand:
    """ID-only registration selector; no caller-owned hashes or permission."""

    scope_id: str
    plan_id: str
    plan_version: int
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    order_artifact_id: str
    order_artifact_version: str
    scope_version: str = BROKER_PRE_RISK_SCOPE_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "scope_id",
            "plan_id",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
            "order_artifact_id",
            "order_artifact_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        if self.scope_version != BROKER_PRE_RISK_SCOPE_VERSION:
            raise ValueError("scope_version is fixed")


@dataclass(frozen=True, slots=True)
class GetExactBrokerPreRiskExecutionScopeCommand:
    """Exact identity/hash/PIT selector for one inactive candidate."""

    scope_id: str
    expected_content_hash: str
    as_of: datetime
    scope_version: str = BROKER_PRE_RISK_SCOPE_VERSION

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "scope_id")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")
        if self.scope_version != BROKER_PRE_RISK_SCOPE_VERSION:
            raise ValueError("scope_version is fixed")


@dataclass(frozen=True, slots=True)
class GetCurrentBrokerPreRiskExecutionScopeCommand:
    """Closed selector for the inactive logical head of one Broker order."""

    scope_id: str
    expected_content_hash: str
    broker_account_id: int
    order_artifact_id: str
    order_artifact_version: str
    order_artifact_content_hash: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    portfolio_receipt_content_hash: str
    as_of: datetime
    scope_version: str = BROKER_PRE_RISK_SCOPE_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "scope_id",
            "order_artifact_id",
            "order_artifact_version",
            "plan_id",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "expected_content_hash",
            "order_artifact_content_hash",
            "plan_content_hash",
            "portfolio_receipt_content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise ValueError("broker_account_id must be a positive integer")
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        _require_aware(self.as_of, "as_of")
        if self.scope_version != BROKER_PRE_RISK_SCOPE_VERSION:
            raise ValueError("scope_version is fixed")


class ExactActivePortfolioTransitionPlanProvider(Protocol):
    """Portfolio Application public port projected for Broker consumption."""

    def get_exact_active(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> PortfolioTransitionPlanDefinition | None:
        """Return one exact active plan selected only by owner identity."""


class ExactInactivePortfolioApprovalReceiptProvider(Protocol):
    """Portfolio public port that cannot upgrade an inactive receipt."""

    def get_exact_inactive(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PortfolioInactiveApprovalReceiptDefinition | None:
        """Return one exact inactive receipt selected by owner identity."""


class ExactInactiveBrokerOrderApprovalArtifactProvider(Protocol):
    """Broker public port for the immutable approval artifact ledger."""

    def get_exact_inactive(
        self, *, artifact_id: str, artifact_version: str, as_of: datetime
    ) -> BrokerOrderApprovalArtifactDefinition | None:
        """Return one exact inactive order artifact selected by owner identity."""


class BrokerPreRiskExecutionScopeRepository(Protocol):
    """Private append-only candidate store and exact PIT read authority."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Broker server clock."""

    def get_scope_winner(
        self, *, scope_id: str, scope_version: str, as_of: datetime
    ) -> BrokerPreRiskExecutionScope | None:
        """Return one immutable scope identity winner."""

    def get_current_head(
        self, *, broker_account_id: int, order_artifact_id: str, as_of: datetime
    ) -> BrokerPreRiskExecutionScope | None:
        """Return the unique logical head for one account and order."""

    def append(
        self,
        scope: BrokerPreRiskExecutionScope,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPreRiskExecutionScope:
        """Append or return one exact first winner using predecessor CAS."""

    def get_exact_by_hash(
        self,
        *,
        scope_id: str,
        scope_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPreRiskExecutionScope | None:
        """Return one exact inactive scope knowable at the cutoff."""


class RegisterBrokerPreRiskExecutionScope:
    """Seal one inactive pre-Risk candidate from three trusted owner reads."""

    def __init__(
        self,
        *,
        plan_provider: ExactActivePortfolioTransitionPlanProvider,
        receipt_provider: ExactInactivePortfolioApprovalReceiptProvider,
        order_provider: ExactInactiveBrokerOrderApprovalArtifactProvider,
        repository: BrokerPreRiskExecutionScopeRepository,
    ) -> None:
        self._plan_provider = plan_provider
        self._receipt_provider = receipt_provider
        self._order_provider = order_provider
        self._repository = repository

    def execute(
        self, command: RegisterBrokerPreRiskExecutionScopeCommand
    ) -> BrokerPreRiskExecutionScope:
        """Double-read all owner sources and append one inactive first winner."""

        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Broker server clock")
            first = self._read_sources(command, recorded_at)
            plan, receipt, order = first
            winner = self._repository.get_scope_winner(
                scope_id=command.scope_id,
                scope_version=command.scope_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                broker_account_id=order.account_id,
                order_artifact_id=order.artifact_id,
                as_of=recorded_at,
            )
            final = self._read_sources(command, recorded_at)
            if first != final:
                raise BrokerPreRiskScopeCorruption(
                    "pre-Risk owner sources changed during registration"
                )
            if winner is not None:
                self._validate_winner(winner, command, final, head, recorded_at)
                return winner
            candidate = self._build_scope(
                command,
                plan,
                receipt,
                order,
                recorded_at=recorded_at,
                supersedes_scope_hash=head.content_hash if head else None,
            )
            if head is not None:
                try:
                    validate_pre_risk_scope_successor(head, candidate)
                except (TypeError, ValueError) as error:
                    raise BrokerPreRiskScopeCorruption(
                        "pre-Risk scope successor is invalid"
                    ) from error
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=head.content_hash if head else None,
                recorded_at=recorded_at,
            )
            self._require_exact_scope(persisted)
            if persisted != candidate:
                raise BrokerPreRiskScopeConflict("concurrent pre-Risk scope first winner differs")
            return persisted

    def _read_sources(
        self,
        command: RegisterBrokerPreRiskExecutionScopeCommand,
        as_of: datetime,
    ) -> tuple[
        PortfolioTransitionPlanDefinition,
        PortfolioInactiveApprovalReceiptDefinition,
        BrokerOrderApprovalArtifactDefinition,
    ]:
        plan = self._plan_provider.get_exact_active(
            plan_id=command.plan_id,
            plan_version=command.plan_version,
            as_of=as_of,
        )
        receipt = self._receipt_provider.get_exact_inactive(
            receipt_id=command.portfolio_receipt_id,
            receipt_version=command.portfolio_receipt_version,
            as_of=as_of,
        )
        order = self._order_provider.get_exact_inactive(
            artifact_id=command.order_artifact_id,
            artifact_version=command.order_artifact_version,
            as_of=as_of,
        )
        checked_plan = self._require_plan(plan, command, as_of)
        checked_receipt = self._require_receipt(receipt, command, as_of)
        checked_order = self._require_order(order, command, as_of)
        if (
            checked_receipt.plan_id != checked_plan.plan_id
            or checked_receipt.plan_version != checked_plan.plan_version
            or checked_receipt.plan_content_hash != checked_plan.content_hash
            or checked_receipt.account_id != checked_plan.account_id
        ):
            raise BrokerPreRiskScopeCorruption(
                "Portfolio receipt does not bind the exact plan definition"
            )
        return checked_plan, checked_receipt, checked_order

    @staticmethod
    def _require_plan(
        value: PortfolioTransitionPlanDefinition | None,
        command: RegisterBrokerPreRiskExecutionScopeCommand,
        as_of: datetime,
    ) -> PortfolioTransitionPlanDefinition:
        if value is None:
            raise BrokerPreRiskScopeUnavailable("exact active Portfolio plan is unavailable")
        if type(value) is not PortfolioTransitionPlanDefinition:
            raise BrokerPreRiskScopeCorruption("Portfolio plan type substitution")
        PortfolioTransitionPlanDefinition.__post_init__(value)
        if value.plan_id != command.plan_id or value.plan_version != command.plan_version:
            raise BrokerPreRiskScopeCorruption("Portfolio plan identity substitution")
        if not value.is_active_at(as_of):
            raise BrokerPreRiskScopeUnavailable("exact active Portfolio plan is unavailable")
        return value

    @staticmethod
    def _require_receipt(
        value: PortfolioInactiveApprovalReceiptDefinition | None,
        command: RegisterBrokerPreRiskExecutionScopeCommand,
        as_of: datetime,
    ) -> PortfolioInactiveApprovalReceiptDefinition:
        if value is None:
            raise BrokerPreRiskScopeUnavailable("exact inactive Portfolio receipt is unavailable")
        if type(value) is not PortfolioInactiveApprovalReceiptDefinition:
            raise BrokerPreRiskScopeCorruption("Portfolio receipt type substitution")
        PortfolioInactiveApprovalReceiptDefinition.__post_init__(value)
        if (
            value.receipt_id != command.portfolio_receipt_id
            or value.receipt_version != command.portfolio_receipt_version
        ):
            raise BrokerPreRiskScopeCorruption("Portfolio receipt identity substitution")
        if not value.is_knowable_at(as_of):
            raise BrokerPreRiskScopeUnavailable("exact inactive Portfolio receipt is unavailable")
        return value

    @staticmethod
    def _require_order(
        value: BrokerOrderApprovalArtifactDefinition | None,
        command: RegisterBrokerPreRiskExecutionScopeCommand,
        as_of: datetime,
    ) -> BrokerOrderApprovalArtifactDefinition:
        if value is None:
            raise BrokerPreRiskScopeUnavailable(
                "exact inactive Broker order artifact is unavailable"
            )
        if type(value) is not BrokerOrderApprovalArtifactDefinition:
            raise BrokerPreRiskScopeCorruption("Broker order artifact type substitution")
        BrokerOrderApprovalArtifactDefinition.__post_init__(value)
        if (
            value.artifact_id != command.order_artifact_id
            or value.artifact_version != command.order_artifact_version
        ):
            raise BrokerPreRiskScopeCorruption("Broker order artifact identity substitution")
        if not value.is_knowable_at(as_of):
            raise BrokerPreRiskScopeUnavailable(
                "exact inactive Broker order artifact is unavailable"
            )
        return value

    @staticmethod
    def _build_scope(
        command: RegisterBrokerPreRiskExecutionScopeCommand,
        plan: PortfolioTransitionPlanDefinition,
        receipt: PortfolioInactiveApprovalReceiptDefinition,
        order: BrokerOrderApprovalArtifactDefinition,
        *,
        recorded_at: datetime,
        supersedes_scope_hash: str | None,
    ) -> BrokerPreRiskExecutionScope:
        return BrokerPreRiskExecutionScope(
            scope_id=command.scope_id,
            scope_version=command.scope_version,
            broker_account_id=order.account_id,
            portfolio_account_id=plan.account_id,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            plan_content_hash=plan.content_hash,
            plan_valid_until=plan.valid_until,
            portfolio_receipt_id=receipt.receipt_id,
            portfolio_receipt_version=receipt.receipt_version,
            portfolio_receipt_content_hash=receipt.content_hash,
            portfolio_subject_id=receipt.subject_id,
            portfolio_subject_version=receipt.subject_version,
            portfolio_subject_content_hash=receipt.subject_content_hash,
            portfolio_receipt_valid_until=receipt.valid_until,
            order_artifact_id=order.artifact_id,
            order_artifact_version=order.artifact_version,
            order_artifact_content_hash=order.content_hash,
            order_artifact_identity_hash=order.identity_hash,
            order_version=order.order_version,
            order_approval_digest=order.approval_digest,
            order_valid_until=order.valid_until,
            order_risk_policy_version=order.risk_policy_version,
            recorded_at=recorded_at,
            valid_until=min(plan.valid_until, receipt.valid_until, order.valid_until),
            supersedes_scope_hash=supersedes_scope_hash,
        )

    def _validate_winner(
        self,
        winner: BrokerPreRiskExecutionScope,
        command: RegisterBrokerPreRiskExecutionScopeCommand,
        sources: tuple[
            PortfolioTransitionPlanDefinition,
            PortfolioInactiveApprovalReceiptDefinition,
            BrokerOrderApprovalArtifactDefinition,
        ],
        head: BrokerPreRiskExecutionScope | None,
        as_of: datetime,
    ) -> None:
        value = self._require_exact_scope(winner)
        plan, receipt, order = sources
        if not value.is_knowable_at(as_of):
            raise BrokerPreRiskScopeUnavailable("persisted pre-Risk scope is unavailable")
        stable = self._build_scope(
            command,
            plan,
            receipt,
            order,
            recorded_at=value.recorded_at,
            supersedes_scope_hash=value.supersedes_scope_hash,
        )
        if stable != value:
            raise BrokerPreRiskScopeConflict("pre-Risk scope identity has another first winner")
        if head is None or self._require_exact_scope(head) != value:
            raise BrokerPreRiskScopeConflict(
                "pre-Risk scope identity is no longer the logical current head"
            )

    @staticmethod
    def _require_exact_scope(value: object) -> BrokerPreRiskExecutionScope:
        if type(value) is not BrokerPreRiskExecutionScope:
            raise BrokerPreRiskScopeCorruption("pre-Risk scope type substitution")
        BrokerPreRiskExecutionScope.__post_init__(value)
        return value


class GetExactBrokerPreRiskExecutionScope:
    """Expose exact inactive identity/hash/PIT reads."""

    def __init__(self, repository: BrokerPreRiskExecutionScopeRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactBrokerPreRiskExecutionScopeCommand
    ) -> BrokerPreRiskExecutionScope | None:
        """Return only the exact knowable inactive candidate."""

        value = self._repository.get_exact_by_hash(
            scope_id=command.scope_id,
            scope_version=command.scope_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = RegisterBrokerPreRiskExecutionScope._require_exact_scope(value)
        if (
            checked.scope_id != command.scope_id
            or checked.scope_version != command.scope_version
            or checked.content_hash != command.expected_content_hash
        ):
            raise BrokerPreRiskScopeCorruption("pre-Risk exact identity substitution")
        if not checked.is_knowable_at(command.as_of):
            return None
        if (
            checked.activation_available
            or not checked.must_not_execute
            or checked.permission != "inactive"
        ):
            raise BrokerPreRiskScopeCorruption("pre-Risk execution state substitution")
        return checked


class GetCurrentBrokerPreRiskExecutionScope:
    """Return only the exact inactive logical head matching a closed selector."""

    def __init__(self, repository: BrokerPreRiskExecutionScopeRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetCurrentBrokerPreRiskExecutionScopeCommand
    ) -> BrokerPreRiskExecutionScope | None:
        """Reject historical heads and every plan/order/receipt substitution."""

        value = GetExactBrokerPreRiskExecutionScope(self._repository).execute(
            GetExactBrokerPreRiskExecutionScopeCommand(
                scope_id=command.scope_id,
                scope_version=command.scope_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if value is None:
            return None
        if not (
            value.broker_account_id == command.broker_account_id
            and value.order_artifact_id == command.order_artifact_id
            and value.order_artifact_version == command.order_artifact_version
            and value.order_artifact_content_hash == command.order_artifact_content_hash
            and value.plan_id == command.plan_id
            and value.plan_version == command.plan_version
            and value.plan_content_hash == command.plan_content_hash
            and value.portfolio_receipt_id == command.portfolio_receipt_id
            and value.portfolio_receipt_version == command.portfolio_receipt_version
            and value.portfolio_receipt_content_hash == command.portfolio_receipt_content_hash
        ):
            raise BrokerPreRiskScopeCorruption("pre-Risk current selector substitution")
        head = self._repository.get_current_head(
            broker_account_id=value.broker_account_id,
            order_artifact_id=value.order_artifact_id,
            as_of=command.as_of,
        )
        if head is None:
            return None
        checked_head = RegisterBrokerPreRiskExecutionScope._require_exact_scope(head)
        return value if checked_head == value else None


__all__ = [
    "BrokerOrderApprovalArtifactDefinition",
    "BrokerPreRiskExecutionScopeRepository",
    "BrokerPreRiskScopeConflict",
    "BrokerPreRiskScopeCorruption",
    "BrokerPreRiskScopeUnavailable",
    "ExactActivePortfolioTransitionPlanProvider",
    "ExactInactiveBrokerOrderApprovalArtifactProvider",
    "ExactInactivePortfolioApprovalReceiptProvider",
    "GetCurrentBrokerPreRiskExecutionScope",
    "GetCurrentBrokerPreRiskExecutionScopeCommand",
    "GetExactBrokerPreRiskExecutionScope",
    "GetExactBrokerPreRiskExecutionScopeCommand",
    "PortfolioInactiveApprovalReceiptDefinition",
    "PortfolioTransitionPlanDefinition",
    "RegisterBrokerPreRiskExecutionScope",
    "RegisterBrokerPreRiskExecutionScopeCommand",
]
