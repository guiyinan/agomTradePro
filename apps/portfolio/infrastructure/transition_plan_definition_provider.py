"""Exact canonical transition-plan definition provider."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.application.transition_plan_inactive_approval import TransitionPlanDefinition
from apps.portfolio.infrastructure.repositories import PortfolioTransitionPlanRepository
from apps.portfolio.infrastructure.transition_models import PortfolioTransitionPlanModel
from core.integration.transition_plan_contracts import require_canonical_transition_plan_family


class DjangoExactTransitionPlanDefinitionProvider:
    """Restore one exact approved canonical plan at a point-in-time cutoff."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        """Return only one exact, approved, knowable and unexpired plan."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if type(plan_id) is not str or not plan_id or plan_id.strip() != plan_id:
            raise ValueError("plan_id must be canonical")
        if type(plan_version) is not int or plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        row = (
            PortfolioTransitionPlanModel._default_manager.using(self._using)
            .filter(
                plan_id=plan_id,
                plan_version=plan_version,
                status="APPROVED",
                approved_at__isnull=False,
                approved_at__lte=as_of,
                created_at__lte=as_of,
                expires_at__gt=as_of,
            )
            .first()
        )
        if row is None:
            return None
        require_canonical_transition_plan_family(row.plan_contract_family)
        plan = PortfolioTransitionPlanRepository._verified_to_domain(row)
        return TransitionPlanDefinition(
            plan=plan,
            content_hash=str(row.immutable_payload_hash),
            recorded_at=row.approved_at,
        )


__all__ = ["DjangoExactTransitionPlanDefinitionProvider"]
