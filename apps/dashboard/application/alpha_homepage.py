"""Dashboard Alpha homepage query services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from apps.account.application.repository_provider import get_portfolio_repository
from apps.account.application.use_cases import GetSizingContextUseCase
from apps.alpha.application.pool_resolver import (
    ALPHA_POOL_MODE_PRICE_COVERED,
    PortfolioAlphaPoolResolver,
)
from apps.alpha.application.services import AlphaService
from apps.alpha.application.trade_dates import resolve_recent_closed_trade_date
from apps.dashboard.application.alpha_homepage_candidates import AlphaCandidateMixin
from apps.dashboard.application.alpha_homepage_exit_watch import AlphaExitWatchMixin
from apps.dashboard.application.alpha_homepage_history import AlphaHistoryMixin
from apps.dashboard.application.alpha_homepage_runtime import AlphaRuntimeMixin
from apps.dashboard.application.repository_provider import (
    AlphaRecommendationHistoryRepository,
    DashboardAlphaContextRepository,
    get_alpha_recommendation_history_repository,
    get_dashboard_alpha_context_repository,
)
from apps.decision_rhythm.application.repository_provider import (
    get_portfolio_transition_plan_repository,
    get_unified_recommendation_repository,
)
from apps.strategy.domain.services import DecisionPolicyEngine, PreTradeRiskGate, SizingEngine

logger = logging.getLogger(__name__)

__all__ = [
    "ALPHA_SCOPE_GENERAL",
    "ALPHA_SCOPE_PORTFOLIO",
    "AlphaHomepageData",
    "AlphaHomepageQuery",
    "GetSizingContextUseCase",
    "normalize_alpha_scope",
]

ALPHA_SCOPE_GENERAL = "general"
ALPHA_SCOPE_PORTFOLIO = "portfolio"
ALPHA_SCOPE_CHOICES = {ALPHA_SCOPE_GENERAL, ALPHA_SCOPE_PORTFOLIO}


class DashboardUser(Protocol):
    """Minimal authenticated-user shape required by the homepage query."""

    id: int


def normalize_alpha_scope(raw_value: str | None) -> str:
    """Normalize Dashboard Alpha scope mode."""
    normalized = str(raw_value or "").strip().lower()
    if normalized in ALPHA_SCOPE_CHOICES:
        return normalized
    return ALPHA_SCOPE_PORTFOLIO


@dataclass(frozen=True)
class AlphaHomepageData:
    """Homepage Alpha payload."""

    pool: dict[str, Any]
    meta: dict[str, Any]
    top_candidates: list[dict[str, Any]]
    actionable_candidates: list[dict[str, Any]]
    exit_watchlist: list[dict[str, Any]]
    exit_watch_summary: dict[str, Any]
    pending_requests: list[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    history_run_id: int | None


class AlphaHomepageQuery(
    AlphaExitWatchMixin,
    AlphaRuntimeMixin,
    AlphaCandidateMixin,
    AlphaHistoryMixin,
):
    """Build the homepage Alpha candidate/ranking view."""

    def __init__(
        self,
        *,
        history_repo: AlphaRecommendationHistoryRepository | None = None,
        context_repo: DashboardAlphaContextRepository | None = None,
    ) -> None:
        self.history_repo = history_repo or get_alpha_recommendation_history_repository()
        self.context_repo = context_repo or get_dashboard_alpha_context_repository()
        self.portfolio_repo = get_portfolio_repository()
        self.alpha_service = AlphaService()
        self.decision_engine = DecisionPolicyEngine()
        self.sizing_engine = SizingEngine()
        self.risk_gate = PreTradeRiskGate()
        self.unified_recommendation_repo = get_unified_recommendation_repository()
        self.transition_plan_repo = get_portfolio_transition_plan_repository()

    def execute(
        self,
        *,
        user: DashboardUser,
        top_n: int = 10,
        portfolio_id: int | None = None,
        pool_mode: str | None = None,
        alpha_scope: str | None = None,
        refresh_sizing_pulse_if_stale: bool = False,
    ) -> AlphaHomepageData:
        today = resolve_recent_closed_trade_date()
        normalized_scope = normalize_alpha_scope(alpha_scope)
        if normalized_scope == ALPHA_SCOPE_GENERAL:
            return self._execute_general(
                user=user,
                top_n=top_n,
                trade_date=today,
            )

        resolved_pool = PortfolioAlphaPoolResolver().resolve(
            user_id=user.id,
            portfolio_id=portfolio_id,
            trade_date=today,
            pool_mode=pool_mode or ALPHA_POOL_MODE_PRICE_COVERED,
        )
        scope = resolved_pool.scope

        alpha_result = self._fetch_alpha_result(
            user=user,
            scope=scope,
            trade_date=today,
            top_n=top_n,
        )
        self._attach_scope_resolution_metadata(
            result=alpha_result,
            resolved_pool=resolved_pool,
        )
        meta = self._build_meta(
            alpha_result=alpha_result,
            scope=scope,
            resolved_pool=resolved_pool,
        )

        top_scores = list(alpha_result.scores[:top_n]) if alpha_result.success else []
        stock_context = self._load_stock_context([score.code for score in top_scores])
        actionable_map = self._load_actionable_map()
        pending_map = self._load_pending_map()
        position_map, portfolio_snapshot, sizing_context = self._load_portfolio_context(
            user_id=user.id,
            portfolio_id=resolved_pool.portfolio_id,
            refresh_pulse_if_stale=refresh_sizing_pulse_if_stale,
        )
        policy_state = self._load_policy_state()

        top_candidates: list[dict[str, Any]] = []
        displayed_snapshots: dict[str, dict[str, Any]] = {}
        for score in top_scores:
            item = self._build_candidate_item(
                score=score,
                stock_context=stock_context.get(score.code, {}),
                actionable_candidate=actionable_map.get(score.code),
                pending_request=pending_map.get(score.code),
                sizing_context=sizing_context,
                portfolio_snapshot=portfolio_snapshot,
                position_map=position_map,
                policy_state=policy_state,
                meta=meta,
            )
            top_candidates.append(item)
            displayed_snapshots[item["code"]] = item

        actionable_candidates = [item for item in top_candidates if item["stage"] == "actionable"]
        exit_watchlist = self._build_exit_watchlist(
            user_id=user.id,
            trade_date=today,
        )
        exit_watch_summary = self._build_exit_watch_summary(exit_watchlist)
        pending_requests = [
            self._serialize_pending_request(
                request_model=model,
                stock_context=stock_context.get(code, {}),
            )
            for code, model in pending_map.items()
        ]

        for item in pending_requests:
            displayed_snapshots.setdefault(item["code"], item)

        history_run_id = self._persist_history(
            user_id=user.id,
            portfolio_id=resolved_pool.portfolio_id,
            portfolio_name=resolved_pool.portfolio_name,
            scope=scope,
            alpha_result=alpha_result,
            meta=meta,
            snapshots=list(displayed_snapshots.values()),
        )
        recent_runs = self._serialize_recent_runs(
            self.history_repo.list_recent_runs(
                user_id=user.id,
                portfolio_id=resolved_pool.portfolio_id,
                limit=5,
            )
        )

        return AlphaHomepageData(
            pool={
                "alpha_scope": ALPHA_SCOPE_PORTFOLIO,
                "portfolio_id": resolved_pool.portfolio_id,
                "portfolio_name": resolved_pool.portfolio_name,
                "label": scope.display_label,
                "pool_type": scope.pool_type,
                "market": scope.market,
                "pool_mode": scope.pool_mode,
                "pool_size": scope.pool_size,
                "requested_pool_mode": resolved_pool.requested_pool_mode,
                "requested_pool_size": resolved_pool.requested_pool_size,
                "scope_fallback": resolved_pool.scope_fallback,
                "fallback_reason": resolved_pool.fallback_reason,
                "selection_reason": scope.selection_reason,
                "scope_hash": scope.scope_hash,
            },
            meta=meta,
            top_candidates=top_candidates,
            actionable_candidates=actionable_candidates,
            exit_watchlist=exit_watchlist,
            exit_watch_summary=exit_watch_summary,
            pending_requests=pending_requests,
            recent_runs=recent_runs,
            history_run_id=history_run_id,
        )

    def _execute_general(
        self, *, user: DashboardUser, top_n: int, trade_date: date
    ) -> AlphaHomepageData:
        """Build a broad-universe research-only Alpha ranking payload."""
        alpha_result = self._fetch_general_alpha_result(
            user=user,
            trade_date=trade_date,
            top_n=top_n,
        )
        self._mark_general_research_only(result=alpha_result, trade_date=trade_date)
        top_scores = list(alpha_result.scores[:top_n]) if alpha_result.success else []
        scope = self._build_general_scope(
            trade_date=trade_date,
            instrument_codes=[score.code for score in top_scores],
        )
        meta = self._build_meta(alpha_result=alpha_result, scope=scope)

        stock_context = self._load_stock_context([score.code for score in top_scores])
        policy_state = self._load_policy_state()
        top_candidates = [
            self._build_candidate_item(
                score=score,
                stock_context=stock_context.get(score.code, {}),
                actionable_candidate=None,
                pending_request=None,
                sizing_context=None,
                portfolio_snapshot=None,
                position_map={},
                policy_state=policy_state,
                meta=meta,
            )
            for score in top_scores
        ]

        return AlphaHomepageData(
            pool={
                "alpha_scope": ALPHA_SCOPE_GENERAL,
                "portfolio_id": None,
                "portfolio_name": "通用研究池",
                "label": scope.display_label,
                "pool_type": scope.pool_type,
                "market": scope.market,
                "pool_mode": scope.pool_mode,
                "pool_size": scope.pool_size,
                "requested_pool_mode": scope.pool_mode,
                "requested_pool_size": scope.pool_size,
                "scope_fallback": False,
                "fallback_reason": "",
                "selection_reason": scope.selection_reason,
                "scope_hash": scope.scope_hash,
                "universe_id": "csi300",
            },
            meta=meta,
            top_candidates=top_candidates,
            actionable_candidates=[],
            exit_watchlist=[],
            exit_watch_summary=self._build_exit_watch_summary([]),
            pending_requests=[],
            recent_runs=[],
            history_run_id=None,
        )
