"""ID-only workflow for immutable inactive Broker Plan-to-Order bindings."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.broker_execution.domain.plan_order_binding import (
    BROKER_ORDER_ARTIFACT_SOURCE_OWNER,
    BROKER_ORDER_ARTIFACT_SOURCE_TYPE,
    BROKER_PLAN_ORDER_BINDING_SCHEMA,
    PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE,
    PORTFOLIO_PLAN_SOURCE_OWNER,
    PORTFOLIO_RECEIPT_SOURCE_CAPABILITY,
    PORTFOLIO_RECEIPT_SOURCE_OWNER,
    BrokerPlanOrderBinding,
    canonical_plan_order_payload_hash_v1,
    validate_plan_order_binding_successor,
)

_PORTFOLIO_RECEIPT_SCHEMA = "portfolio-transition-plan-approval-receipt.v1"
_BROKER_ORDER_ARTIFACT_SCHEMA = "broker-live-order-approval-artifact.v1"


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_non_negative_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class BrokerPlanOrderBindingUnavailable(ValueError):
    """An exact active source or binding is unavailable at the cutoff."""


class BrokerPlanOrderBindingConflict(ValueError):
    """An immutable identity or logical-current subject has another winner."""


class BrokerPlanOrderBindingCorruption(ValueError):
    """A trusted source or persisted binding failed exact validation."""


@dataclass(frozen=True, slots=True)
class ExactPortfolioPlanOrderDefinition:
    """Broker consumer projection of one owner-derived canonical-v1 plan row."""

    plan_id: str
    plan_version: int
    content_hash: str
    account_id: str
    order_ordinal: int
    order_payload_json: str
    order_content_hash: str
    recorded_at: datetime
    valid_until: datetime
    owner: str = PORTFOLIO_PLAN_SOURCE_OWNER
    artifact_type: str = PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        _require_token(self.plan_id, "plan_id")
        _require_positive_integer(self.plan_version, "plan_version")
        _require_hash(self.content_hash, "content_hash")
        _require_token(self.account_id, "account_id")
        _require_non_negative_integer(self.order_ordinal, "order_ordinal")
        expected_row_hash = canonical_plan_order_payload_hash_v1(self.order_payload_json)
        _require_hash(self.order_content_hash, "order_content_hash")
        if self.order_content_hash != expected_row_hash:
            raise ValueError("order_content_hash does not match canonical-v1 row bytes")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("Portfolio plan validity window is invalid")
        if self.owner != PORTFOLIO_PLAN_SOURCE_OWNER:
            raise ValueError("Portfolio plan owner is fixed")
        if self.artifact_type != PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE:
            raise ValueError("Portfolio plan artifact_type is fixed")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact plan row is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class ExactPortfolioInactiveReceiptDefinition:
    """Broker consumer projection of one exact inactive Portfolio receipt."""

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
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = PORTFOLIO_RECEIPT_SOURCE_OWNER
    capability: str = PORTFOLIO_RECEIPT_SOURCE_CAPABILITY
    schema: str = _PORTFOLIO_RECEIPT_SCHEMA
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
        _require_positive_integer(self.plan_version, "plan_version")
        for field_name in ("content_hash", "subject_content_hash", "plan_content_hash"):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in ("issued_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("Portfolio receipt clock sequence is invalid")
        if self.owner != PORTFOLIO_RECEIPT_SOURCE_OWNER:
            raise ValueError("Portfolio receipt owner is fixed")
        if self.capability != PORTFOLIO_RECEIPT_SOURCE_CAPABILITY:
            raise ValueError("Portfolio receipt capability is fixed")
        if self.schema != _PORTFOLIO_RECEIPT_SCHEMA:
            raise ValueError("Portfolio receipt schema is fixed")
        if self.execution_permission != "inactive" or self.must_not_execute is not True:
            raise ValueError("Portfolio receipt must remain explicitly inactive")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact inactive receipt is knowable at the cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class ExactBrokerOrderArtifactDefinition:
    """Application projection of one exact inactive Broker approval artifact."""

    artifact_id: str
    artifact_version: str
    identity_hash: str
    content_hash: str
    account_id: int
    order_version: int
    approval_digest: str
    approved_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = BROKER_ORDER_ARTIFACT_SOURCE_OWNER
    artifact_type: str = BROKER_ORDER_ARTIFACT_SOURCE_TYPE
    schema: str = _BROKER_ORDER_ARTIFACT_SCHEMA
    activation_available: bool = False
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        try:
            canonical_id = str(UUID(self.artifact_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("artifact_id must be a canonical UUID") from error
        if canonical_id != self.artifact_id:
            raise ValueError("artifact_id must be a canonical UUID")
        _require_positive_integer(self.account_id, "account_id")
        _require_positive_integer(self.order_version, "order_version")
        expected_version = f"{_BROKER_ORDER_ARTIFACT_SCHEMA}.{self.order_version}"
        if self.artifact_version != expected_version:
            raise ValueError("artifact_version must bind the exact order_version")
        for field_name in ("identity_hash", "content_hash", "approval_digest"):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in ("approved_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.approved_at <= self.recorded_at < self.valid_until:
            raise ValueError("Broker order artifact clock sequence is invalid")
        if self.owner != BROKER_ORDER_ARTIFACT_SOURCE_OWNER:
            raise ValueError("Broker order artifact owner is fixed")
        if self.artifact_type != BROKER_ORDER_ARTIFACT_SOURCE_TYPE:
            raise ValueError("Broker order artifact artifact_type is fixed")
        if self.schema != _BROKER_ORDER_ARTIFACT_SCHEMA:
            raise ValueError("Broker order artifact schema is fixed")
        if self.activation_available is not False or self.must_not_execute is not True:
            raise ValueError("Broker order artifact must remain explicitly inactive")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact inactive artifact is knowable at the cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class RegisterBrokerPlanOrderBindingCommand:
    """ID-only selector; caller cannot supply hashes, accounts, clocks, or permission."""

    binding_id: str
    plan_id: str
    plan_version: int
    plan_order_ordinal: int
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    order_artifact_id: str
    order_artifact_version: str
    binding_version: str = BROKER_PLAN_ORDER_BINDING_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "plan_id",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
            "order_artifact_id",
            "order_artifact_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_positive_integer(self.plan_version, "plan_version")
        _require_non_negative_integer(self.plan_order_ordinal, "plan_order_ordinal")
        if self.binding_version != BROKER_PLAN_ORDER_BINDING_SCHEMA:
            raise ValueError("binding_version is fixed")


@dataclass(frozen=True, slots=True)
class GetExactBrokerPlanOrderBindingCommand:
    """Exact identity/hash/PIT selector for one inactive binding."""

    binding_id: str
    expected_content_hash: str
    as_of: datetime
    binding_version: str = BROKER_PLAN_ORDER_BINDING_SCHEMA

    def __post_init__(self) -> None:
        _require_token(self.binding_id, "binding_id")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")
        if self.binding_version != BROKER_PLAN_ORDER_BINDING_SCHEMA:
            raise ValueError("binding_version is fixed")


@dataclass(frozen=True, slots=True)
class GetCurrentBrokerPlanOrderBindingCommand:
    """Closed selector for one exact inactive logical-current binding."""

    binding_id: str
    expected_content_hash: str
    portfolio_plan_id: str
    portfolio_plan_version: int
    portfolio_plan_content_hash: str
    portfolio_account_id: str
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    portfolio_receipt_content_hash: str
    portfolio_subject_id: str
    portfolio_subject_version: str
    portfolio_subject_content_hash: str
    plan_order_ordinal: int
    plan_order_content_hash: str
    broker_account_id: int
    order_artifact_id: str
    order_artifact_version: str
    order_artifact_identity_hash: str
    order_artifact_content_hash: str
    order_approval_digest: str
    order_version: int
    as_of: datetime
    binding_version: str = BROKER_PLAN_ORDER_BINDING_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "portfolio_plan_id",
            "portfolio_account_id",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
            "portfolio_subject_id",
            "portfolio_subject_version",
            "order_artifact_id",
            "order_artifact_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "expected_content_hash",
            "portfolio_plan_content_hash",
            "portfolio_receipt_content_hash",
            "portfolio_subject_content_hash",
            "plan_order_content_hash",
            "order_artifact_identity_hash",
            "order_artifact_content_hash",
            "order_approval_digest",
        ):
            _require_hash(getattr(self, field_name), field_name)
        _require_positive_integer(self.portfolio_plan_version, "portfolio_plan_version")
        _require_non_negative_integer(self.plan_order_ordinal, "plan_order_ordinal")
        _require_positive_integer(self.broker_account_id, "broker_account_id")
        _require_positive_integer(self.order_version, "order_version")
        _require_aware(self.as_of, "as_of")
        if self.binding_version != BROKER_PLAN_ORDER_BINDING_SCHEMA:
            raise ValueError("binding_version is fixed")


class ExactPortfolioPlanOrderProvider(Protocol):
    """Trusted Portfolio public-reader adapter projected for Broker."""

    def get_exact_active(
        self,
        *,
        plan_id: str,
        plan_version: int,
        order_ordinal: int,
        as_of: datetime,
    ) -> ExactPortfolioPlanOrderDefinition | None:
        """Return one owner-derived exact active canonical-v1 row."""


class ExactPortfolioInactiveReceiptProvider(Protocol):
    """Trusted Portfolio public-reader adapter that cannot upgrade permission."""

    def get_exact_inactive(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> ExactPortfolioInactiveReceiptDefinition | None:
        """Return one exact inactive receipt selected only by owner identity."""


class ExactBrokerOrderArtifactProvider(Protocol):
    """Trusted Broker public-reader adapter for its immutable artifact ledger."""

    def get_exact_inactive(
        self, *, artifact_id: str, artifact_version: str, as_of: datetime
    ) -> ExactBrokerOrderArtifactDefinition | None:
        """Return one exact inactive artifact selected only by owner identity."""


class BrokerPlanOrderBindingRepository(Protocol):
    """Private append-only binding store and exact PIT/current read port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one private first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Broker server clock."""

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> BrokerPlanOrderBinding | None:
        """Return one immutable binding identity winner."""

    def get_current_head(
        self,
        *,
        plan_id: str,
        plan_version: int,
        plan_order_ordinal: int,
        order_artifact_id: str,
        as_of: datetime,
    ) -> BrokerPlanOrderBinding | None:
        """Return the logical head for the exact plan-row/order subject."""

    def append(
        self,
        binding: BrokerPlanOrderBinding,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPlanOrderBinding:
        """Append or return one exact first winner using predecessor CAS."""

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPlanOrderBinding | None:
        """Return one exact immutable binding knowable at the cutoff."""


class RegisterBrokerPlanOrderBinding:
    """Seal one inactive binding from three stable trusted owner reads."""

    def __init__(
        self,
        *,
        plan_provider: ExactPortfolioPlanOrderProvider,
        receipt_provider: ExactPortfolioInactiveReceiptProvider,
        order_provider: ExactBrokerOrderArtifactProvider,
        repository: BrokerPlanOrderBindingRepository,
    ) -> None:
        self._plan_provider = plan_provider
        self._receipt_provider = receipt_provider
        self._order_provider = order_provider
        self._repository = repository

    def execute(self, command: RegisterBrokerPlanOrderBindingCommand) -> BrokerPlanOrderBinding:
        """Double-read every source at one cutoff and append by predecessor CAS."""

        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Broker server clock")
            first = self._read_sources(command, recorded_at)
            winner = self._repository.get_binding_winner(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                plan_id=command.plan_id,
                plan_version=command.plan_version,
                plan_order_ordinal=command.plan_order_ordinal,
                order_artifact_id=command.order_artifact_id,
                as_of=recorded_at,
            )
            final = self._read_sources(command, recorded_at)
            if first != final:
                raise BrokerPlanOrderBindingCorruption(
                    "Plan-to-Order owner sources changed during registration"
                )
            plan, receipt, order = final
            if winner is not None:
                self._validate_winner(winner, command, final, head, recorded_at)
                return winner
            checked_head = self._optional_head(head, recorded_at)
            candidate = self._build_binding(
                command,
                plan,
                receipt,
                order,
                recorded_at=recorded_at,
                supersedes_binding_hash=(
                    checked_head.content_hash if checked_head is not None else None
                ),
            )
            if checked_head is not None:
                try:
                    validate_plan_order_binding_successor(checked_head, candidate)
                except (TypeError, ValueError) as error:
                    raise BrokerPlanOrderBindingCorruption(
                        "Plan-to-Order successor is invalid"
                    ) from error
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=(
                    checked_head.content_hash if checked_head is not None else None
                ),
                recorded_at=recorded_at,
            )
            checked_persisted = self._require_binding(persisted)
            if checked_persisted != candidate:
                raise BrokerPlanOrderBindingConflict(
                    "concurrent Plan-to-Order binding first winner differs"
                )
            return checked_persisted

    def _read_sources(
        self, command: RegisterBrokerPlanOrderBindingCommand, as_of: datetime
    ) -> tuple[
        ExactPortfolioPlanOrderDefinition,
        ExactPortfolioInactiveReceiptDefinition,
        ExactBrokerOrderArtifactDefinition,
    ]:
        plan = self._plan_provider.get_exact_active(
            plan_id=command.plan_id,
            plan_version=command.plan_version,
            order_ordinal=command.plan_order_ordinal,
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
            raise BrokerPlanOrderBindingCorruption(
                "Portfolio receipt does not bind the exact plan definition"
            )
        return checked_plan, checked_receipt, checked_order

    @staticmethod
    def _require_plan(
        value: ExactPortfolioPlanOrderDefinition | None,
        command: RegisterBrokerPlanOrderBindingCommand,
        as_of: datetime,
    ) -> ExactPortfolioPlanOrderDefinition:
        if value is None:
            raise BrokerPlanOrderBindingUnavailable("exact Portfolio plan row is unavailable")
        if type(value) is not ExactPortfolioPlanOrderDefinition:
            raise BrokerPlanOrderBindingCorruption("Portfolio plan row type substitution")
        try:
            ExactPortfolioPlanOrderDefinition.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise BrokerPlanOrderBindingCorruption("Portfolio plan row is invalid") from error
        if value.plan_id != command.plan_id or value.plan_version != command.plan_version:
            raise BrokerPlanOrderBindingCorruption("Portfolio plan identity substitution")
        if value.order_ordinal != command.plan_order_ordinal:
            raise BrokerPlanOrderBindingCorruption("Portfolio plan order ordinal substitution")
        if not value.is_active_at(as_of):
            raise BrokerPlanOrderBindingUnavailable("exact Portfolio plan row is unavailable")
        return value

    @staticmethod
    def _require_receipt(
        value: ExactPortfolioInactiveReceiptDefinition | None,
        command: RegisterBrokerPlanOrderBindingCommand,
        as_of: datetime,
    ) -> ExactPortfolioInactiveReceiptDefinition:
        if value is None:
            raise BrokerPlanOrderBindingUnavailable(
                "exact inactive Portfolio receipt is unavailable"
            )
        if type(value) is not ExactPortfolioInactiveReceiptDefinition:
            raise BrokerPlanOrderBindingCorruption("Portfolio receipt type substitution")
        try:
            ExactPortfolioInactiveReceiptDefinition.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise BrokerPlanOrderBindingCorruption("Portfolio receipt is invalid") from error
        if (
            value.receipt_id != command.portfolio_receipt_id
            or value.receipt_version != command.portfolio_receipt_version
        ):
            raise BrokerPlanOrderBindingCorruption("Portfolio receipt identity substitution")
        if not value.is_knowable_at(as_of):
            raise BrokerPlanOrderBindingUnavailable(
                "exact inactive Portfolio receipt is unavailable"
            )
        return value

    @staticmethod
    def _require_order(
        value: ExactBrokerOrderArtifactDefinition | None,
        command: RegisterBrokerPlanOrderBindingCommand,
        as_of: datetime,
    ) -> ExactBrokerOrderArtifactDefinition:
        if value is None:
            raise BrokerPlanOrderBindingUnavailable(
                "exact inactive Broker order artifact is unavailable"
            )
        if type(value) is not ExactBrokerOrderArtifactDefinition:
            raise BrokerPlanOrderBindingCorruption("Broker order artifact type substitution")
        try:
            ExactBrokerOrderArtifactDefinition.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise BrokerPlanOrderBindingCorruption("Broker order artifact is invalid") from error
        if (
            value.artifact_id != command.order_artifact_id
            or value.artifact_version != command.order_artifact_version
        ):
            raise BrokerPlanOrderBindingCorruption("Broker order artifact identity substitution")
        if not value.is_knowable_at(as_of):
            raise BrokerPlanOrderBindingUnavailable(
                "exact inactive Broker order artifact is unavailable"
            )
        return value

    @staticmethod
    def _build_binding(
        command: RegisterBrokerPlanOrderBindingCommand,
        plan: ExactPortfolioPlanOrderDefinition,
        receipt: ExactPortfolioInactiveReceiptDefinition,
        order: ExactBrokerOrderArtifactDefinition,
        *,
        recorded_at: datetime,
        supersedes_binding_hash: str | None,
    ) -> BrokerPlanOrderBinding:
        return BrokerPlanOrderBinding(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            portfolio_plan_id=plan.plan_id,
            portfolio_plan_version=plan.plan_version,
            portfolio_plan_content_hash=plan.content_hash,
            portfolio_account_id=plan.account_id,
            portfolio_receipt_id=receipt.receipt_id,
            portfolio_receipt_version=receipt.receipt_version,
            portfolio_receipt_content_hash=receipt.content_hash,
            portfolio_subject_id=receipt.subject_id,
            portfolio_subject_version=receipt.subject_version,
            portfolio_subject_content_hash=receipt.subject_content_hash,
            plan_order_ordinal=plan.order_ordinal,
            plan_order_payload_json=plan.order_payload_json,
            plan_order_content_hash=plan.order_content_hash,
            broker_account_id=order.account_id,
            order_artifact_id=order.artifact_id,
            order_artifact_version=order.artifact_version,
            order_artifact_identity_hash=order.identity_hash,
            order_artifact_content_hash=order.content_hash,
            order_approval_digest=order.approval_digest,
            order_version=order.order_version,
            portfolio_plan_valid_until=plan.valid_until,
            portfolio_receipt_valid_until=receipt.valid_until,
            order_artifact_valid_until=order.valid_until,
            recorded_at=recorded_at,
            valid_until=min(plan.valid_until, receipt.valid_until, order.valid_until),
            supersedes_binding_hash=supersedes_binding_hash,
        )

    def _validate_winner(
        self,
        winner: BrokerPlanOrderBinding,
        command: RegisterBrokerPlanOrderBindingCommand,
        sources: tuple[
            ExactPortfolioPlanOrderDefinition,
            ExactPortfolioInactiveReceiptDefinition,
            ExactBrokerOrderArtifactDefinition,
        ],
        head: BrokerPlanOrderBinding | None,
        as_of: datetime,
    ) -> None:
        checked = self._require_binding(winner)
        if not checked.is_knowable_at(as_of):
            raise BrokerPlanOrderBindingUnavailable("persisted binding is unavailable")
        plan, receipt, order = sources
        stable = self._build_binding(
            command,
            plan,
            receipt,
            order,
            recorded_at=checked.recorded_at,
            supersedes_binding_hash=checked.supersedes_binding_hash,
        )
        if stable != checked:
            raise BrokerPlanOrderBindingConflict("binding identity has another first winner")
        if head is None or self._require_binding(head) != checked:
            raise BrokerPlanOrderBindingConflict(
                "binding identity is no longer the logical current head"
            )

    @classmethod
    def _optional_head(
        cls, value: BrokerPlanOrderBinding | None, as_of: datetime
    ) -> BrokerPlanOrderBinding | None:
        if value is None:
            return None
        checked = cls._require_binding(value)
        if not checked.is_knowable_at(as_of):
            raise BrokerPlanOrderBindingCorruption("binding current head is not active")
        return checked

    @staticmethod
    def _require_binding(value: object) -> BrokerPlanOrderBinding:
        if type(value) is not BrokerPlanOrderBinding:
            raise BrokerPlanOrderBindingCorruption("binding type substitution")
        try:
            BrokerPlanOrderBinding.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise BrokerPlanOrderBindingCorruption("binding is invalid") from error
        if (
            value.activation_available
            or not value.must_not_execute
            or value.permission != "inactive"
        ):
            raise BrokerPlanOrderBindingCorruption("binding execution state substitution")
        return value


class GetExactBrokerPlanOrderBinding:
    """Expose exact inactive identity/hash/PIT reads."""

    def __init__(self, repository: BrokerPlanOrderBindingRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactBrokerPlanOrderBindingCommand
    ) -> BrokerPlanOrderBinding | None:
        """Return only one exact knowable inactive binding."""

        value = self._repository.get_exact_by_hash(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = RegisterBrokerPlanOrderBinding._require_binding(value)
        if (
            checked.binding_id != command.binding_id
            or checked.binding_version != command.binding_version
            or checked.content_hash != command.expected_content_hash
        ):
            raise BrokerPlanOrderBindingCorruption("binding exact identity substitution")
        return checked if checked.is_knowable_at(command.as_of) else None


class GetCurrentBrokerPlanOrderBinding:
    """Return only the exact inactive logical head matching a closed selector."""

    def __init__(self, repository: BrokerPlanOrderBindingRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetCurrentBrokerPlanOrderBindingCommand
    ) -> BrokerPlanOrderBinding | None:
        """Reject historical heads and every plan, row, receipt, or order substitution."""

        value = GetExactBrokerPlanOrderBinding(self._repository).execute(
            GetExactBrokerPlanOrderBindingCommand(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if value is None:
            return None
        selector = (
            value.portfolio_plan_id,
            value.portfolio_plan_version,
            value.portfolio_plan_content_hash,
            value.portfolio_account_id,
            value.portfolio_receipt_id,
            value.portfolio_receipt_version,
            value.portfolio_receipt_content_hash,
            value.portfolio_subject_id,
            value.portfolio_subject_version,
            value.portfolio_subject_content_hash,
            value.plan_order_ordinal,
            value.plan_order_content_hash,
            value.broker_account_id,
            value.order_artifact_id,
            value.order_artifact_version,
            value.order_artifact_identity_hash,
            value.order_artifact_content_hash,
            value.order_approval_digest,
            value.order_version,
        )
        requested = (
            command.portfolio_plan_id,
            command.portfolio_plan_version,
            command.portfolio_plan_content_hash,
            command.portfolio_account_id,
            command.portfolio_receipt_id,
            command.portfolio_receipt_version,
            command.portfolio_receipt_content_hash,
            command.portfolio_subject_id,
            command.portfolio_subject_version,
            command.portfolio_subject_content_hash,
            command.plan_order_ordinal,
            command.plan_order_content_hash,
            command.broker_account_id,
            command.order_artifact_id,
            command.order_artifact_version,
            command.order_artifact_identity_hash,
            command.order_artifact_content_hash,
            command.order_approval_digest,
            command.order_version,
        )
        if selector != requested:
            raise BrokerPlanOrderBindingCorruption("binding current selector substitution")
        head = self._repository.get_current_head(
            plan_id=value.portfolio_plan_id,
            plan_version=value.portfolio_plan_version,
            plan_order_ordinal=value.plan_order_ordinal,
            order_artifact_id=value.order_artifact_id,
            as_of=command.as_of,
        )
        if head is None:
            return None
        checked_head = RegisterBrokerPlanOrderBinding._require_binding(head)
        return value if checked_head == value else None


__all__ = [
    "BrokerPlanOrderBindingConflict",
    "BrokerPlanOrderBindingCorruption",
    "BrokerPlanOrderBindingRepository",
    "BrokerPlanOrderBindingUnavailable",
    "ExactBrokerOrderArtifactDefinition",
    "ExactBrokerOrderArtifactProvider",
    "ExactPortfolioInactiveReceiptDefinition",
    "ExactPortfolioInactiveReceiptProvider",
    "ExactPortfolioPlanOrderDefinition",
    "ExactPortfolioPlanOrderProvider",
    "GetCurrentBrokerPlanOrderBinding",
    "GetCurrentBrokerPlanOrderBindingCommand",
    "GetExactBrokerPlanOrderBinding",
    "GetExactBrokerPlanOrderBindingCommand",
    "RegisterBrokerPlanOrderBinding",
    "RegisterBrokerPlanOrderBindingCommand",
]
