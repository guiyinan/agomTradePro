"""Exact Portfolio-owned realized-outcome seal for R5 promotion trials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


class _PortfolioOutcomeValues(TypedDict):
    outcome_version: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    observation_id: str
    fixed_income_result_id: str
    fixed_income_result_version: str
    fixed_income_result_record_hash: str
    fixed_income_owner_seal_hash: str
    selection_as_of: datetime
    outcome_observed_at: datetime
    outcome_available_at: datetime
    recorded_at: datetime
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


@dataclass(frozen=True)
class R5PortfolioOutcomeSeal:
    """Complete projection of one canonical Portfolio outcome owner record."""

    outcome_id: str
    outcome_version: str
    owner: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    observation_id: str
    fixed_income_result_id: str
    fixed_income_result_version: str
    fixed_income_result_record_hash: str
    fixed_income_owner_seal_hash: str
    selection_as_of: datetime
    outcome_observed_at: datetime
    outcome_available_at: datetime
    recorded_at: datetime
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
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        outcome_version: str,
        owner_record_id: str,
        owner_record_version: str,
        owner_record_hash: str,
        observation_id: str,
        fixed_income_result_id: str,
        fixed_income_result_version: str,
        fixed_income_result_record_hash: str,
        fixed_income_owner_seal_hash: str,
        selection_as_of: datetime,
        outcome_observed_at: datetime,
        outcome_available_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        target_gross_return: Decimal,
        target_cost: Decimal,
        benchmark_gross_return: Decimal,
        benchmark_cost: Decimal,
        target_maximum_drawdown: Decimal,
        benchmark_maximum_drawdown: Decimal,
        capacity_utilization: Decimal,
        liquidity_breached: bool,
        realized_credit_loss: Decimal,
    ) -> R5PortfolioOutcomeSeal:
        """Seal all identity, owner, formation, clock, return and risk fields."""

        values: _PortfolioOutcomeValues = {
            "outcome_version": outcome_version,
            "owner_record_id": owner_record_id,
            "owner_record_version": owner_record_version,
            "owner_record_hash": owner_record_hash,
            "observation_id": observation_id,
            "fixed_income_result_id": fixed_income_result_id,
            "fixed_income_result_version": fixed_income_result_version,
            "fixed_income_result_record_hash": fixed_income_result_record_hash,
            "fixed_income_owner_seal_hash": fixed_income_owner_seal_hash,
            "selection_as_of": selection_as_of,
            "outcome_observed_at": outcome_observed_at,
            "outcome_available_at": outcome_available_at,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
            "target_gross_return": target_gross_return,
            "target_cost": target_cost,
            "benchmark_gross_return": benchmark_gross_return,
            "benchmark_cost": benchmark_cost,
            "target_maximum_drawdown": target_maximum_drawdown,
            "benchmark_maximum_drawdown": benchmark_maximum_drawdown,
            "capacity_utilization": capacity_utilization,
            "liquidity_breached": liquidity_breached,
            "realized_credit_loss": realized_credit_loss,
        }
        digest = canonical_hash(_portfolio_outcome_payload(**values))
        return cls(
            outcome_id=f"r5-rv-portfolio-outcome:{digest}",
            owner="portfolio",
            content_hash=digest,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            **values,
        )

    def __post_init__(self) -> None:
        if self.owner != "portfolio":
            raise ValueError("R5 realized outcome must be Portfolio-owned")
        for field_name in (
            "outcome_id",
            "outcome_version",
            "owner_record_id",
            "owner_record_version",
            "observation_id",
            "fixed_income_result_id",
            "fixed_income_result_version",
        ):
            require_token(
                str(getattr(self, field_name)),
                f"R5 Portfolio outcome {field_name}",
                maximum=300,
            )
        for field_name in (
            "owner_record_hash",
            "fixed_income_result_record_hash",
            "fixed_income_owner_seal_hash",
            "content_hash",
        ):
            require_sha256(
                str(getattr(self, field_name)),
                f"R5 Portfolio outcome {field_name}",
            )
        for field_name in (
            "selection_as_of",
            "outcome_observed_at",
            "outcome_available_at",
            "recorded_at",
            "valid_until",
        ):
            require_aware(
                getattr(self, field_name),
                f"R5 Portfolio outcome {field_name}",
            )
        if not (
            self.selection_as_of
            < self.outcome_observed_at
            <= self.outcome_available_at
            <= self.recorded_at
            < self.valid_until
        ):
            raise ValueError("R5 Portfolio outcome clocks are invalid")
        for field_name in (
            "target_gross_return",
            "target_cost",
            "benchmark_gross_return",
            "benchmark_cost",
            "target_maximum_drawdown",
            "benchmark_maximum_drawdown",
            "capacity_utilization",
            "realized_credit_loss",
        ):
            _require_finite(
                getattr(self, field_name),
                f"R5 Portfolio outcome {field_name}",
            )
        if self.target_cost < 0 or self.benchmark_cost < 0:
            raise ValueError("R5 Portfolio outcome costs cannot be negative")
        if self.target_net_return <= Decimal("-1"):
            raise ValueError("R5 target net return must be greater than -100%")
        if self.benchmark_net_return <= Decimal("-1"):
            raise ValueError("R5 benchmark net return must be greater than -100%")
        for drawdown in (
            self.target_maximum_drawdown,
            self.benchmark_maximum_drawdown,
        ):
            if not Decimal("0") <= drawdown <= Decimal("1"):
                raise ValueError("R5 Portfolio drawdown must be within [0, 1]")
        if self.capacity_utilization < 0:
            raise ValueError("R5 Portfolio capacity utilization cannot be negative")
        if type(self.liquidity_breached) is not bool:
            raise ValueError("R5 Portfolio liquidity breach state must be boolean")
        if self.realized_credit_loss < 0:
            raise ValueError("R5 Portfolio credit loss cannot be negative")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R5 Portfolio outcome must remain research-only")
        expected = r5_portfolio_outcome_seal_hash(self)
        if (
            self.content_hash != expected
            or self.outcome_id != f"r5-rv-portfolio-outcome:{expected}"
        ):
            raise ValueError("R5 Portfolio outcome content hash or identity mismatch")

    @property
    def target_net_return(self) -> Decimal:
        """Return target return after its exact once-only cost."""

        return self.target_gross_return - self.target_cost

    @property
    def benchmark_net_return(self) -> Decimal:
        """Return benchmark return after its exact once-only cost."""

        return self.benchmark_gross_return - self.benchmark_cost

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact owner record is known and valid."""

        require_aware(as_of, "R5 Portfolio outcome as_of")
        return self.recorded_at <= as_of < self.valid_until


def _portfolio_outcome_payload(
    *,
    outcome_version: str,
    owner_record_id: str,
    owner_record_version: str,
    owner_record_hash: str,
    observation_id: str,
    fixed_income_result_id: str,
    fixed_income_result_version: str,
    fixed_income_result_record_hash: str,
    fixed_income_owner_seal_hash: str,
    selection_as_of: datetime,
    outcome_observed_at: datetime,
    outcome_available_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    target_gross_return: Decimal,
    target_cost: Decimal,
    benchmark_gross_return: Decimal,
    benchmark_cost: Decimal,
    target_maximum_drawdown: Decimal,
    benchmark_maximum_drawdown: Decimal,
    capacity_utilization: Decimal,
    liquidity_breached: bool,
    realized_credit_loss: Decimal,
) -> dict[str, object]:
    return {
        "schema": "research-r5-portfolio-relative-value-outcome.v1",
        "identity": (outcome_version, "portfolio"),
        "owner_record": (
            owner_record_id,
            owner_record_version,
            owner_record_hash,
        ),
        "observation_id": observation_id,
        "fixed_income_result": (
            fixed_income_result_id,
            fixed_income_result_version,
            fixed_income_result_record_hash,
            fixed_income_owner_seal_hash,
        ),
        "window": (
            selection_as_of,
            outcome_observed_at,
            outcome_available_at,
            recorded_at,
            valid_until,
        ),
        "returns": (
            target_gross_return,
            target_cost,
            benchmark_gross_return,
            benchmark_cost,
        ),
        "risk": (
            target_maximum_drawdown,
            benchmark_maximum_drawdown,
            capacity_utilization,
            liquidity_breached,
            realized_credit_loss,
        ),
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r5_portfolio_outcome_seal_hash(outcome: R5PortfolioOutcomeSeal) -> str:
    """Recompute the complete exact Portfolio outcome seal hash."""

    return canonical_hash(
        _portfolio_outcome_payload(
            outcome_version=outcome.outcome_version,
            owner_record_id=outcome.owner_record_id,
            owner_record_version=outcome.owner_record_version,
            owner_record_hash=outcome.owner_record_hash,
            observation_id=outcome.observation_id,
            fixed_income_result_id=outcome.fixed_income_result_id,
            fixed_income_result_version=outcome.fixed_income_result_version,
            fixed_income_result_record_hash=outcome.fixed_income_result_record_hash,
            fixed_income_owner_seal_hash=outcome.fixed_income_owner_seal_hash,
            selection_as_of=outcome.selection_as_of,
            outcome_observed_at=outcome.outcome_observed_at,
            outcome_available_at=outcome.outcome_available_at,
            recorded_at=outcome.recorded_at,
            valid_until=outcome.valid_until,
            target_gross_return=outcome.target_gross_return,
            target_cost=outcome.target_cost,
            benchmark_gross_return=outcome.benchmark_gross_return,
            benchmark_cost=outcome.benchmark_cost,
            target_maximum_drawdown=outcome.target_maximum_drawdown,
            benchmark_maximum_drawdown=outcome.benchmark_maximum_drawdown,
            capacity_utilization=outcome.capacity_utilization,
            liquidity_breached=outcome.liquidity_breached,
            realized_credit_loss=outcome.realized_credit_loss,
        )
    )


__all__ = ["R5PortfolioOutcomeSeal", "r5_portfolio_outcome_seal_hash"]
