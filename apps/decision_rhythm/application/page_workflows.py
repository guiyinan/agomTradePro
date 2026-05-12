"""Application workflows for decision rhythm HTML page rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..domain.entities import (
    DecisionQuota,
    ExecutionStatus,
    QuotaPeriod,
)
from .query_workflows import (
    CooldownRepositoryProtocol,
    DecisionRequestRepositoryProtocol,
    QuotaRepositoryProtocol,
)

_EXECUTION_STATUS_LABELS = {
    ExecutionStatus.PENDING.value: "待执行",
    ExecutionStatus.EXECUTED.value: "已执行",
    ExecutionStatus.FAILED.value: "执行失败",
    ExecutionStatus.CANCELLED.value: "已取消",
}

_PERIOD_LABELS = {
    QuotaPeriod.DAILY: "每日",
    QuotaPeriod.WEEKLY: "每周",
    QuotaPeriod.MONTHLY: "每月",
}


class AccountEntityProtocol(Protocol):
    """Protocol for simulated account entities used by page workflows."""

    account_id: int
    account_name: str
    account_type: Any


class AccountRepositoryProtocol(Protocol):
    """Protocol for loading simulated accounts."""

    def get_by_user(self, user_id: int) -> list[AccountEntityProtocol]:
        """Return accounts owned by the given user."""


class AssetNameResolverProtocol(Protocol):
    """Protocol for bulk asset-name resolution."""

    def __call__(self, codes: list[str]) -> dict[str, str]:
        """Return a mapping from asset code to display name."""


@dataclass(frozen=True)
class PageAccountOption:
    """Account selector item used by HTML pages."""

    id: str
    account_name: str
    account_type: str


@dataclass(frozen=True)
class PageCurrentQuota:
    """Current quota card view model."""

    max_decisions: int
    used_decisions: int
    period_start: datetime | None = None
    period_end: datetime | None = None


@dataclass(frozen=True)
class PageCooldownItem:
    """Cooldown row view model."""

    asset_code: str
    asset_name: str
    min_decision_interval_hours: int
    min_execution_interval_hours: int
    last_decision_at: datetime | None = None


@dataclass(frozen=True)
class PageDecisionRequestItem:
    """Decision request row view model."""

    request_id: str
    asset_code: str
    asset_name: str
    direction: str
    execution_status: str
    priority: str
    requested_at: datetime | None = None

    def get_execution_status_display(self) -> str:
        """Return the legacy template display label for execution status."""
        return _EXECUTION_STATUS_LABELS.get(
            self.execution_status,
            self.execution_status,
        )


@dataclass(frozen=True)
class PageQuotaConfigItem:
    """Quota config card view model."""

    period: str
    used_decisions: int
    max_decisions: int
    used_executions: int
    max_execution_count: int


@dataclass(frozen=True)
class DecisionQuotaPageContext:
    """Structured context for the quota overview page."""

    current_quota: PageCurrentQuota | None
    active_cooldowns: list[PageCooldownItem]
    recent_requests: list[PageDecisionRequestItem]
    accounts: list[PageAccountOption]
    current_account_id: str
    quota_used: int
    quota_remaining: int
    quota_total: int
    quota_usage_percent: float
    page_title: str = "决策配额管理"
    page_description: str = "决策频率约束与配额监控"

    def to_context(self) -> dict[str, Any]:
        """Return a Django-template-friendly context mapping."""
        return {
            "current_quota": self.current_quota,
            "active_cooldowns": self.active_cooldowns,
            "recent_requests": self.recent_requests,
            "accounts": self.accounts,
            "current_account_id": self.current_account_id,
            "quota_used": self.quota_used,
            "quota_remaining": self.quota_remaining,
            "quota_total": self.quota_total,
            "quota_usage_percent": self.quota_usage_percent,
            "page_title": self.page_title,
            "page_description": self.page_description,
        }


@dataclass(frozen=True)
class DecisionQuotaConfigPageContext:
    """Structured context for the quota configuration page."""

    quotas: list[PageQuotaConfigItem]
    accounts: list[PageAccountOption]
    current_account_id: str
    period_choices: list[tuple[str, str]]
    page_title: str = "决策配额配置"
    page_description: str = "配置和管理决策配额"

    def to_context(self) -> dict[str, Any]:
        """Return a Django-template-friendly context mapping."""
        return {
            "quotas": self.quotas,
            "accounts": self.accounts,
            "current_account_id": self.current_account_id,
            "period_choices": self.period_choices,
            "page_title": self.page_title,
            "page_description": self.page_description,
        }


@dataclass(frozen=True)
class DecisionQuotaPageRequest:
    """Request for the quota overview page workflow."""

    requested_account_id: str = ""
    user_id: int | None = None
    is_authenticated: bool = False


@dataclass(frozen=True)
class DecisionQuotaConfigPageRequest:
    """Request for the quota config page workflow."""

    requested_account_id: str = ""
    user_id: int | None = None
    is_authenticated: bool = False


class GetDecisionQuotaPageUseCase:
    """Build the quota overview page context outside the interface layer."""

    def __init__(
        self,
        *,
        account_repo: AccountRepositoryProtocol,
        quota_repo: QuotaRepositoryProtocol,
        cooldown_repo: CooldownRepositoryProtocol,
        request_repo: DecisionRequestRepositoryProtocol,
        asset_name_resolver: AssetNameResolverProtocol,
    ):
        self.account_repo = account_repo
        self.quota_repo = quota_repo
        self.cooldown_repo = cooldown_repo
        self.request_repo = request_repo
        self.asset_name_resolver = asset_name_resolver

    def execute(
        self,
        request: DecisionQuotaPageRequest,
    ) -> DecisionQuotaPageContext:
        """Return structured context for the quota overview page."""
        accounts = self._build_accounts(request.user_id, request.is_authenticated)
        current_account_id = self._resolve_account_id(
            request.requested_account_id,
            accounts,
        )

        account_filter = current_account_id or "default"
        quotas = self.quota_repo.get_all_quotas(account_id=account_filter)
        current_quota = self._select_latest_quota(quotas)

        active_cooldowns = self.cooldown_repo.get_all_active()[:10]
        recent_requests = self.request_repo.get_recent(days=3650)[:20]

        asset_name_map = self.asset_name_resolver(
            [cooldown.asset_code for cooldown in active_cooldowns if cooldown.asset_code]
            + [
                decision_request.asset_code
                for decision_request in recent_requests
                if decision_request.asset_code
            ]
        )

        quota_total = current_quota.max_decisions if current_quota else 10
        quota_used = current_quota.used_decisions if current_quota else 0
        quota_remaining = max(0, quota_total - quota_used)

        return DecisionQuotaPageContext(
            current_quota=(
                PageCurrentQuota(
                    max_decisions=current_quota.max_decisions,
                    used_decisions=current_quota.used_decisions,
                    period_start=current_quota.period_start,
                    period_end=current_quota.period_end,
                )
                if current_quota
                else None
            ),
            active_cooldowns=[
                PageCooldownItem(
                    asset_code=cooldown.asset_code,
                    asset_name=asset_name_map.get(
                        cooldown.asset_code,
                        cooldown.asset_code,
                    ),
                    min_decision_interval_hours=cooldown.min_decision_interval_hours,
                    min_execution_interval_hours=cooldown.min_execution_interval_hours,
                    last_decision_at=cooldown.last_decision_at,
                )
                for cooldown in active_cooldowns
            ],
            recent_requests=[
                PageDecisionRequestItem(
                    request_id=decision_request.request_id,
                    asset_code=decision_request.asset_code,
                    asset_name=asset_name_map.get(
                        decision_request.asset_code,
                        decision_request.asset_code,
                    ),
                    direction=decision_request.direction,
                    execution_status=decision_request.execution_status.value,
                    priority=decision_request.priority.value,
                    requested_at=decision_request.requested_at,
                )
                for decision_request in recent_requests
            ],
            accounts=accounts,
            current_account_id=current_account_id,
            quota_used=quota_used,
            quota_remaining=quota_remaining,
            quota_total=quota_total,
            quota_usage_percent=(
                round(quota_used / quota_total * 100, 1) if quota_total > 0 else 0.0
            ),
        )

    def _build_accounts(
        self,
        user_id: int | None,
        is_authenticated: bool,
    ) -> list[PageAccountOption]:
        """Return account selector options for the current user."""
        if not is_authenticated or user_id is None:
            return []

        accounts = self.account_repo.get_by_user(user_id)
        return sorted(
            [
                PageAccountOption(
                    id=str(account.account_id),
                    account_name=account.account_name,
                    account_type=getattr(account.account_type, "value", str(account.account_type)),
                )
                for account in accounts
            ],
            key=lambda item: (item.account_type, item.account_name),
        )

    def _resolve_account_id(
        self,
        requested_account_id: str,
        accounts: list[PageAccountOption],
    ) -> str:
        """Return the account id that should drive the page query."""
        if requested_account_id:
            return requested_account_id
        if accounts:
            return accounts[0].id
        return ""

    def _select_latest_quota(
        self,
        quotas: list[DecisionQuota],
    ) -> DecisionQuota | None:
        """Return the latest quota entry by period start."""
        if not quotas:
            return None
        return max(
            quotas,
            key=lambda quota: quota.period_start or datetime.min.replace(tzinfo=UTC),
        )


class GetDecisionQuotaConfigPageUseCase:
    """Build the quota config page context outside the interface layer."""

    def __init__(
        self,
        *,
        account_repo: AccountRepositoryProtocol,
        quota_repo: QuotaRepositoryProtocol,
    ):
        self.account_repo = account_repo
        self.quota_repo = quota_repo

    def execute(
        self,
        request: DecisionQuotaConfigPageRequest,
    ) -> DecisionQuotaConfigPageContext:
        """Return structured context for the quota configuration page."""
        accounts = self._build_accounts(request.user_id, request.is_authenticated)
        current_account_id = self._resolve_account_id(
            request.requested_account_id,
            accounts,
        )
        account_filter = current_account_id or "default"

        quotas = self.quota_repo.get_all_quotas(account_id=account_filter)
        config_items = [
            PageQuotaConfigItem(
                period=quota.period.value,
                used_decisions=quota.used_decisions,
                max_decisions=quota.max_decisions,
                used_executions=quota.used_executions,
                max_execution_count=quota.max_execution_count,
            )
            for quota in quotas
        ]

        return DecisionQuotaConfigPageContext(
            quotas=config_items,
            accounts=accounts,
            current_account_id=current_account_id,
            period_choices=[(period.value, _PERIOD_LABELS[period]) for period in QuotaPeriod],
        )

    def _build_accounts(
        self,
        user_id: int | None,
        is_authenticated: bool,
    ) -> list[PageAccountOption]:
        """Return account selector options for the current user."""
        if not is_authenticated or user_id is None:
            return []

        accounts = self.account_repo.get_by_user(user_id)
        return sorted(
            [
                PageAccountOption(
                    id=str(account.account_id),
                    account_name=account.account_name,
                    account_type=getattr(account.account_type, "value", str(account.account_type)),
                )
                for account in accounts
            ],
            key=lambda item: (item.account_type, item.account_name),
        )

    def _resolve_account_id(
        self,
        requested_account_id: str,
        accounts: list[PageAccountOption],
    ) -> str:
        """Return the account id that should drive the page query."""
        if requested_account_id:
            return requested_account_id
        if accounts:
            return accounts[0].id
        return ""
