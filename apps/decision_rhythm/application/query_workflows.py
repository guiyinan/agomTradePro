"""Application query workflows for decision rhythm read models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..domain.entities import CooldownPeriod, DecisionRequest, DecisionQuota, QuotaPeriod


class QuotaRepositoryProtocol(Protocol):
    """Protocol for quota read operations."""

    def get_all_quotas(
        self,
        period: QuotaPeriod | None = None,
        account_id: str | None = None,
    ) -> list[DecisionQuota]:
        """Return quota entities filtered by period and account."""

    def get_quota(
        self,
        period: QuotaPeriod,
        account_id: str = "default",
    ) -> DecisionQuota | None:
        """Return a single quota entity for the given period and account."""


class CooldownRepositoryProtocol(Protocol):
    """Protocol for cooldown read operations."""

    def get_all_active(self) -> list[CooldownPeriod]:
        """Return active cooldown entries."""

    def get_active_cooldown(
        self,
        asset_code: str,
        direction: str | None = None,
    ) -> CooldownPeriod | None:
        """Return the active cooldown for an asset when present."""

    def get_remaining_hours(
        self,
        asset_code: str,
        direction: str | None = None,
    ) -> float:
        """Return remaining cooldown hours for an asset."""


class DecisionRequestRepositoryProtocol(Protocol):
    """Protocol for decision request read operations."""

    def get_recent(
        self,
        days: int = 30,
        asset_code: str | None = None,
    ) -> list[DecisionRequest]:
        """Return recent requests filtered by time window and asset."""

    def get_by_id(self, request_id: str) -> DecisionRequest | None:
        """Return a request by its identifier."""

    def get_statistics(self, days: int = 30) -> dict[str, Any]:
        """Return request statistics for the selected window."""


@dataclass(frozen=True)
class ListDecisionQuotasRequest:
    """Request for listing decision quotas."""

    period: QuotaPeriod | None = None
    account_id: str | None = None


@dataclass(frozen=True)
class GetDecisionQuotaByPeriodRequest:
    """Request for fetching one quota by period."""

    period: QuotaPeriod
    account_id: str = "default"


@dataclass(frozen=True)
class GetActiveCooldownByAssetRequest:
    """Request for fetching one active cooldown by asset."""

    asset_code: str
    direction: str | None = None


@dataclass(frozen=True)
class GetCooldownRemainingHoursRequest:
    """Request for cooldown remaining-hours query."""

    asset_code: str
    direction: str | None = None


@dataclass(frozen=True)
class CooldownRemainingHoursResult:
    """Cooldown remaining-hours result exposed to the interface layer."""

    asset_code: str
    remaining_hours: float

    @property
    def is_active(self) -> bool:
        """Whether the cooldown is still active."""
        return self.remaining_hours > 0


@dataclass(frozen=True)
class ListDecisionRequestsRequest:
    """Request for listing recent decision requests."""

    days: int = 30
    asset_code: str | None = None


@dataclass(frozen=True)
class GetDecisionRequestRequest:
    """Request for fetching a single decision request."""

    request_id: str


@dataclass(frozen=True)
class GetDecisionRequestStatisticsRequest:
    """Request for fetching decision request statistics."""

    days: int = 30


class ListDecisionQuotasUseCase:
    """List decision quotas outside the interface layer."""

    def __init__(self, quota_repo: QuotaRepositoryProtocol):
        self.quota_repo = quota_repo

    def execute(self, request: ListDecisionQuotasRequest) -> list[DecisionQuota]:
        """Return quotas for the requested filter set."""
        return self.quota_repo.get_all_quotas(
            period=request.period,
            account_id=request.account_id,
        )


class GetDecisionQuotaByPeriodUseCase:
    """Fetch one decision quota by period."""

    def __init__(self, quota_repo: QuotaRepositoryProtocol):
        self.quota_repo = quota_repo

    def execute(
        self,
        request: GetDecisionQuotaByPeriodRequest,
    ) -> DecisionQuota | None:
        """Return the quota matching the requested period and account."""
        return self.quota_repo.get_quota(
            request.period,
            account_id=request.account_id,
        )


class ListActiveCooldownsUseCase:
    """List active cooldowns outside the interface layer."""

    def __init__(self, cooldown_repo: CooldownRepositoryProtocol):
        self.cooldown_repo = cooldown_repo

    def execute(self) -> list[CooldownPeriod]:
        """Return all active cooldowns."""
        return self.cooldown_repo.get_all_active()


class GetActiveCooldownByAssetUseCase:
    """Fetch one active cooldown by asset code."""

    def __init__(self, cooldown_repo: CooldownRepositoryProtocol):
        self.cooldown_repo = cooldown_repo

    def execute(
        self,
        request: GetActiveCooldownByAssetRequest,
    ) -> CooldownPeriod | None:
        """Return the active cooldown for the requested asset."""
        return self.cooldown_repo.get_active_cooldown(
            request.asset_code,
            request.direction,
        )


class GetCooldownRemainingHoursUseCase:
    """Fetch cooldown remaining hours outside the interface layer."""

    def __init__(self, cooldown_repo: CooldownRepositoryProtocol):
        self.cooldown_repo = cooldown_repo

    def execute(
        self,
        request: GetCooldownRemainingHoursRequest,
    ) -> CooldownRemainingHoursResult:
        """Return remaining-hours summary for the requested asset."""
        return CooldownRemainingHoursResult(
            asset_code=request.asset_code,
            remaining_hours=self.cooldown_repo.get_remaining_hours(
                request.asset_code,
                request.direction,
            ),
        )


class ListDecisionRequestsUseCase:
    """List recent decision requests outside the interface layer."""

    def __init__(self, request_repo: DecisionRequestRepositoryProtocol):
        self.request_repo = request_repo

    def execute(
        self,
        request: ListDecisionRequestsRequest,
    ) -> list[DecisionRequest]:
        """Return recent decision requests."""
        return self.request_repo.get_recent(
            days=request.days,
            asset_code=request.asset_code,
        )


class GetDecisionRequestUseCase:
    """Fetch one decision request outside the interface layer."""

    def __init__(self, request_repo: DecisionRequestRepositoryProtocol):
        self.request_repo = request_repo

    def execute(
        self,
        request: GetDecisionRequestRequest,
    ) -> DecisionRequest | None:
        """Return one decision request by identifier."""
        return self.request_repo.get_by_id(request.request_id)


class GetDecisionRequestStatisticsUseCase:
    """Fetch request statistics outside the interface layer."""

    def __init__(self, request_repo: DecisionRequestRepositoryProtocol):
        self.request_repo = request_repo

    def execute(
        self,
        request: GetDecisionRequestStatisticsRequest,
    ) -> dict[str, Any]:
        """Return request statistics for the requested window."""
        return self.request_repo.get_statistics(request.days)
