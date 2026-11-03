"""Application entry point for simulated portfolio capacity assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from apps.risk_center.domain.portfolio_capacity import (
    CapacityParticipationPolicy,
    CapacityUsageSnapshot,
    CapacityWindowObservation,
    PortfolioCapacityDecision,
    evaluate_portfolio_capacity,
)


@dataclass(frozen=True, slots=True)
class PortfolioCapacityAssessmentRequest:
    """Complete typed inputs assembled from one locked account/resource snapshot."""

    observation: CapacityWindowObservation
    policy: CapacityParticipationPolicy | None
    usage: CapacityUsageSnapshot
    requested_purpose: str
    business_date: date
    as_of: datetime


class PortfolioCapacityRiskPort(Protocol):
    """Narrow application port for plan and execution risk checks."""

    def assess_capacity(
        self,
        request: PortfolioCapacityAssessmentRequest,
    ) -> PortfolioCapacityDecision:
        """Return the source and resource bounded per-session capacity decision."""


class PortfolioCapacityAssessmentService:
    """Application service that delegates to the pure capacity domain rule."""

    def assess_capacity(
        self,
        request: PortfolioCapacityAssessmentRequest,
    ) -> PortfolioCapacityDecision:
        """Assess one requested security against its current-session resource snapshot."""

        return evaluate_portfolio_capacity(
            observation=request.observation,
            policy=request.policy,
            usage=request.usage,
            requested_purpose=request.requested_purpose,
            business_date=request.business_date,
            as_of=request.as_of,
        )
