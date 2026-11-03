"""Read-only baseline policy port used by simulation portfolio risk composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.risk_center.domain.portfolio_baseline_risk import (
    PortfolioBaselineAssessment,
    PortfolioBaselinePolicy,
    assess_portfolio_baseline,
    intersect_native_account_limits,
    portfolio_risk_subject_is_excluded,
)


@dataclass(frozen=True, slots=True)
class PortfolioBaselinePolicyReadResult:
    """An existing explicit policy or stable reasons why it cannot be qualified."""

    policy: PortfolioBaselinePolicy | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Ensure the read result cannot claim both success and a blocking reason."""

        if self.policy is not None and type(self.policy) is not PortfolioBaselinePolicy:
            raise TypeError("policy must be PortfolioBaselinePolicy or None")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str
            or not reason
            or reason.strip() != reason
            or any(character.isspace() for character in reason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must be stable nonempty tokens")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes cannot contain duplicates")
        if (self.policy is None) == (not self.reason_codes):
            raise ValueError("a policy read must contain either a policy or blocking reasons")


class PortfolioBaselinePolicyReader(Protocol):
    """Read existing records without creating default floor/template rows."""

    def read_baseline_policy(
        self, *, account_id: int, as_of: datetime
    ) -> PortfolioBaselinePolicyReadResult:
        """Return only an exact, active, explicitly persisted baseline policy."""
        ...


__all__ = [
    "PortfolioBaselineAssessment",
    "PortfolioBaselinePolicy",
    "PortfolioBaselinePolicyReadResult",
    "PortfolioBaselinePolicyReader",
    "assess_portfolio_baseline",
    "intersect_native_account_limits",
    "portfolio_risk_subject_is_excluded",
]
