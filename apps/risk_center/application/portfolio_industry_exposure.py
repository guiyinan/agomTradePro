"""Public application ports and use case for simulated portfolio industry risk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from apps.risk_center.domain.portfolio_exposure import (
    IndustryExposurePolicy,
    PortfolioExposureProjection,
    PortfolioIndustryExposureAssessment,
    assess_portfolio_industry_exposure,
)
from core.exceptions import InsufficientDataError


@dataclass(frozen=True, slots=True)
class PortfolioIndustryExposureQuery:
    """Owner-scoped source lookup at an explicitly supplied date and cutoff."""

    account_id: int
    portfolio_snapshot_id: str
    as_of: datetime
    business_date: date

    def __post_init__(self) -> None:
        """Reject ambiguous owner, snapshot, and cutoff values at the app boundary."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if (
            type(self.portfolio_snapshot_id) is not str
            or not self.portfolio_snapshot_id
            or self.portfolio_snapshot_id.strip() != self.portfolio_snapshot_id
        ):
            raise ValueError("portfolio_snapshot_id must be a nonempty canonical string")
        if type(self.as_of) is not datetime or self.as_of.tzinfo is None:
            raise ValueError("as_of must be a timezone-aware datetime")
        if self.as_of.utcoffset() is None:
            raise ValueError("as_of must have a concrete UTC offset")
        if type(self.business_date) is not date:
            raise TypeError("business_date must be an explicit date")


class PortfolioIndustryExposureProjectionReader(Protocol):
    """Read port for portfolio projections owned by the Portfolio context."""

    def read_projection(
        self,
        *,
        account_id: int,
        portfolio_snapshot_id: str,
        as_of: datetime,
        business_date: date,
    ) -> PortfolioExposureProjection | None:
        """Return one exact portfolio projection without substituting a newer snapshot."""
        ...


class IndustryExposurePolicyReader(Protocol):
    """Read port for the unique versioned industry-risk policy at a cutoff."""

    def read_policy(
        self,
        *,
        account_id: int,
        as_of: datetime,
    ) -> IndustryExposurePolicy | None:
        """Return the configured policy or None when no policy covers this cutoff."""
        ...


class PortfolioIndustryExposureInputUnavailableError(InsufficientDataError):
    """A missing/corrupt source input prevents a risk assessment from being formed."""

    def __init__(self, reason_codes: tuple[str, ...]) -> None:
        """Preserve stable source-gate reasons for the caller's blocked result."""

        if type(reason_codes) is not tuple or not reason_codes:
            raise ValueError("reason_codes must be a nonempty tuple")
        if any(type(reason) is not str or not reason for reason in reason_codes):
            raise ValueError("reason_codes must contain nonempty strings")
        self.reason_codes = reason_codes
        super().__init__(", ".join(reason_codes))


class AssessPortfolioIndustryExposureUseCase:
    """Resolve exact inputs, then run the pure industry/ETF risk calculation."""

    def __init__(
        self,
        *,
        projection_reader: PortfolioIndustryExposureProjectionReader,
        policy_reader: IndustryExposurePolicyReader,
    ) -> None:
        """Inject public read ports owned by the portfolio and policy composition roots."""

        self._projection_reader = projection_reader
        self._policy_reader = policy_reader

    def execute(
        self,
        query: PortfolioIndustryExposureQuery,
    ) -> PortfolioIndustryExposureAssessment:
        """Return conservative exposure bounds or a typed unavailable-input error."""

        policy = self._policy_reader.read_policy(
            account_id=query.account_id,
            as_of=query.as_of,
        )
        if policy is None:
            raise PortfolioIndustryExposureInputUnavailableError(
                ("INDUSTRY_RISK_POLICY_NOT_FOUND",)
            )
        projection = self._projection_reader.read_projection(
            account_id=query.account_id,
            portfolio_snapshot_id=query.portfolio_snapshot_id,
            as_of=query.as_of,
            business_date=query.business_date,
        )
        if projection is None:
            raise PortfolioIndustryExposureInputUnavailableError(
                ("PORTFOLIO_EXPOSURE_PROJECTION_NOT_FOUND",)
            )
        if (
            projection.portfolio_snapshot_id != query.portfolio_snapshot_id
            or projection.as_of != query.as_of
            or projection.business_date != query.business_date
        ):
            raise PortfolioIndustryExposureInputUnavailableError(
                ("PORTFOLIO_EXPOSURE_PROJECTION_SCOPE_MISMATCH",)
            )
        return assess_portfolio_industry_exposure(policy=policy, projection=projection)


__all__: tuple[str, ...] = (
    "AssessPortfolioIndustryExposureUseCase",
    "IndustryExposurePolicyReader",
    "PortfolioIndustryExposureInputUnavailableError",
    "PortfolioIndustryExposureProjectionReader",
    "PortfolioIndustryExposureQuery",
)
