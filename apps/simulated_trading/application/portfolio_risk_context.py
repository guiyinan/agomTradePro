"""One immutable consumer context for risk reports, execution and pressure runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from apps.risk_center.application.portfolio_baseline_risk import PortfolioBaselinePolicyReadResult
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetsReadResult
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyBundle
from apps.risk_center.application.portfolio_risk_snapshot import (
    AccountSnapshot,
    PortfolioRiskAssessmentResult,
    ProposedOrder,
)
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReadResult,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    AccountSnapshotReadResult,
)


class PortfolioRiskClock(Protocol):
    """Supply a server-owned clock, never a user-supplied source timestamp."""

    def now(self) -> datetime:
        """Return the actual aware service clock."""
        ...


@dataclass(frozen=True, slots=True)
class PreparedPortfolioRisk:
    """Exact resources, source and policy instances used for one explained result."""

    actor_user_id: int
    snapshot: AccountSnapshot
    resources: AccountSnapshotReadResult
    proposals: tuple[ProposedOrder, ...]
    policy: PortfolioRiskPolicyBundle | None
    baseline_source: PortfolioBaselinePolicyReadResult
    assets: PortfolioRiskAssetsReadResult
    calendar: PortfolioRiskCalendarReadResult
    assessment: PortfolioRiskAssessmentResult
    report: PortfolioRiskReportPayload
    as_of: datetime
    business_date: date
    identity_bindings: tuple[PortfolioRiskIdentityBinding, ...]
    policy_binding_sha256: str | None
    native_limits_sha256: str
    input_snapshot_json: str
    capacity_requested_purpose: str


class PortfolioRiskPressureRunner(Protocol):
    """Explicitly retain one existing Scenario run using this frozen context."""

    def run(
        self, *, prepared: PreparedPortfolioRisk, scenario_identifier: str, idempotency_key: str
    ) -> PortfolioRiskReportPayload:
        """Run approved hypothetical pressure without creating or releasing orders."""
        ...
