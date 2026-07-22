"""Persistence for canonical portfolio transition plans."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.portfolio.domain.entities import ConstraintDecision, OrderDraft, TransitionPlan
from core.integration.research_integrity_registry import get_decision_snapshot

from .models import PortfolioTransitionPlanModel
from .policy_models import PortfolioPlanningPolicyModel


class PortfolioPlanningPolicyRepository:
    """Read the single active, versioned planning policy."""

    def get_active_config(self) -> dict[str, object]:
        """Return active thresholds or fail closed when none is configured."""

        policy = PortfolioPlanningPolicyModel._default_manager.filter(status="active").first()
        if policy is None:
            raise ValueError("no active portfolio planning policy is configured")
        return {
            "policy_version": policy.version,
            "buy_lot_size": policy.buy_lot_size,
            "fee_rate": policy.fee_rate,
            "slippage_rate": policy.slippage_rate,
            "min_rebalance_value": policy.min_rebalance_value,
            "max_asset_weight": policy.max_asset_weight,
            "max_volume_participation": policy.max_volume_participation,
        }


class PortfolioTransitionPlanRepository:
    """Store immutable plan payloads and controlled lifecycle transitions."""

    @transaction.atomic
    def save(self, plan: TransitionPlan) -> TransitionPlan:
        """Persist a plan idempotently."""

        if settings.DECISION_SNAPSHOT_REQUIRED:
            snapshot = get_decision_snapshot(plan.decision_snapshot_id)
            if snapshot is None:
                raise ValueError("decision input snapshot not found")
            snapshot.verify()
        orders = [self._order_to_dict(order) for order in plan.orders]
        constraints = [decision.__dict__ for decision in plan.constraints]
        payload = {
            "account_id": plan.account_id,
            "decision_snapshot_id": plan.decision_snapshot_id,
            "portfolio_snapshot_id": plan.portfolio_snapshot_id,
            "target_portfolio_id": plan.target_portfolio_id,
            "as_of_time": plan.as_of_time.isoformat(),
            "expires_at": plan.expires_at.isoformat(),
            "orders": orders,
            "constraints": constraints,
            "cash_before": str(plan.cash_before),
            "cash_after": str(plan.cash_after),
            "planning_policy_version": plan.metadata.get("planning_policy_version", ""),
            "version": plan.version,
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        existing = PortfolioTransitionPlanModel._default_manager.filter(
            idempotency_key=plan.idempotency_key
        ).first()
        if existing:
            if existing.immutable_payload_hash != payload_hash:
                raise ValueError("idempotency key was already used for a different plan")
            return self._to_domain(existing)
        PortfolioTransitionPlanModel._default_manager.create(
            plan_id=plan.plan_id,
            account_id=plan.account_id,
            source_recommendation_ids=[],
            current_positions_snapshot=[],
            target_positions_snapshot=[],
            orders=orders,
            risk_contract={
                "constraints": constraints,
                "planning_policy_version": plan.metadata.get("planning_policy_version", ""),
            },
            summary={"cash_before": str(plan.cash_before), "cash_after": str(plan.cash_after)},
            status=plan.status,
            as_of=plan.as_of_time,
            idempotency_key=plan.idempotency_key,
            decision_snapshot_id=plan.decision_snapshot_id,
            portfolio_snapshot_id=plan.portfolio_snapshot_id,
            target_portfolio_id=plan.target_portfolio_id,
            expires_at=plan.expires_at,
            immutable_payload_hash=payload_hash,
            plan_version=plan.version,
        )
        return plan

    def get(self, plan_id: str) -> TransitionPlan | None:
        row = PortfolioTransitionPlanModel._default_manager.filter(plan_id=plan_id).first()
        return self._to_domain(row) if row else None

    def get_by_idempotency_key(self, idempotency_key: str) -> TransitionPlan | None:
        row = PortfolioTransitionPlanModel._default_manager.filter(
            idempotency_key=idempotency_key
        ).first()
        return self._to_domain(row) if row else None

    @transaction.atomic
    def approve(self, plan_id: str, decision_snapshot_id: str) -> TransitionPlan:
        """Approve only an unexpired plan bound to the same decision snapshot."""

        row = PortfolioTransitionPlanModel._default_manager.select_for_update().get(plan_id=plan_id)
        if row.decision_snapshot_id != decision_snapshot_id:
            raise ValueError("decision snapshot changed; rebuild the transition plan")
        if row.expires_at is None or row.expires_at <= timezone.now():
            raise ValueError("transition plan has expired")
        if row.status not in {"DRAFT", "READY_FOR_APPROVAL", "APPROVAL_PENDING"}:
            raise ValueError(f"cannot approve plan in status {row.status}")
        row.status = "APPROVED"
        row.approved_at = timezone.now()
        row.save(update_fields=["status", "approved_at", "updated_at"])
        return self._to_domain(row)

    @classmethod
    def _to_domain(cls, row: PortfolioTransitionPlanModel) -> TransitionPlan:
        orders = tuple(cls._order_from_dict(item) for item in (row.orders or []))
        constraints = tuple(
            ConstraintDecision(**item) for item in (row.risk_contract or {}).get("constraints", [])
        )
        return TransitionPlan(
            plan_id=row.plan_id,
            idempotency_key=row.idempotency_key or row.plan_id,
            account_id=row.account_id,
            decision_snapshot_id=row.decision_snapshot_id,
            portfolio_snapshot_id=row.portfolio_snapshot_id,
            target_portfolio_id=row.target_portfolio_id,
            as_of_time=row.as_of,
            expires_at=row.expires_at or row.as_of,
            orders=orders,
            constraints=constraints,
            cash_before=Decimal(str((row.summary or {}).get("cash_before", "0"))),
            cash_after=Decimal(str((row.summary or {}).get("cash_after", "0"))),
            status=row.status,
            version=row.plan_version,
            metadata={
                "planning_policy_version": (row.risk_contract or {}).get(
                    "planning_policy_version", ""
                )
            },
        )

    @staticmethod
    def _order_to_dict(order: OrderDraft) -> dict:
        return {
            "asset_code": order.asset_code,
            "side": order.side,
            "quantity": order.quantity,
            "reference_price": str(order.reference_price),
            "estimated_fee": str(order.estimated_fee),
            "status": order.status,
            "remaining_quantity": order.remaining_quantity,
            "constraints": [item.__dict__ for item in order.constraints],
        }

    @staticmethod
    def _order_from_dict(item: dict) -> OrderDraft:
        return OrderDraft(
            asset_code=str(item["asset_code"]),
            side=str(item["side"]),
            quantity=int(item["quantity"]),
            reference_price=Decimal(str(item["reference_price"])),
            estimated_fee=Decimal(str(item["estimated_fee"])),
            status=str(item.get("status", "draft")),
            remaining_quantity=int(item.get("remaining_quantity", 0)),
            constraints=tuple(ConstraintDecision(**entry) for entry in item.get("constraints", [])),
        )
