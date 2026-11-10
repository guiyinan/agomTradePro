"""Application contract for refreshing official event evidence before plan assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from core.exceptions import AgomTradeProException

_POLICY_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_MAXIMUM_OWNER_LEASE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class RebalanceJourneyOfficialEventRefreshReceipt:
    """A non-proof acknowledgement binding refresh scope and active evidence provenance."""

    request_scope: RebalanceJourneyEventRequestScope
    asset_pairs: tuple[tuple[str, str], ...]
    source_id: str
    start_on: date
    end_on: date
    policy_fingerprint: str
    lease_policy: TransitionPlanEventCoverageLeasePolicy

    def __post_init__(self) -> None:
        """Reject malformed scope, fingerprint, and unbounded effective lease values."""

        if type(self.request_scope) is not RebalanceJourneyEventRequestScope:
            raise ValueError("refresh receipt request scope is invalid")
        if (
            type(self.asset_pairs) is not tuple
            or not self.asset_pairs
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or any(
                    type(value) is not str or not value or value.strip() != value for value in pair
                )
                for pair in self.asset_pairs
            )
            or len(self.asset_pairs) != len(set(self.asset_pairs))
        ):
            raise ValueError("refresh receipt must contain unique exact asset/security pairs")
        if (
            type(self.source_id) is not str
            or not self.source_id
            or self.source_id.strip() != self.source_id
        ):
            raise ValueError("refresh receipt source identity is invalid")
        if (
            type(self.start_on) is not date
            or type(self.start_on) is datetime
            or type(self.end_on) is not date
            or type(self.end_on) is datetime
            or self.start_on > self.end_on
        ):
            raise ValueError("refresh receipt window is invalid")
        if (
            type(self.policy_fingerprint) is not str
            or _POLICY_FINGERPRINT.fullmatch(self.policy_fingerprint) is None
            or type(self.lease_policy) is not TransitionPlanEventCoverageLeasePolicy
            or self.lease_policy.policy_version != self.policy_fingerprint
            or self.lease_policy.maximum_ttl > _MAXIMUM_OWNER_LEASE
        ):
            raise ValueError("refresh receipt policy fingerprint or lease policy is invalid")


class RebalanceJourneyOfficialEventRefresher(Protocol):
    """Refresh official disclosure captures for one exact set of portfolio identities."""

    def refresh(
        self,
        *,
        asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
    ) -> RebalanceJourneyOfficialEventRefreshReceipt:
        """Return a non-proof receipt; persisted proof is always read separately."""
        ...


def refresh_official_event_identities(
    refresher: RebalanceJourneyOfficialEventRefresher,
    *,
    asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
    request_scope: RebalanceJourneyEventRequestScope,
    as_of: datetime,
) -> RebalanceJourneyOfficialEventRefreshReceipt:
    """Run the injected capture and require an exact scoped receipt, never a proof claim."""

    if (
        type(request_scope) is not RebalanceJourneyEventRequestScope
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or type(asset_identities) is not tuple
        or not asset_identities
        or any(type(identity) is not PortfolioRiskAssetIdentity for identity in asset_identities)
        or any(
            type(identity.security_id) is not str or not identity.security_id
            for identity in asset_identities
        )
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REQUEST_SCOPE_INVALID")
    try:
        receipt = refresher.refresh(
            asset_identities=asset_identities,
            request_scope=request_scope,
            as_of=as_of,
        )
    except RebalanceJourneyUnavailable:
        raise
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_FAILED") from error
    expected_pairs = tuple(
        sorted((identity.asset_code, identity.security_id or "") for identity in asset_identities)
    )
    if (
        type(receipt) is not RebalanceJourneyOfficialEventRefreshReceipt
        or receipt.request_scope != request_scope
        or receipt.asset_pairs != expected_pairs
        or receipt.source_id != "szse_official"
        or receipt.lease_policy.policy_version != receipt.policy_fingerprint
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_INCOMPLETE")
    return receipt


__all__ = (
    "RebalanceJourneyOfficialEventRefresher",
    "RebalanceJourneyOfficialEventRefreshReceipt",
    "refresh_official_event_identities",
)
