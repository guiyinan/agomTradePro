"""Canonical Portfolio plans cannot become execution handoffs without Evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.use_cases import SubmitApprovedPlanUseCase
from apps.portfolio.domain.entities import TransitionPlan

NOW = datetime.now(UTC)


class _Repository:
    def __init__(self, plan: TransitionPlan | None) -> None:
        self.plan = plan

    def get(self, plan_id: str) -> TransitionPlan | None:
        return self.plan if self.plan is not None and self.plan.plan_id == plan_id else None


def _plan() -> TransitionPlan:
    return TransitionPlan(
        plan_id="plan-1",
        idempotency_key="idem-1",
        account_id="7",
        decision_snapshot_id="decision-1",
        portfolio_snapshot_id="portfolio-1",
        target_portfolio_id="target-1",
        as_of_time=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        orders=(),
        constraints=(),
        cash_before=Decimal("1000"),
        cash_after=Decimal("1000"),
        status="APPROVED",
        metadata={"planning_policy_version": "policy-v1"},
    )


def test_approved_plan_is_blocked_without_integrated_evidence() -> None:
    use_case = SubmitApprovedPlanUseCase(_Repository(_plan()))

    with pytest.raises(ValueError, match="Evidence is integrated"):
        use_case.execute("plan-1")


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        (None, "not found"),
        (replace(_plan(), status="DRAFT"), "only approved"),
        (replace(_plan(), expires_at=NOW - timedelta(seconds=1)), "expired"),
    ],
)
def test_submit_preserves_existing_identity_status_and_expiry_checks(
    plan: TransitionPlan | None, message: str
) -> None:
    use_case = SubmitApprovedPlanUseCase(_Repository(plan))

    with pytest.raises(ValueError, match=message):
        use_case.execute("plan-1")
