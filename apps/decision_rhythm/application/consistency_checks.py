"""Consistency checks for Alpha rankings and workspace recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class AlphaRankingSnapshot:
    """Latest Alpha ranking state used by consistency checks."""

    latest_trade_date: date | None
    latest_updated_at: datetime | None
    top_codes: tuple[str, ...] = ()
    provider_source: str = ""
    status: str = ""
    runtime_provider_status: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceRecommendationSnapshot:
    """Latest workspace recommendation state for one account."""

    account_id: str
    latest_updated_at: datetime | None
    recommendation_codes: tuple[str, ...] = ()
    source_candidate_ids: tuple[str, ...] = ()
    total_count: int = 0


@dataclass(frozen=True)
class ConsistencyIssue:
    """One consistency finding."""

    code: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return an API-safe representation."""

        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class AlphaWorkspaceConsistencyResult:
    """Consistency check result."""

    status: str
    checked_account_id: str
    alpha: AlphaRankingSnapshot
    workspace: WorkspaceRecommendationSnapshot
    issues: tuple[ConsistencyIssue, ...] = ()

    @property
    def is_ok(self) -> bool:
        """Return whether no issue was detected."""

        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        """Return an API-safe representation."""

        return {
            "status": self.status,
            "checked_account_id": self.checked_account_id,
            "alpha": {
                "latest_trade_date": (
                    self.alpha.latest_trade_date.isoformat()
                    if self.alpha.latest_trade_date
                    else None
                ),
                "latest_updated_at": (
                    self.alpha.latest_updated_at.isoformat()
                    if self.alpha.latest_updated_at
                    else None
                ),
                "top_codes": list(self.alpha.top_codes),
                "provider_source": self.alpha.provider_source,
                "status": self.alpha.status,
                "runtime_provider_status": self.alpha.runtime_provider_status,
            },
            "workspace": {
                "account_id": self.workspace.account_id,
                "latest_updated_at": (
                    self.workspace.latest_updated_at.isoformat()
                    if self.workspace.latest_updated_at
                    else None
                ),
                "recommendation_codes": list(self.workspace.recommendation_codes),
                "source_candidate_ids": list(self.workspace.source_candidate_ids),
                "total_count": self.workspace.total_count,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


class AlphaWorkspaceConsistencyChecker:
    """Evaluate whether workspace recommendations track latest Alpha rankings."""

    def __init__(
        self,
        *,
        allowed_lag_days: int = 1,
        min_top_overlap: int = 1,
        require_alpha_rank_origin: bool = True,
    ) -> None:
        self.allowed_lag_days = max(0, allowed_lag_days)
        self.min_top_overlap = max(0, min_top_overlap)
        self.require_alpha_rank_origin = require_alpha_rank_origin

    def evaluate(
        self,
        *,
        alpha: AlphaRankingSnapshot,
        workspace: WorkspaceRecommendationSnapshot,
    ) -> AlphaWorkspaceConsistencyResult:
        """Evaluate snapshots and return issues without touching external systems."""

        issues: list[ConsistencyIssue] = []

        if not alpha.latest_trade_date or not alpha.top_codes:
            issues.append(
                ConsistencyIssue(
                    code="alpha_ranking_empty",
                    severity="warning",
                    message="Alpha 排名快照为空，无法校验工作台候选一致性。",
                )
            )

        if workspace.total_count == 0 or not workspace.recommendation_codes:
            issues.append(
                ConsistencyIssue(
                    code="workspace_recommendations_empty",
                    severity="warning",
                    message="工作台推荐为空，需要刷新或检查候选生成链路。",
                    details={"account_id": workspace.account_id},
                )
            )

        qlib_status = alpha.runtime_provider_status.get("qlib")
        if qlib_status is None and alpha.runtime_provider_status:
            issues.append(
                ConsistencyIssue(
                    code="alpha_qlib_provider_missing",
                    severity="warning",
                    message="Alpha runtime provider 状态中缺少 qlib，可能正在使用降级链路。",
                    details={"providers": sorted(alpha.runtime_provider_status.keys())},
                )
            )
        elif isinstance(qlib_status, dict):
            status = str(qlib_status.get("status") or "").lower()
            if status and status != "available":
                issues.append(
                    ConsistencyIssue(
                        code="alpha_qlib_provider_degraded",
                        severity="warning",
                        message="Qlib provider 当前不可用或降级，Alpha 排名可能来自缓存兜底。",
                        details=dict(qlib_status),
                    )
                )

        if alpha.latest_trade_date and workspace.latest_updated_at:
            lag_days = (alpha.latest_trade_date - workspace.latest_updated_at.date()).days
            if lag_days > self.allowed_lag_days:
                issues.append(
                    ConsistencyIssue(
                        code="workspace_recommendations_stale",
                        severity="warning",
                        message="工作台推荐更新时间明显落后于最新 Alpha 排名。",
                        details={
                            "alpha_latest_trade_date": alpha.latest_trade_date.isoformat(),
                            "workspace_latest_updated_at": (
                                workspace.latest_updated_at.isoformat()
                            ),
                            "lag_days": lag_days,
                            "allowed_lag_days": self.allowed_lag_days,
                        },
                    )
                )

        if alpha.top_codes and workspace.recommendation_codes and self.min_top_overlap > 0:
            top_set = set(alpha.top_codes)
            workspace_set = set(workspace.recommendation_codes)
            overlap = sorted(top_set & workspace_set)
            if len(overlap) < self.min_top_overlap:
                issues.append(
                    ConsistencyIssue(
                        code="workspace_alpha_overlap_low",
                        severity="warning",
                        message="工作台推荐与最新 Alpha 排名重合度过低。",
                        details={
                            "overlap_count": len(overlap),
                            "required_overlap": self.min_top_overlap,
                            "overlap_codes": overlap,
                        },
                    )
                )

        if (
            self.require_alpha_rank_origin
            and workspace.total_count > 0
            and not any(
                source_id.startswith("alpha_rank:")
                for source_id in workspace.source_candidate_ids
            )
        ):
            issues.append(
                ConsistencyIssue(
                    code="workspace_missing_alpha_rank_origin",
                    severity="warning",
                    message="工作台推荐缺少 Alpha 排名候选溯源，可能仍在使用旧候选链路。",
                    details={"account_id": workspace.account_id},
                )
            )

        status = "ok" if not issues else "warning"
        return AlphaWorkspaceConsistencyResult(
            status=status,
            checked_account_id=workspace.account_id,
            alpha=alpha,
            workspace=workspace,
            issues=tuple(issues),
        )
