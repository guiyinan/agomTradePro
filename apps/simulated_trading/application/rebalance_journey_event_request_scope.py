"""Request-scoped account identity passed to event refresh and proof readers."""

from __future__ import annotations

from dataclasses import dataclass

from apps.portfolio.application.transition_plan_lifecycle import TransitionPlanRevisionRequest
from apps.risk_center.application.portfolio_risk_snapshot import AccountSnapshot
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable


@dataclass(frozen=True, slots=True)
class RebalanceJourneyEventRequestScope:
    """Bind the authenticated actor to one account and its verified owner."""

    actor_user_id: int
    account_id: int
    owner_user_id: int

    def __post_init__(self) -> None:
        """Reject aliases, booleans and non-positive identity values."""

        if any(
            type(value) is not int or value <= 0
            for value in (self.actor_user_id, self.account_id, self.owner_user_id)
        ):
            raise ValueError("event request scope identities must be positive exact integers")


def build_rebalance_journey_event_request_scope(
    request: TransitionPlanRevisionRequest,
    prepared: PreparedPortfolioRisk,
) -> RebalanceJourneyEventRequestScope:
    """Bind request IDs only to an authorized, matching account resource snapshot."""

    if (
        type(request) is not TransitionPlanRevisionRequest
        or type(prepared) is not PreparedPortfolioRisk
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REQUEST_SCOPE_INVALID")
    account_scope = prepared.resources.scope
    resource_snapshot = prepared.resources.snapshot
    if (
        prepared.actor_user_id != request.actor_user_id
        or prepared.snapshot.account_id != request.account_id
        or account_scope is None
        or not account_scope.can_write
        or account_scope.owner_user_id != prepared.snapshot.owner_user_id
        or prepared.resources.reason_codes
        or type(resource_snapshot) is not AccountSnapshot
        or resource_snapshot.account_id != request.account_id
        or resource_snapshot.owner_user_id != account_scope.owner_user_id
        or resource_snapshot.snapshot_id != prepared.snapshot.snapshot_id
        or resource_snapshot.read_at != prepared.snapshot.read_at
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REQUEST_SCOPE_INVALID")
    return RebalanceJourneyEventRequestScope(
        actor_user_id=request.actor_user_id,
        account_id=request.account_id,
        owner_user_id=account_scope.owner_user_id,
    )


__all__ = (
    "RebalanceJourneyEventRequestScope",
    "build_rebalance_journey_event_request_scope",
)
