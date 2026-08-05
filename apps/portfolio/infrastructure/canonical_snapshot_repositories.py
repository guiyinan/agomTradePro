"""Django repositories for canonical snapshots and execution feedback."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.portfolio.domain.canonical_snapshots import (
    BrokerFillEvidence,
    BrokerOrderEventEvidence,
    CanonicalPortfolioSnapshot,
    CanonicalPosition,
    ConstraintExecutionDeviation,
    PortfolioExecutionFeedback,
    SnapshotEvidenceKind,
    SnapshotSourceEvidence,
)

from .canonical_snapshot_models import (
    CanonicalPortfolioSnapshotModel,
    PortfolioExecutionFeedbackModel,
)
from .models import OrderIntentModel, PortfolioTransitionPlanModel


class DjangoCanonicalPortfolioSnapshotRepository:
    """Persist and read the Portfolio-owned immutable snapshot truth."""

    @transaction.atomic
    def append(self, snapshot: CanonicalPortfolioSnapshot) -> CanonicalPortfolioSnapshot:
        """Append idempotently and reject conflicting immutable identities."""

        existing = CanonicalPortfolioSnapshotModel._default_manager.filter(
            snapshot_id=snapshot.snapshot_id
        ).first()
        if existing is not None:
            if existing.content_hash != snapshot.content_hash:
                raise ValueError("canonical snapshot identity already has different content")
            return self._to_domain(existing)
        duplicate = CanonicalPortfolioSnapshotModel._default_manager.filter(
            content_hash=snapshot.content_hash
        ).first()
        if duplicate is not None:
            return self._to_domain(duplicate)
        evidence_by_kind = {item.kind: item for item in snapshot.source_evidence}
        CanonicalPortfolioSnapshotModel._default_manager.create(
            snapshot_id=snapshot.snapshot_id,
            account_ref=snapshot.account_ref,
            as_of=snapshot.as_of,
            base_currency=snapshot.base_currency,
            cash_balance=snapshot.cash_balance,
            cash_version=snapshot.cash_version,
            positions_version=snapshot.positions_version,
            cash_observed_at=evidence_by_kind[SnapshotEvidenceKind.CASH].observed_at,
            positions_observed_at=evidence_by_kind[SnapshotEvidenceKind.POSITIONS].observed_at,
            positions=[self._position_to_dict(item) for item in snapshot.positions],
            source_evidence=[
                self._source_evidence_to_dict(item) for item in snapshot.source_evidence
            ],
            content_hash=snapshot.content_hash,
        )
        return snapshot

    def get(self, snapshot_id: str) -> CanonicalPortfolioSnapshot | None:
        """Return one exact canonical snapshot."""

        row = CanonicalPortfolioSnapshotModel._default_manager.filter(
            snapshot_id=snapshot_id
        ).first()
        return self._to_domain(row) if row is not None else None

    def find_at_or_before(
        self, *, account_ref: str, cutoff: datetime
    ) -> CanonicalPortfolioSnapshot | None:
        """Resolve an explicit source-as-of cutoff without timestamp washing."""

        row = (
            CanonicalPortfolioSnapshotModel._default_manager.filter(
                account_ref=account_ref,
                as_of__lte=cutoff,
            )
            .order_by("-as_of", "-created_at")
            .first()
        )
        return self._to_domain(row) if row is not None else None

    @classmethod
    def _to_domain(cls, row: CanonicalPortfolioSnapshotModel) -> CanonicalPortfolioSnapshot:
        positions = tuple(cls._position_from_dict(item) for item in (row.positions or []))
        source_evidence = tuple(
            cls._source_evidence_from_dict(item) for item in (row.source_evidence or [])
        )
        return CanonicalPortfolioSnapshot(
            snapshot_id=row.snapshot_id,
            account_ref=row.account_ref,
            as_of=row.as_of,
            base_currency=row.base_currency,
            cash_balance=row.cash_balance,
            cash_version=row.cash_version,
            positions_version=row.positions_version,
            positions=positions,
            source_evidence=source_evidence,
            content_hash=row.content_hash,
        )

    @staticmethod
    def _position_to_dict(item: CanonicalPosition) -> dict[str, object]:
        return {
            "asset_code": item.asset_code,
            "quantity": str(item.quantity),
            "available_quantity": str(item.available_quantity),
            "market_value_base": str(item.market_value_base),
            "position_source_ref": item.position_source_ref,
            "position_observed_at": item.position_observed_at.isoformat(),
            "valuation_source_ref": item.valuation_source_ref,
            "valuation_observed_at": item.valuation_observed_at.isoformat(),
        }

    @staticmethod
    def _position_from_dict(item: dict[str, Any]) -> CanonicalPosition:
        return CanonicalPosition(
            asset_code=str(item["asset_code"]),
            quantity=Decimal(str(item["quantity"])),
            available_quantity=Decimal(str(item["available_quantity"])),
            market_value_base=Decimal(str(item["market_value_base"])),
            position_source_ref=str(item["position_source_ref"]),
            position_observed_at=datetime.fromisoformat(str(item["position_observed_at"])),
            valuation_source_ref=str(item["valuation_source_ref"]),
            valuation_observed_at=datetime.fromisoformat(str(item["valuation_observed_at"])),
        )

    @staticmethod
    def _source_evidence_to_dict(item: SnapshotSourceEvidence) -> dict[str, object]:
        return {
            "kind": item.kind.value,
            "owner": item.owner,
            "evidence_ref": item.evidence_ref,
            "version": item.version,
            "observed_at": item.observed_at.isoformat(),
            "content_hash": item.content_hash,
        }

    @staticmethod
    def _source_evidence_from_dict(item: dict[str, Any]) -> SnapshotSourceEvidence:
        return SnapshotSourceEvidence(
            kind=SnapshotEvidenceKind(str(item["kind"])),
            owner=str(item["owner"]),
            evidence_ref=str(item["evidence_ref"]),
            version=str(item["version"]),
            observed_at=datetime.fromisoformat(str(item["observed_at"])),
            content_hash=str(item["content_hash"]),
        )


class DjangoPortfolioExecutionFeedbackRepository:
    """Persist immutable feedback joined only by stable bounded-context references."""

    @transaction.atomic
    def append(self, feedback: PortfolioExecutionFeedback) -> PortfolioExecutionFeedback:
        """Verify Portfolio references and append feedback idempotently."""

        if not CanonicalPortfolioSnapshotModel._default_manager.filter(
            snapshot_id=feedback.portfolio_snapshot_ref
        ).exists():
            raise ValueError("canonical portfolio snapshot reference is missing")
        if not PortfolioTransitionPlanModel._default_manager.filter(
            plan_id=feedback.transition_plan_ref
        ).exists():
            raise ValueError("portfolio transition plan reference is missing")
        if not OrderIntentModel._default_manager.filter(
            intent_id=feedback.order_intent_ref
        ).exists():
            raise ValueError("portfolio order intent reference is missing")
        existing = PortfolioExecutionFeedbackModel._default_manager.filter(
            feedback_id=feedback.feedback_id
        ).first()
        if existing is not None:
            if existing.content_hash != feedback.content_hash:
                raise ValueError("execution feedback identity already has different content")
            return self._to_domain(existing)
        duplicate = PortfolioExecutionFeedbackModel._default_manager.filter(
            content_hash=feedback.content_hash
        ).first()
        if duplicate is not None:
            return self._to_domain(duplicate)
        PortfolioExecutionFeedbackModel._default_manager.create(
            feedback_id=feedback.feedback_id,
            portfolio_snapshot_ref=feedback.portfolio_snapshot_ref,
            transition_plan_ref=feedback.transition_plan_ref,
            order_intent_ref=feedback.order_intent_ref,
            planning_policy_version=feedback.planning_policy_version,
            asset_code=feedback.asset_code,
            side=feedback.side,
            planned_quantity=feedback.planned_quantity,
            planned_reference_price=feedback.planned_reference_price,
            planned_estimated_fee=feedback.planned_estimated_fee,
            client_order_ref=feedback.client_order_ref,
            broker_order_ref=feedback.broker_order_ref,
            order_events=[self._order_event_to_dict(item) for item in feedback.order_events],
            fills=[self._fill_to_dict(item) for item in feedback.fills],
            reconciliation_ref=feedback.reconciliation_ref,
            reconciliation_observed_at=feedback.reconciliation_observed_at,
            filled_quantity=feedback.filled_quantity,
            average_fill_price=feedback.average_fill_price,
            actual_fee=feedback.actual_fee,
            fee_variance=feedback.fee_variance,
            realized_slippage=feedback.realized_slippage,
            fill_rate=feedback.fill_rate,
            rejected=feedback.rejected,
            rejection_code=feedback.rejection_code,
            rejection_reason=feedback.rejection_reason,
            constraint_deviations=[
                self._deviation_to_dict(item) for item in feedback.constraint_deviations
            ],
            source_evidence_hash=feedback.source_evidence_hash,
            content_hash=feedback.content_hash,
        )
        return feedback

    def get(self, feedback_id: str) -> PortfolioExecutionFeedback | None:
        """Return one exact immutable execution feedback record."""

        row = PortfolioExecutionFeedbackModel._default_manager.filter(
            feedback_id=feedback_id
        ).first()
        return self._to_domain(row) if row is not None else None

    @classmethod
    def _to_domain(cls, row: PortfolioExecutionFeedbackModel) -> PortfolioExecutionFeedback:
        return PortfolioExecutionFeedback(
            feedback_id=row.feedback_id,
            portfolio_snapshot_ref=row.portfolio_snapshot_ref,
            transition_plan_ref=row.transition_plan_ref,
            order_intent_ref=row.order_intent_ref,
            planning_policy_version=row.planning_policy_version,
            asset_code=row.asset_code,
            side=row.side,
            planned_quantity=row.planned_quantity,
            planned_reference_price=row.planned_reference_price,
            planned_estimated_fee=row.planned_estimated_fee,
            client_order_ref=row.client_order_ref,
            broker_order_ref=row.broker_order_ref,
            order_events=tuple(
                cls._order_event_from_dict(item) for item in (row.order_events or [])
            ),
            fills=tuple(cls._fill_from_dict(item) for item in (row.fills or [])),
            reconciliation_ref=row.reconciliation_ref,
            reconciliation_observed_at=row.reconciliation_observed_at,
            filled_quantity=row.filled_quantity,
            average_fill_price=row.average_fill_price,
            actual_fee=row.actual_fee,
            fee_variance=row.fee_variance,
            realized_slippage=row.realized_slippage,
            fill_rate=row.fill_rate,
            rejected=row.rejected,
            rejection_code=row.rejection_code,
            rejection_reason=row.rejection_reason,
            constraint_deviations=tuple(
                cls._deviation_from_dict(item) for item in (row.constraint_deviations or [])
            ),
            source_evidence_hash=row.source_evidence_hash,
            content_hash=row.content_hash,
        )

    @staticmethod
    def _order_event_to_dict(item: BrokerOrderEventEvidence) -> dict[str, object]:
        return {
            "event_ref": item.event_ref,
            "event_type": item.event_type,
            "status": item.status,
            "occurred_at": item.occurred_at.isoformat(),
        }

    @staticmethod
    def _order_event_from_dict(item: dict[str, Any]) -> BrokerOrderEventEvidence:
        return BrokerOrderEventEvidence(
            event_ref=str(item["event_ref"]),
            event_type=str(item["event_type"]),
            status=str(item.get("status", "")),
            occurred_at=datetime.fromisoformat(str(item["occurred_at"])),
        )

    @staticmethod
    def _fill_to_dict(item: BrokerFillEvidence) -> dict[str, object]:
        return {
            "fill_ref": item.fill_ref,
            "quantity": str(item.quantity),
            "price": str(item.price),
            "fee": str(item.fee),
            "occurred_at": item.occurred_at.isoformat(),
        }

    @staticmethod
    def _fill_from_dict(item: dict[str, Any]) -> BrokerFillEvidence:
        return BrokerFillEvidence(
            fill_ref=str(item["fill_ref"]),
            quantity=Decimal(str(item["quantity"])),
            price=Decimal(str(item["price"])),
            fee=Decimal(str(item["fee"])),
            occurred_at=datetime.fromisoformat(str(item["occurred_at"])),
        )

    @staticmethod
    def _deviation_to_dict(item: ConstraintExecutionDeviation) -> dict[str, str]:
        return {
            "rule_code": item.rule_code,
            "expected_value": item.expected_value,
            "actual_value": item.actual_value,
            "reason": item.reason,
        }

    @staticmethod
    def _deviation_from_dict(item: dict[str, Any]) -> ConstraintExecutionDeviation:
        return ConstraintExecutionDeviation(
            rule_code=str(item["rule_code"]),
            expected_value=str(item["expected_value"]),
            actual_value=str(item["actual_value"]),
            reason=str(item["reason"]),
        )


__all__ = [
    "DjangoCanonicalPortfolioSnapshotRepository",
    "DjangoPortfolioExecutionFeedbackRepository",
]
