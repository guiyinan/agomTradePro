"""Portfolio construction and approval use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from apps.portfolio.domain.entities import PortfolioSnapshot, TargetPortfolio, TransitionPlan
from apps.portfolio.domain.services import build_transition_plan


class TransitionPlanGateway(Protocol):
    def save(self, plan: TransitionPlan) -> TransitionPlan: ...
    def get(self, plan_id: str) -> TransitionPlan | None: ...
    def get_by_idempotency_key(self, idempotency_key: str) -> TransitionPlan | None: ...
    def approve(self, plan_id: str, decision_snapshot_id: str) -> TransitionPlan: ...


class PlanningPolicyGateway(Protocol):
    """Read the active database-backed planning thresholds."""

    def get_active_config(self) -> dict[str, object]: ...


class BuildTransitionPlanUseCase:
    """Build one deterministic and idempotent transition plan."""

    def __init__(
        self,
        repository: TransitionPlanGateway,
        policy_repository: PlanningPolicyGateway,
    ):
        self._repository = repository
        self._policy_repository = policy_repository

    def execute(
        self,
        *,
        idempotency_key: str,
        target: TargetPortfolio,
        current: PortfolioSnapshot,
        prices: dict[str, Decimal],
        market_facts: dict[str, dict[str, Any]],
        expires_at: datetime,
    ) -> TransitionPlan:
        config = self._policy_repository.get_active_config()
        plan = build_transition_plan(
            idempotency_key=idempotency_key,
            target=target,
            current=current,
            prices=prices,
            market_facts=market_facts,
            config=config,
            expires_at=expires_at,
        )
        return self._repository.save(plan)


class ValidateTransitionPlanUseCase:
    """Validate plan freshness and decision binding before approval."""

    def __init__(self, repository: TransitionPlanGateway):
        self._repository = repository

    def execute(self, plan_id: str, decision_snapshot_id: str) -> TransitionPlan:
        return self._repository.approve(plan_id, decision_snapshot_id)


class SubmitApprovedPlanUseCase:
    """Return an immutable approved execution handoff."""

    def __init__(self, repository: TransitionPlanGateway):
        self._repository = repository

    def execute(self, plan_id: str) -> TransitionPlan:
        plan = self._repository.get(plan_id)
        if plan is None:
            raise ValueError("transition plan not found")
        if plan.status != "APPROVED":
            raise ValueError("only approved plans may be submitted for execution")
        if plan.expires_at <= datetime.now(UTC):
            raise ValueError("approved transition plan has expired")
        return plan
