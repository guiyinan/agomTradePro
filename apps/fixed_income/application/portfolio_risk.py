"""Application boundary for R5 fixed-income portfolio risk research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.fixed_income.domain.portfolio_risk import (
    FixedIncomePortfolioRiskAssessment,
    FixedIncomeRiskBudgetPolicy,
    PortfolioRiskBlocker,
    PortfolioRiskBlockerCode,
    PortfolioRiskInputBundle,
    blocked_fixed_income_portfolio_risk_assessment,
    evaluate_fixed_income_portfolio_risk,
)


class PortfolioRiskInputBundleProvider(Protocol):
    """Read one canonical, owner-assembled portfolio risk bundle."""

    def get_bundle(
        self,
        bundle_id: str,
        *,
        evaluated_at: datetime,
    ) -> PortfolioRiskInputBundle | None:
        """Return the exact bundle or ``None`` without synthesizing inputs."""


class FixedIncomeRiskBudgetPolicyProvider(Protocol):
    """Read one exact Research-governed risk budget policy version."""

    def get_policy(
        self,
        policy_version: str,
        *,
        evaluated_at: datetime,
    ) -> FixedIncomeRiskBudgetPolicy | None:
        """Return the exact policy or ``None`` without default thresholds."""


@dataclass(frozen=True)
class AssessFixedIncomePortfolioRiskCommand:
    """Request one evidence-bound R5 portfolio risk assessment."""

    bundle_id: str
    budget_policy_version: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not self.bundle_id.strip():
            raise ValueError("bundle_id cannot be blank")
        if not self.budget_policy_version.strip():
            raise ValueError("budget_policy_version cannot be blank")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")


class AssessFixedIncomePortfolioRisk:
    """Collect canonical evidence and run the pure fail-closed assessment."""

    def __init__(
        self,
        *,
        bundle_provider: PortfolioRiskInputBundleProvider,
        policy_provider: FixedIncomeRiskBudgetPolicyProvider,
    ) -> None:
        self._bundle_provider = bundle_provider
        self._policy_provider = policy_provider

    def execute(
        self,
        command: AssessFixedIncomePortfolioRiskCommand,
    ) -> FixedIncomePortfolioRiskAssessment:
        """Assess only provider evidence; missing bundle or policy stays blocked."""

        bundle = self._bundle_provider.get_bundle(
            command.bundle_id,
            evaluated_at=command.evaluated_at,
        )
        if bundle is None:
            return blocked_fixed_income_portfolio_risk_assessment(
                bundle_id=command.bundle_id,
                policy_version=command.budget_policy_version,
                evaluated_at=command.evaluated_at,
                blocker=PortfolioRiskBlocker(
                    code=PortfolioRiskBlockerCode.CANONICAL_BUNDLE_MISSING,
                    detail="canonical fixed-income portfolio risk bundle is unavailable",
                ),
            )
        policy = self._policy_provider.get_policy(
            command.budget_policy_version,
            evaluated_at=command.evaluated_at,
        )
        if policy is None:
            return blocked_fixed_income_portfolio_risk_assessment(
                bundle_id=command.bundle_id,
                policy_version=command.budget_policy_version,
                evaluated_at=command.evaluated_at,
                input_hash=bundle.input_hash,
                portfolio_snapshot_id=bundle.portfolio_snapshot_id,
                portfolio_snapshot_hash=bundle.portfolio_snapshot_hash,
                policy_hash=bundle.budget_policy_hash,
                blocker=PortfolioRiskBlocker(
                    code=PortfolioRiskBlockerCode.BUDGET_POLICY_MISSING,
                    detail="versioned fixed-income risk budget policy is unavailable",
                ),
            )
        return evaluate_fixed_income_portfolio_risk(
            bundle,
            policy=policy,
            evaluated_at=command.evaluated_at,
        )


__all__ = [
    "AssessFixedIncomePortfolioRisk",
    "AssessFixedIncomePortfolioRiskCommand",
    "FixedIncomeRiskBudgetPolicyProvider",
    "PortfolioRiskInputBundleProvider",
]
