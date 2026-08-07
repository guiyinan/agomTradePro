"""ID-only persistence contracts for Portfolio-owned R5 realized outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, TypedDict, Unpack

from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecordCommand,
)
from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal

R5_PORTFOLIO_OUTCOME_VERSION = "portfolio-r5-relative-value-outcome.v1"


class R5PortfolioOutcomePersistenceConflict(ValueError):
    """Raised when one owner identity resolves to absent or different evidence."""


class R5PortfolioOutcomePersistenceCorruption(ValueError):
    """Raised when persisted headers, payloads, or owner projections disagree."""


class _SourceFactoryValues(TypedDict):
    owner_record_id: str
    owner_record_version: str
    observation_id: str
    fixed_income_result_id: str
    fixed_income_result_version: str
    fixed_income_result_record_hash: str
    selection_as_of: datetime
    outcome_observed_at: datetime
    outcome_available_at: datetime
    valid_until: datetime
    target_gross_return: Decimal
    target_cost: Decimal
    benchmark_gross_return: Decimal
    benchmark_cost: Decimal
    target_maximum_drawdown: Decimal
    benchmark_maximum_drawdown: Decimal
    capacity_utilization: Decimal
    liquidity_breached: bool
    realized_credit_loss: Decimal


class _SourceConstructorValues(_SourceFactoryValues):
    owner: str
    owner_record_hash: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool


def r5_portfolio_outcome_command_hash(
    *,
    owner_record_id: str,
    owner_record_version: str,
) -> str:
    """Hash the complete caller-safe ID/version persistence command."""

    require_token(owner_record_id, "owner_record_id", maximum=300)
    require_token(owner_record_version, "owner_record_version", maximum=300)
    return canonical_hash(
        {
            "schema": "portfolio-r5-outcome-persistence-command.v1",
            "owner_record": (owner_record_id, owner_record_version),
        }
    )


def _source_payload(values: _SourceFactoryValues) -> dict[str, object]:
    return {
        "schema": "portfolio-r5-relative-value-outcome-source.v1",
        "owner": "portfolio",
        "owner_record": (
            values["owner_record_id"],
            values["owner_record_version"],
        ),
        "observation_id": values["observation_id"],
        "fixed_income_result": (
            values["fixed_income_result_id"],
            values["fixed_income_result_version"],
            values["fixed_income_result_record_hash"],
        ),
        "window": (
            values["selection_as_of"],
            values["outcome_observed_at"],
            values["outcome_available_at"],
            values["valid_until"],
        ),
        "returns": (
            values["target_gross_return"],
            values["target_cost"],
            values["benchmark_gross_return"],
            values["benchmark_cost"],
        ),
        "risk": (
            values["target_maximum_drawdown"],
            values["benchmark_maximum_drawdown"],
            values["capacity_utilization"],
            values["liquidity_breached"],
            values["realized_credit_loss"],
        ),
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


@dataclass(frozen=True)
class R5PortfolioOutcomeSourceRecord:
    """Canonical Portfolio owner record returned by a trusted Application port."""

    owner: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    observation_id: str
    fixed_income_result_id: str
    fixed_income_result_version: str
    fixed_income_result_record_hash: str
    selection_as_of: datetime
    outcome_observed_at: datetime
    outcome_available_at: datetime
    valid_until: datetime
    target_gross_return: Decimal
    target_cost: Decimal
    benchmark_gross_return: Decimal
    benchmark_cost: Decimal
    target_maximum_drawdown: Decimal
    benchmark_maximum_drawdown: Decimal
    capacity_utilization: Decimal
    liquidity_breached: bool
    realized_credit_loss: Decimal
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        **values: Unpack[_SourceFactoryValues],
    ) -> R5PortfolioOutcomeSourceRecord:
        """Create and seal one complete canonical Portfolio source record."""

        digest = canonical_hash(_source_payload(values))
        return cls(
            owner="portfolio",
            owner_record_hash=digest,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            **values,
        )

    def __post_init__(self) -> None:
        if self.owner != "portfolio":
            raise ValueError("R5 outcome source must be Portfolio-owned")
        for name in (
            "owner_record_id",
            "owner_record_version",
            "observation_id",
            "fixed_income_result_id",
            "fixed_income_result_version",
        ):
            require_token(str(getattr(self, name)), f"R5 outcome source {name}", maximum=300)
        require_sha256(self.owner_record_hash, "R5 outcome source owner_record_hash")
        require_sha256(
            self.fixed_income_result_record_hash,
            "R5 outcome source fixed_income_result_record_hash",
        )
        for name in (
            "selection_as_of",
            "outcome_observed_at",
            "outcome_available_at",
            "valid_until",
        ):
            require_aware(getattr(self, name), f"R5 outcome source {name}")
        if not (
            self.selection_as_of
            < self.outcome_observed_at
            <= self.outcome_available_at
            < self.valid_until
        ):
            raise ValueError("R5 outcome source clocks are invalid")
        for name in (
            "target_gross_return",
            "target_cost",
            "benchmark_gross_return",
            "benchmark_cost",
            "target_maximum_drawdown",
            "benchmark_maximum_drawdown",
            "capacity_utilization",
            "realized_credit_loss",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"R5 outcome source {name} must be a finite Decimal")
        if self.target_cost < 0 or self.benchmark_cost < 0:
            raise ValueError("R5 outcome source costs cannot be negative")
        if self.target_gross_return - self.target_cost <= Decimal("-1"):
            raise ValueError("R5 target net return must be greater than -100%")
        if self.benchmark_gross_return - self.benchmark_cost <= Decimal("-1"):
            raise ValueError("R5 benchmark net return must be greater than -100%")
        for drawdown in (
            self.target_maximum_drawdown,
            self.benchmark_maximum_drawdown,
        ):
            if not Decimal("0") <= drawdown <= Decimal("1"):
                raise ValueError("R5 outcome source drawdown must be within [0, 1]")
        if self.capacity_utilization < 0:
            raise ValueError("R5 outcome source capacity utilization cannot be negative")
        if type(self.liquidity_breached) is not bool:
            raise ValueError("R5 outcome source liquidity state must be boolean")
        if self.realized_credit_loss < 0:
            raise ValueError("R5 outcome source credit loss cannot be negative")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R5 outcome source must remain research-only")
        if self.owner_record_hash != canonical_hash(_source_payload(self.factory_values)):
            raise ValueError("R5 outcome source owner record hash mismatch")

    @property
    def factory_values(self) -> _SourceFactoryValues:
        """Return exact values accepted by the canonical factory."""

        return {
            "owner_record_id": self.owner_record_id,
            "owner_record_version": self.owner_record_version,
            "observation_id": self.observation_id,
            "fixed_income_result_id": self.fixed_income_result_id,
            "fixed_income_result_version": self.fixed_income_result_version,
            "fixed_income_result_record_hash": self.fixed_income_result_record_hash,
            "selection_as_of": self.selection_as_of,
            "outcome_observed_at": self.outcome_observed_at,
            "outcome_available_at": self.outcome_available_at,
            "valid_until": self.valid_until,
            "target_gross_return": self.target_gross_return,
            "target_cost": self.target_cost,
            "benchmark_gross_return": self.benchmark_gross_return,
            "benchmark_cost": self.benchmark_cost,
            "target_maximum_drawdown": self.target_maximum_drawdown,
            "benchmark_maximum_drawdown": self.benchmark_maximum_drawdown,
            "capacity_utilization": self.capacity_utilization,
            "liquidity_breached": self.liquidity_breached,
            "realized_credit_loss": self.realized_credit_loss,
        }

    @property
    def constructor_values(self) -> _SourceConstructorValues:
        """Return every constructor field for strict tamper tests and codecs."""

        return {
            "owner": self.owner,
            "owner_record_hash": self.owner_record_hash,
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
            **self.factory_values,
        }


class R5PortfolioOutcomeSource(Protocol):
    """Exact Portfolio Application owner query; never latest/current/list."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction boundary key."""

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSourceRecord | None:
        """Return one canonical owner record by exact identity."""


class ExactR5RelativeValueOwnerRecordQuery(Protocol):
    """FixedIncome Application query used inside the shared persistence UoW."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction boundary key."""

    def execute(
        self,
        command: GetExactR5RelativeValueOwnerRecordCommand,
    ) -> R5RelativeValueOwnerRecordSeal | None:
        """Return one strict exact FixedIncome owner projection."""


@dataclass(frozen=True)
class R5PortfolioOutcomePersistenceDraft:
    """Authoritatively reread Portfolio source plus exact FixedIncome seal."""

    source_record: R5PortfolioOutcomeSourceRecord
    fixed_income_record: R5RelativeValueOwnerRecordSeal

    def __post_init__(self) -> None:
        source = self.source_record
        fixed_income = self.fixed_income_record
        if (
            source.fixed_income_result_id != fixed_income.result_id
            or source.fixed_income_result_version != fixed_income.result_version
            or source.fixed_income_result_record_hash != fixed_income.result_record_hash
            or fixed_income.recorded_at > source.selection_as_of
        ):
            raise ValueError("R5 outcome fixed-income owner projection mismatch")

    @property
    def expected_command_hash(self) -> str:
        """Rebuild the caller-safe command authorizing this source record."""

        return r5_portfolio_outcome_command_hash(
            owner_record_id=self.source_record.owner_record_id,
            owner_record_version=self.source_record.owner_record_version,
        )

    @property
    def draft_hash(self) -> str:
        """Seal the complete semantic draft before the server clock is claimed."""

        return canonical_hash(
            {
                "schema": "portfolio-r5-outcome-persistence-draft.v1",
                "source_record": self.source_record,
                "fixed_income_record": self.fixed_income_record,
            }
        )

    def to_outcome(self, *, recorded_at: datetime) -> R5PortfolioOutcomeSeal:
        """Create the immutable outcome using only the repository server clock."""

        source = self.source_record
        return R5PortfolioOutcomeSeal.create(
            outcome_version=R5_PORTFOLIO_OUTCOME_VERSION,
            owner_record_id=source.owner_record_id,
            owner_record_version=source.owner_record_version,
            owner_record_hash=source.owner_record_hash,
            observation_id=source.observation_id,
            fixed_income_result_id=source.fixed_income_result_id,
            fixed_income_result_version=source.fixed_income_result_version,
            fixed_income_result_record_hash=source.fixed_income_result_record_hash,
            fixed_income_owner_seal_hash=self.fixed_income_record.content_hash,
            selection_as_of=source.selection_as_of,
            outcome_observed_at=source.outcome_observed_at,
            outcome_available_at=source.outcome_available_at,
            recorded_at=recorded_at,
            valid_until=source.valid_until,
            target_gross_return=source.target_gross_return,
            target_cost=source.target_cost,
            benchmark_gross_return=source.benchmark_gross_return,
            benchmark_cost=source.benchmark_cost,
            target_maximum_drawdown=source.target_maximum_drawdown,
            benchmark_maximum_drawdown=source.benchmark_maximum_drawdown,
            capacity_utilization=source.capacity_utilization,
            liquidity_breached=source.liquidity_breached,
            realized_credit_loss=source.realized_credit_loss,
        )


@dataclass(frozen=True)
class PersistR5PortfolioOutcomeCommand:
    """ID/version-only request with no payload, hashes, clocks, or capabilities."""

    owner_record_id: str
    owner_record_version: str

    def __post_init__(self) -> None:
        require_token(self.owner_record_id, "owner_record_id", maximum=300)
        require_token(self.owner_record_version, "owner_record_version", maximum=300)

    @property
    def command_hash(self) -> str:
        """Return the complete caller-safe command seal."""

        return r5_portfolio_outcome_command_hash(
            owner_record_id=self.owner_record_id,
            owner_record_version=self.owner_record_version,
        )


@dataclass(frozen=True)
class GetExactR5PortfolioOutcomeCommand:
    """Hash-bound PIT query without latest/current/list semantics."""

    outcome_id: str
    outcome_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        require_token(self.outcome_id, "outcome_id", maximum=300)
        require_token(self.outcome_version, "outcome_version", maximum=300)
        require_sha256(self.expected_content_hash, "expected_content_hash")
        require_aware(self.as_of, "as_of")


class R5PortfolioOutcomePersistenceRepository(Protocol):
    """Read-only exact-query port for the Portfolio outcome ledger."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction boundary key."""

    def get_exact(
        self,
        *,
        outcome_id: str,
        outcome_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        """Return one active, hash-bound, owner-verified outcome."""


class R5PortfolioOutcomePersistenceWriter(Protocol):
    """Trusted closure writer accepting only caller-safe ID-only commands."""

    def persist(
        self,
        command: PersistR5PortfolioOutcomeCommand,
    ) -> R5PortfolioOutcomeSeal:
        """Reread every owner and atomically append or replay one winner."""


class PersistR5PortfolioOutcome:
    """Application use case for one exact owner-bound append."""

    def __init__(self, *, writer: R5PortfolioOutcomePersistenceWriter) -> None:
        self._writer = writer

    def execute(self, command: PersistR5PortfolioOutcomeCommand) -> R5PortfolioOutcomeSeal:
        """Delegate one ID-only command to the closure-bound writer."""

        return self._writer.persist(command)


class GetExactPersistedR5PortfolioOutcome:
    """Application use case for one active PIT exact replay."""

    def __init__(self, repository: R5PortfolioOutcomePersistenceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR5PortfolioOutcomeCommand,
    ) -> R5PortfolioOutcomeSeal | None:
        """Return one exact outcome after strict restoration and owner replay."""

        return self._repository.get_exact(
            outcome_id=command.outcome_id,
            outcome_version=command.outcome_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )


__all__ = [
    "GetExactPersistedR5PortfolioOutcome",
    "GetExactR5PortfolioOutcomeCommand",
    "PersistR5PortfolioOutcome",
    "PersistR5PortfolioOutcomeCommand",
    "R5_PORTFOLIO_OUTCOME_VERSION",
    "R5PortfolioOutcomePersistenceConflict",
    "R5PortfolioOutcomePersistenceCorruption",
    "R5PortfolioOutcomePersistenceDraft",
    "R5PortfolioOutcomePersistenceRepository",
    "R5PortfolioOutcomePersistenceWriter",
    "R5PortfolioOutcomeSource",
    "R5PortfolioOutcomeSourceRecord",
    "ExactR5RelativeValueOwnerRecordQuery",
    "r5_portfolio_outcome_command_hash",
]
