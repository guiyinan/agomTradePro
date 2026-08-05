"""Application contracts for canonical snapshots and execution feedback."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from apps.portfolio.domain.canonical_snapshots import (
    BrokerExecutionEvidence,
    CanonicalCashProjection,
    CanonicalPortfolioSnapshot,
    CanonicalPositionsProjection,
    ConstraintExecutionDeviation,
    PortfolioExecutionFeedback,
    build_canonical_portfolio_snapshot,
    build_execution_feedback,
)


class CanonicalPortfolioSnapshotRepository(Protocol):
    """Persistence port for the Portfolio-owned append-only snapshot truth."""

    def append(self, snapshot: CanonicalPortfolioSnapshot) -> CanonicalPortfolioSnapshot:
        """Append idempotently, rejecting a conflicting immutable identity."""

    def get(self, snapshot_id: str) -> CanonicalPortfolioSnapshot | None:
        """Return one exact snapshot by stable reference."""

    def find_at_or_before(
        self, *, account_ref: str, cutoff: datetime
    ) -> CanonicalPortfolioSnapshot | None:
        """Return the newest source-as-of snapshot not later than the cutoff."""


class PortfolioExecutionFeedbackRepository(Protocol):
    """Persistence port for append-only reconciled execution feedback."""

    def append(self, feedback: PortfolioExecutionFeedback) -> PortfolioExecutionFeedback:
        """Append feedback after verifying its Portfolio-owned references."""

    def get(self, feedback_id: str) -> PortfolioExecutionFeedback | None:
        """Return one exact feedback record."""


class BrokerExecutionEvidenceProvider(Protocol):
    """Broker Execution Application boundary; never exposes its ORM models."""

    def get_reconciled_evidence(
        self,
        *,
        client_order_ref: str,
        reconciliation_ref: str,
    ) -> BrokerExecutionEvidence | None:
        """Return exact broker evidence or ``None`` when evidence is incomplete."""


class PortfolioSnapshotApplicationProtocol(Protocol):
    """Only supported snapshot read surface for Account, Risk, and Strategy."""

    def get_snapshot(self, snapshot_id: str) -> CanonicalPortfolioSnapshot | None:
        """Return one exact immutable snapshot."""

    def get_snapshot_at_or_before(
        self, *, account_ref: str, cutoff: datetime
    ) -> CanonicalPortfolioSnapshot | None:
        """Resolve by source as-of without replacing source timestamps."""


class CanonicalPortfolioSnapshotQueryService:
    """Application-owned snapshot read service for cross-App consumers."""

    def __init__(self, repository: CanonicalPortfolioSnapshotRepository) -> None:
        self._repository = repository

    def get_snapshot(self, snapshot_id: str) -> CanonicalPortfolioSnapshot | None:
        """Return one exact immutable snapshot."""

        return self._repository.get(snapshot_id)

    def get_snapshot_at_or_before(
        self, *, account_ref: str, cutoff: datetime
    ) -> CanonicalPortfolioSnapshot | None:
        """Return the latest eligible source observation at a fixed cutoff."""

        _require_aware(cutoff, "cutoff")
        return self._repository.find_at_or_before(account_ref=account_ref, cutoff=cutoff)


class CreateCanonicalPortfolioSnapshotUseCase:
    """Create and append a canonical snapshot from explicit owner evidence."""

    def __init__(self, repository: CanonicalPortfolioSnapshotRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        cash_projection: CanonicalCashProjection,
        positions_projection: CanonicalPositionsProjection,
    ) -> CanonicalPortfolioSnapshot:
        """Accept only digest-verified owner projections, then append idempotently."""

        snapshot = build_canonical_portfolio_snapshot(
            cash_projection=cash_projection,
            positions_projection=positions_projection,
        )
        return self._repository.append(snapshot)


class RecordPortfolioExecutionFeedbackUseCase:
    """Persist plan-versus-fill metrics only with complete broker evidence."""

    def __init__(
        self,
        *,
        repository: PortfolioExecutionFeedbackRepository,
        broker_evidence_provider: BrokerExecutionEvidenceProvider,
    ) -> None:
        self._repository = repository
        self._broker_evidence_provider = broker_evidence_provider

    def execute(
        self,
        *,
        portfolio_snapshot_ref: str,
        transition_plan_ref: str,
        order_intent_ref: str,
        planning_policy_version: str,
        asset_code: str,
        side: str,
        planned_quantity: Decimal,
        planned_reference_price: Decimal,
        planned_estimated_fee: Decimal,
        client_order_ref: str,
        reconciliation_ref: str,
        constraint_deviations: tuple[ConstraintExecutionDeviation, ...] = (),
    ) -> PortfolioExecutionFeedback:
        """Fail closed if Broker Execution cannot attest the requested references."""

        broker_evidence = self._broker_evidence_provider.get_reconciled_evidence(
            client_order_ref=client_order_ref,
            reconciliation_ref=reconciliation_ref,
        )
        if broker_evidence is None:
            raise ValueError("reconciled broker execution evidence is missing")
        if broker_evidence.client_order_ref != client_order_ref:
            raise ValueError("broker evidence client order reference mismatch")
        if broker_evidence.reconciliation_ref != reconciliation_ref:
            raise ValueError("broker evidence reconciliation reference mismatch")
        feedback = build_execution_feedback(
            portfolio_snapshot_ref=portfolio_snapshot_ref,
            transition_plan_ref=transition_plan_ref,
            order_intent_ref=order_intent_ref,
            planning_policy_version=planning_policy_version,
            asset_code=asset_code,
            side=side,
            planned_quantity=planned_quantity,
            planned_reference_price=planned_reference_price,
            planned_estimated_fee=planned_estimated_fee,
            broker_evidence=broker_evidence,
            constraint_deviations=constraint_deviations,
        )
        return self._repository.append(feedback)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "BrokerExecutionEvidenceProvider",
    "CanonicalPortfolioSnapshotQueryService",
    "CanonicalPortfolioSnapshotRepository",
    "CreateCanonicalPortfolioSnapshotUseCase",
    "PortfolioExecutionFeedbackRepository",
    "PortfolioSnapshotApplicationProtocol",
    "RecordPortfolioExecutionFeedbackUseCase",
]
