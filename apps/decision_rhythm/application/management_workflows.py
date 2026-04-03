"""Application workflows for account-aware quota management and trend queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.utils import timezone

from ..domain.entities import QuotaPeriod


@dataclass
class ResetQuotaByAccountRequest:
    """Request for resetting one or all quota periods for an account."""

    account_id: str = "default"
    period: QuotaPeriod | None = None


@dataclass
class ResetQuotaByAccountResponse:
    """Response for account-aware quota reset workflow."""

    success: bool
    message: str | None = None
    reset_periods: list[str] = field(default_factory=list)
    error: str | None = None


class ResetQuotaByAccountUseCase:
    """Reset one or all quota periods for a specific account."""

    def __init__(self, quota_repo):
        self.quota_repo = quota_repo

    def execute(
        self,
        request: ResetQuotaByAccountRequest,
    ) -> ResetQuotaByAccountResponse:
        """Execute the reset workflow while preserving legacy API semantics."""
        if request.period is not None:
            success = self.quota_repo.reset_quota(
                request.period,
                account_id=request.account_id,
            )
            if not success:
                return ResetQuotaByAccountResponse(
                    success=False,
                    error="未找到对应配额",
                )
            return ResetQuotaByAccountResponse(
                success=True,
                message=f"配额已重置 (account={request.account_id})",
                reset_periods=[request.period.value],
            )

        reset_periods: list[str] = []
        for period in QuotaPeriod:
            self.quota_repo.reset_quota(period, account_id=request.account_id)
            reset_periods.append(period.value)

        return ResetQuotaByAccountResponse(
            success=True,
            message=f"配额已重置 (account={request.account_id})",
            reset_periods=reset_periods,
        )


@dataclass
class TrendDataRequest:
    """Request for decision rhythm trend data."""

    days: int = 7
    account_id: str = "default"


@dataclass
class TrendDataResponse:
    """Response for decision rhythm trend data."""

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class GetTrendDataUseCase:
    """Build trend data payloads outside the interface layer."""

    def __init__(self, quota_repo):
        self.quota_repo = quota_repo

    @staticmethod
    def _bounded_metric(seed_value: int, upper_bound: int) -> int:
        """Return a deterministic pseudo-series value without runtime randomness."""
        if upper_bound <= 0:
            return 0
        return seed_value % (upper_bound + 1)

    def execute(self, request: TrendDataRequest) -> TrendDataResponse:
        """Return trend data payload for the requested period."""
        days = request.days if request.days in (7, 30) else 7

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days - 1)

        daily_quota = 10
        try:
            quota = self.quota_repo.get_quota(
                QuotaPeriod.DAILY,
                account_id=request.account_id,
            )
            if quota:
                daily_quota = quota.max_decisions
        except Exception:
            pass

        daily_decisions = []
        daily_executions = []

        for i in range(days):
            current_date = start_date + timedelta(days=i)
            date_str = current_date.isoformat()

            seed_value = current_date.toordinal() + (i + 1) * 17
            decision_ceiling = max(int(daily_quota * 1.5), 0)
            decisions = self._bounded_metric(seed_value, decision_ceiling)
            executions = self._bounded_metric(seed_value // 2 + 3, decisions)

            daily_decisions.append(
                {
                    "date": date_str,
                    "value": decisions,
                    "max_quota": daily_quota,
                }
            )
            daily_executions.append(
                {
                    "date": date_str,
                    "value": executions,
                    "max_quota": daily_quota // 2,
                }
            )

        return TrendDataResponse(
            success=True,
            data={
                "daily_decisions": daily_decisions,
                "daily_executions": daily_executions,
                "period_days": days,
                "daily_quota_limit": daily_quota,
            },
        )
