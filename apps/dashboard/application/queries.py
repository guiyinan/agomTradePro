"""
Dashboard Query Services.

Application 层查询服务，为 Dashboard 视图提供数据聚合。

重构说明 (2026-03-11):
- 将跨模块数据获取逻辑从 views.py 移至 Query Services
- 隐藏 ORM 实现细节
- 提供简化的 API 给视图层使用
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils import timezone as django_timezone

from apps.dashboard.application.repository_provider import (
    get_dashboard_alpha_context_repository,
    get_dashboard_query_repository,
)

logger = logging.getLogger(__name__)

DEGRADED_DASHBOARD_QUERY_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


# ============================================================================
# Alpha Visualization Query Service
# ============================================================================


@dataclass(frozen=True)
class AlphaVisualizationData:
    """Alpha 可视化数据"""

    stock_scores: list[dict[str, Any]]
    stock_scores_meta: dict[str, Any]
    provider_status: dict[str, Any]
    coverage_metrics: dict[str, Any]
    ic_trends: list[dict[str, Any]]
    ic_trends_meta: dict[str, Any]


class AlphaVisualizationQuery:
    """
    Alpha 可视化查询服务

    聚合 Alpha 选股评分、Provider 状态、覆盖率指标和 IC 趋势数据。

    Example:
        >>> query = AlphaVisualizationQuery()
        >>> data = query.execute(top_n=10, ic_days=30)
        >>> print(len(data.stock_scores))
    """

    def execute(
        self,
        top_n: int = 10,
        ic_days: int = 30,
        user: Any | None = None,
    ) -> AlphaVisualizationData:
        """
        执行查询

        Args:
            top_n: 返回的股票数量
            ic_days: IC 趋势天数
            user: 当前登录用户，用于读取用户级 Alpha 缓存

        Returns:
            AlphaVisualizationData
        """
        stock_scores_payload = self._get_stock_scores_payload(top_n, user=user)
        ic_trends = self._get_ic_trends(ic_days)
        return AlphaVisualizationData(
            stock_scores=stock_scores_payload["items"],
            stock_scores_meta=stock_scores_payload["meta"],
            provider_status=self._get_provider_status(),
            coverage_metrics=self._get_coverage_metrics(),
            ic_trends=ic_trends,
            ic_trends_meta=self._build_ic_trends_meta(ic_trends),
        )

    def execute_metrics(self, ic_days: int = 30) -> AlphaVisualizationData:
        """Load dashboard Alpha metrics without fetching stock scores."""
        ic_trends = self._get_ic_trends(ic_days)
        return AlphaVisualizationData(
            stock_scores=[],
            stock_scores_meta={},
            provider_status=self._get_lightweight_provider_status(),
            coverage_metrics=self._get_coverage_metrics(),
            ic_trends=ic_trends,
            ic_trends_meta=self._build_ic_trends_meta(ic_trends),
        )

    def _get_stock_scores_payload(
        self,
        top_n: int,
        user: Any | None = None,
    ) -> dict[str, Any]:
        """获取 Alpha 选股评分结果"""
        try:
            from apps.alpha.application.services import AlphaService

            service = AlphaService()
            result = None
            attempts: list[tuple[str, Any]] = []
            for provider_name in ("qlib", "cache", "simple", "etf"):
                candidate = service.get_stock_scores(
                    universe_id="csi300",
                    intended_trade_date=date.today(),
                    top_n=top_n,
                    user=user,
                    provider_filter=provider_name,
                )
                attempts.append((provider_name, candidate))
                result = candidate
                if candidate.success and candidate.scores:
                    result = self._annotate_dashboard_alpha_result(
                        candidate,
                        selected_provider=provider_name,
                        attempts=attempts,
                    )
                    break

            if result and result.success and result.scores:
                code_to_name = self._resolve_security_names(
                    [score.code for score in result.scores[:top_n]]
                )
                return {
                    "items": [
                        {
                            "code": score.code,
                            "name": code_to_name.get(score.code, ""),
                            "score": round(score.score, 4),
                            "rank": score.rank,
                            "source": score.source,
                            "confidence": round(score.confidence, 3),
                            "factors": score.factors,
                            "asof_date": score.asof_date.isoformat() if score.asof_date else None,
                        }
                        for score in result.scores[:top_n]
                    ],
                    "meta": self._build_stock_scores_meta(result),
                }
            return {
                "items": [],
                "meta": (
                    self._build_stock_scores_meta(result)
                    if result
                    else {
                        "status": "error",
                        "source": "none",
                        "warning_message": "alpha_stock_scores_unavailable",
                        "is_degraded": True,
                        "uses_cached_data": False,
                    }
                ),
            }
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get alpha stock scores: {e}")
            return {
                "items": [],
                "meta": {
                    "status": "error",
                    "source": "none",
                    "warning_message": "alpha_stock_scores_unavailable",
                    "is_degraded": True,
                    "uses_cached_data": False,
                },
            }

    def _annotate_dashboard_alpha_result(
        self,
        result,
        *,
        selected_provider: str,
        attempts: list[tuple[str, Any]],
    ):
        """Attach dashboard-specific freshness hints when the page falls back from realtime qlib."""
        metadata = dict(getattr(result, "metadata", {}) or {})
        qlib_attempt = next(
            (candidate for provider, candidate in attempts if provider == "qlib"), None
        )
        if (
            selected_provider != "qlib"
            and qlib_attempt is not None
            and not getattr(qlib_attempt, "success", False)
        ):
            qlib_metadata = dict(getattr(qlib_attempt, "metadata", {}) or {})
            fallback_reason = (
                getattr(qlib_attempt, "error_message", None)
                or qlib_metadata.get("reliability_notice", {}).get("message")
                or "实时 Qlib 结果尚未就绪"
            )
            refresh_triggered = bool(qlib_metadata.get("async_task_triggered"))
            asof_date = metadata.get("asof_date") or metadata.get("cache_date")

            metadata.setdefault("fallback_from", "qlib")
            metadata.setdefault("fallback_reason", fallback_reason)
            metadata["refresh_triggered"] = refresh_triggered
            metadata["uses_cached_data"] = bool(
                metadata.get("uses_cached_data", False)
                or (
                    selected_provider == "cache"
                    and not metadata.get("latest_available_qlib_result", False)
                )
            )

            if (
                selected_provider == "cache"
                and metadata.get("uses_cached_data")
                and not metadata.get("reliability_notice")
            ):
                message = (
                    f"当前展示的是 {asof_date or '未知日期'} 的缓存评分。原因：{fallback_reason}"
                )
                if refresh_triggered:
                    message += " 系统已自动触发实时刷新任务，可稍后重试。"
                metadata["reliability_notice"] = {
                    "level": "warning",
                    "code": "dashboard_cache_fallback",
                    "title": "Alpha 当前使用缓存结果",
                    "message": message,
                }

        result.metadata = metadata
        return result

    def _build_stock_scores_meta(self, result) -> dict[str, Any]:
        """Build template/API-friendly metadata for Alpha score reliability."""
        metadata = dict(getattr(result, "metadata", {}) or {})
        notice = metadata.get("reliability_notice") or {}
        return {
            "status": getattr(result, "status", "available"),
            "source": getattr(result, "source", "none"),
            "staleness_days": getattr(result, "staleness_days", None),
            "is_degraded": bool(
                metadata.get("is_degraded", getattr(result, "status", "") == "degraded")
            ),
            "uses_cached_data": bool(metadata.get("uses_cached_data", False)),
            "effective_asof_date": metadata.get("effective_asof_date"),
            "requested_trade_date": metadata.get("requested_trade_date"),
            "warning_title": notice.get("title"),
            "warning_message": notice.get("message"),
            "warning_level": notice.get("level"),
            "warning_code": notice.get("code"),
            "qlib_data_latest_date": metadata.get("qlib_data_latest_date"),
            "cache_date": metadata.get("cache_date"),
            "cache_created_at": metadata.get("created_at"),
            "provider_source": metadata.get("provider_source"),
            "fallback_from": metadata.get("fallback_from"),
            "fallback_reason": metadata.get("fallback_reason"),
            "refresh_triggered": bool(metadata.get("refresh_triggered", False)),
        }

    def _resolve_security_names(self, codes: list[str]) -> dict[str, str]:
        """根据代码解析证券名称"""
        code_aliases = self._build_code_aliases(codes)
        if not code_aliases:
            return {}

        try:
            from apps.asset_analysis.application.asset_name_service import resolve_asset_names
        except (ImportError, ImproperlyConfigured) as e:
            logger.debug(f"Failed to import asset name resolver: {e}")
            return {}

        lookup_codes = sorted({alias for aliases in code_aliases.values() for alias in aliases})
        try:
            resolved_lookup_map = resolve_asset_names(lookup_codes)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.debug(f"Failed to resolve security names: {e}")
            return {}

        name_map: dict[str, str] = {}
        for requested_code, aliases in code_aliases.items():
            for alias in aliases:
                resolved_name = resolved_lookup_map.get(alias)
                if resolved_name:
                    name_map[requested_code] = resolved_name
                    break

        return name_map

    def _build_code_aliases(self, codes: list[str]) -> dict[str, set[str]]:
        """Build request-code aliases so full symbols and base codes can share one lookup."""
        aliases: dict[str, set[str]] = {}
        for code in codes:
            original = (code or "").strip()
            normalized = original.upper()
            if not normalized:
                continue

            code_aliases = {normalized}
            base_code = normalized.split(".")[0]
            if base_code:
                code_aliases.add(base_code)

            aliases[original] = code_aliases
        return aliases

    def _assign_names_from_rows(
        self,
        *,
        name_map: dict[str, str],
        code_aliases: dict[str, set[str]],
        rows,
        code_field: str,
        name_field: str,
    ) -> None:
        """Assign names back to the original request codes by matching lookup aliases."""
        for row in rows:
            resolved_code = str(row.get(code_field) or "").strip().upper()
            resolved_name = row.get(name_field) or ""
            if not resolved_code or not resolved_name:
                continue

            for requested_code, aliases in code_aliases.items():
                if requested_code not in name_map and resolved_code in aliases:
                    name_map[requested_code] = resolved_name

    def _get_provider_status(self) -> dict[str, Any]:
        """获取 Alpha Provider 状态"""
        try:
            from apps.alpha.application.services import AlphaService
            from shared.infrastructure.metrics import get_alpha_metrics

            service = AlphaService()
            provider_status = service.get_provider_status()
            metrics = get_alpha_metrics()

            provider_metrics = {}
            for provider_name in provider_status.keys():
                success_rate = metrics.registry.get_metric(
                    "alpha_provider_success_rate", {"provider": provider_name}
                )
                latency = metrics.registry.get_metric(
                    "alpha_provider_latency_ms", {"provider": provider_name}
                )

                provider_metrics[provider_name] = {
                    "success_rate": round(success_rate.value, 3) if success_rate else 0.0,
                    "latency_ms": int(latency.value) if latency else 0,
                }

            return {
                "providers": provider_status,
                "metrics": provider_metrics,
                "timestamp": django_timezone.now().isoformat(),
                "status": "available",
                "data_source": "live",
                "warning_message": None,
            }
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get alpha provider status: {e}")
            return {
                "providers": {},
                "metrics": {},
                "timestamp": None,
                "status": "degraded",
                "data_source": "fallback",
                "warning_message": "provider_status_unavailable",
            }

    def _get_lightweight_provider_status(self) -> dict[str, Any]:
        """Get Alpha Provider metadata for homepage metrics without health checks."""
        try:
            from apps.alpha.application.services import AlphaService
            from shared.infrastructure.metrics import get_alpha_metrics

            service = AlphaService()
            if hasattr(service, "get_provider_registry_status"):
                provider_status = service.get_provider_registry_status()
            else:
                provider_status = service.get_provider_status()
            metrics = get_alpha_metrics()

            provider_metrics = {}
            for provider_name in provider_status.keys():
                success_rate = metrics.registry.get_metric(
                    "alpha_provider_success_rate", {"provider": provider_name}
                )
                latency = metrics.registry.get_metric(
                    "alpha_provider_latency_ms", {"provider": provider_name}
                )

                provider_metrics[provider_name] = {
                    "success_rate": round(success_rate.value, 3) if success_rate else 0.0,
                    "latency_ms": int(latency.value) if latency else 0,
                }

            return {
                "providers": provider_status,
                "metrics": provider_metrics,
                "timestamp": django_timezone.now().isoformat(),
                "status": "registered",
                "data_source": "registry",
                "warning_message": None,
            }
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get lightweight alpha provider status: {e}")
            return {
                "providers": {},
                "metrics": {},
                "timestamp": django_timezone.now().isoformat(),
                "status": "degraded",
                "data_source": "fallback",
                "warning_message": "provider_registry_unavailable",
            }

    def _get_coverage_metrics(self) -> dict[str, Any]:
        """获取 Alpha 覆盖率指标"""
        try:
            from shared.infrastructure.metrics import get_alpha_metrics

            metrics = get_alpha_metrics()

            coverage = metrics.registry.get_metric("alpha_coverage_ratio")
            request_count = metrics.registry.get_metric("alpha_score_request_count")
            cache_hit_rate = metrics.registry.get_metric("alpha_cache_hit_rate")

            return {
                "coverage_ratio": round(coverage.value, 3) if coverage else 0.0,
                "total_requests": int(request_count.value) if request_count else 0,
                "cache_hit_rate": round(cache_hit_rate.value, 3) if cache_hit_rate else 0.0,
                "timestamp": django_timezone.now().isoformat(),
                "status": "available",
                "data_source": "live",
                "warning_message": None,
            }
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get alpha coverage metrics: {e}")
            return {
                "coverage_ratio": 0.0,
                "total_requests": 0,
                "cache_hit_rate": 0.0,
                "timestamp": None,
                "status": "degraded",
                "data_source": "fallback",
                "warning_message": "coverage_metrics_unavailable",
            }

    def _get_ic_trends(self, days: int) -> list[dict[str, Any]]:
        """获取 Alpha IC/ICIR 趋势数据"""
        try:
            trends = get_dashboard_query_repository().get_alpha_ic_trends(days)
            if trends:
                return trends
            return self._empty_ic_data(days)

        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get alpha IC trends: {e}")
            return self._empty_ic_data(days)

    def _empty_ic_data(self, days: int) -> list[dict[str, Any]]:
        """返回显式 unavailable 的空 IC 时间序列。"""
        trends = []
        base_date = date.today()

        for i in range(days):
            check_date = base_date - timedelta(days=days - i)
            trends.append(
                {
                    "date": check_date.isoformat(),
                    "ic": None,
                    "icir": None,
                    "rank_ic": None,
                }
            )

        return trends

    def _build_ic_trends_meta(self, trends: list[dict[str, Any]]) -> dict[str, Any]:
        has_live_data = any(
            row.get("ic") is not None
            or row.get("icir") is not None
            or row.get("rank_ic") is not None
            for row in trends
        )
        if has_live_data:
            return {
                "status": "available",
                "data_source": "live",
                "warning_message": None,
            }
        return {
            "status": "unavailable",
            "data_source": "fallback",
            "warning_message": "ic_trends_unavailable",
        }


# ============================================================================
# Decision Plane Query Service
# ============================================================================


@dataclass(frozen=True)
class DecisionPlaneData:
    """决策平面数据"""

    beta_gate_visible_classes: str
    alpha_watch_count: int
    alpha_candidate_count: int
    alpha_actionable_count: int
    quota_total: int
    quota_used: int
    quota_remaining: int
    quota_usage_percent: float
    actionable_candidates: list[Any]
    pending_requests: list[Any]


@dataclass(frozen=True)
class AlphaDecisionChainData:
    """Alpha 决策链聚合数据。"""

    overview: dict[str, Any]
    top_stocks: list[dict[str, Any]]
    actionable_candidates: list[dict[str, Any]]
    pending_requests: list[dict[str, Any]]


class DecisionPlaneQuery:
    """
    决策平面查询服务

    聚合 Beta Gate、Alpha 触发器、配额和候选数据。

    Example:
        >>> query = DecisionPlaneQuery()
        >>> data = query.execute()
        >>> print(data.quota_remaining)
    """

    def execute(self, max_candidates: int = 5, max_pending: int = 10) -> DecisionPlaneData:
        """
        执行查询

        Args:
            max_candidates: 最大候选数量
            max_pending: 最大待处理请求数量

        Returns:
            DecisionPlaneData
        """
        all_actionable_candidates = self._get_actionable_candidates(max_count=None)
        listed_actionable_candidates = (
            all_actionable_candidates[:max_candidates]
            if max_candidates > 0
            else all_actionable_candidates
        )

        return DecisionPlaneData(
            beta_gate_visible_classes=self._get_beta_gate_visible_classes(),
            alpha_watch_count=self._get_alpha_status_count("WATCH"),
            alpha_candidate_count=self._get_alpha_status_count("CANDIDATE"),
            alpha_actionable_count=len(all_actionable_candidates),
            quota_total=self._get_quota_total(),
            quota_used=self._get_quota_used(),
            quota_remaining=self._get_quota_remaining(),
            quota_usage_percent=self._get_quota_usage_percent(),
            actionable_candidates=listed_actionable_candidates,
            pending_requests=self._get_pending_requests(max_pending),
        )

    def _get_beta_gate_visible_classes(self) -> str:
        """获取 Beta Gate 允许的可见资产类别"""
        try:
            from apps.beta_gate.application.config_summary_service import (
                get_beta_gate_config_summary_service,
            )

            beta_gate_context = get_beta_gate_config_summary_service().get_active_config_context()
            allowed_classes = beta_gate_context.get("allowed_asset_classes", [])
            if allowed_classes:
                return ", ".join(allowed_classes[:3])
            return "全部"
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get beta gate visible classes: {e}")
            return "-"

    def _get_alpha_status_count(self, status: str) -> int:
        """获取 Alpha 候选状态计数"""
        try:
            from apps.alpha_trigger.application.global_alert_service import (
                get_alpha_trigger_global_alert_service,
            )

            summary = get_alpha_trigger_global_alert_service().get_workspace_summary()
            key_by_status = {
                "WATCH": "alpha_watch_count",
                "CANDIDATE": "alpha_candidate_count",
                "ACTIONABLE": "alpha_actionable_count",
            }
            return int(summary.get(key_by_status.get(status, ""), 0))
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get alpha status count for {status}: {e}")
            return 0

    def _get_quota_total(self) -> int:
        """获取决策配额总数"""
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            quota = get_decision_rhythm_global_alert_service().get_weekly_quota_usage()
            return quota["quota_total"] if quota else 10
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get quota total: {e}")
            return 10

    def _get_quota_used(self) -> int:
        """获取已使用的决策配额"""
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            quota = get_decision_rhythm_global_alert_service().get_weekly_quota_usage()
            return quota["quota_used"] if quota else 0
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get quota used: {e}")
            return 0

    def _get_quota_remaining(self) -> int:
        """获取剩余决策配额"""
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            quota = get_decision_rhythm_global_alert_service().get_weekly_quota_usage()
            return quota["quota_remaining"] if quota else 10
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get quota remaining: {e}")
            return 10

    def _get_quota_usage_percent(self) -> float:
        """获取决策配额使用百分比"""
        total = self._get_quota_total()
        used = self._get_quota_used()
        if total > 0:
            return round(used / total * 100, 1)
        return 0.0

    def _attach_asset_names(self, items: list[Any]) -> list[Any]:
        """为候选或请求对象批量补充资产名称。"""
        lookup_codes: set[str] = set()
        for item in items:
            code = str(getattr(item, "asset_code", "") or "").strip().upper()
            if not code:
                continue
            lookup_codes.add(code)
            base_code = code.split(".")[0]
            if base_code:
                lookup_codes.add(base_code)

        if not lookup_codes:
            return items

        try:
            from apps.asset_analysis.application.asset_name_service import resolve_asset_names

            name_map = resolve_asset_names(list(lookup_codes))
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to resolve asset names for workflow panel: {e}")
            return items

        for item in items:
            existing_name = str(getattr(item, "asset_name", "") or "").strip()
            if existing_name:
                continue

            code = str(getattr(item, "asset_code", "") or "").strip()
            normalized_code = code.upper()
            if not normalized_code:
                continue

            base_code = normalized_code.split(".")[0]
            resolved_name = name_map.get(normalized_code) or name_map.get(base_code)
            if resolved_name:
                item.asset_name = resolved_name

        return items

    def _get_actionable_candidates(self, max_count: int | None) -> list[Any]:
        """获取可操作候选列表"""
        try:
            context_repo = get_dashboard_alpha_context_repository()
            candidates = context_repo.load_actionable_candidates(max_count=max_count)
            return self._attach_asset_names(candidates)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get actionable candidates: {e}")
            return []

    def _get_pending_requests(self, max_count: int | None) -> list[Any]:
        """获取待处理请求列表"""
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            requests = get_decision_rhythm_global_alert_service().list_pending_execution_requests()

            deduped = []
            seen_codes = set()
            for item in requests:
                code = (getattr(item, "asset_code", "") or "").upper()
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                deduped.append(item)
                if max_count is not None and len(deduped) >= max_count:
                    break

            return self._attach_asset_names(deduped)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get pending requests: {e}")
            return []


class AlphaDecisionChainQuery:
    """
    Alpha 决策链查询服务。

    将 Alpha Top N 排名、Workflow 可行动候选、待执行队列收束成统一视图，
    供 Dashboard 页面、API、SDK、MCP 共用。
    """

    def execute(
        self,
        top_n: int = 10,
        ic_days: int = 30,
        max_candidates: int = 5,
        max_pending: int = 10,
        user: Any | None = None,
    ) -> AlphaDecisionChainData:
        """执行 Alpha 决策链聚合查询。"""
        if user is not None:
            homepage_data = get_alpha_homepage_query().execute(user=user, top_n=top_n)
            alpha_visualization_data = AlphaVisualizationData(
                stock_scores=homepage_data.top_candidates,
                stock_scores_meta=dict(homepage_data.meta or {}),
                provider_status={},
                coverage_metrics={},
                ic_trends=[],
                ic_trends_meta={},
            )
        else:
            alpha_visualization_data = get_alpha_visualization_query().execute(
                top_n=top_n,
                ic_days=ic_days,
                user=user,
            )
        decision_plane_data = get_decision_plane_query().execute(
            max_candidates=max_candidates,
            max_pending=max_pending,
        )
        return self.build(
            alpha_visualization_data=alpha_visualization_data,
            decision_plane_data=decision_plane_data,
        )

    def build(
        self,
        *,
        alpha_visualization_data: AlphaVisualizationData,
        decision_plane_data: DecisionPlaneData,
    ) -> AlphaDecisionChainData:
        """用已获取的 Alpha 与 Workflow 数据构造统一决策链。"""
        top_stocks = [dict(item) for item in alpha_visualization_data.stock_scores]
        top_match_index = self._build_top_match_index(top_stocks)

        pending_matches = self._build_pending_matches(
            top_stocks,
            decision_plane_data.pending_requests,
        )
        actionable_matches = self._build_actionable_matches(
            top_stocks,
            decision_plane_data.actionable_candidates,
            pending_matches=pending_matches,
        )

        top_rank_only_count = 0
        top10_actionable_count = 0
        top10_pending_count = 0

        enriched_top_stocks: list[dict[str, Any]] = []
        for stock in top_stocks:
            canonical_code = str(stock.get("code") or "").strip().upper()
            actionable_match = actionable_matches.get(canonical_code)
            pending_match = pending_matches.get(canonical_code)

            if pending_match:
                workflow_stage = "pending"
                workflow_stage_label = "待执行队列"
                top10_pending_count += 1
            elif actionable_match:
                workflow_stage = "actionable"
                workflow_stage_label = "可行动候选"
                top10_actionable_count += 1
            else:
                workflow_stage = "top_ranked"
                workflow_stage_label = "仅在 Alpha Top 排名"
                top_rank_only_count += 1

            enriched_stock = dict(stock)
            enriched_stock.update(
                {
                    "workflow_stage": workflow_stage,
                    "workflow_stage_label": workflow_stage_label,
                    "is_actionable": bool(actionable_match),
                    "is_pending": bool(pending_match),
                    "candidate_id": (
                        actionable_match.get("candidate_id") if actionable_match else None
                    ),
                    "pending_request_id": (
                        pending_match.get("request_id") if pending_match else None
                    ),
                    "pending_execution_status": (
                        pending_match.get("execution_status") if pending_match else None
                    ),
                }
            )
            enriched_top_stocks.append(enriched_stock)

        actionable_candidates = [
            self._serialize_actionable_candidate(item, top_match_index)
            for item in decision_plane_data.actionable_candidates
        ]
        pending_requests = [
            self._serialize_pending_request(item, top_match_index)
            for item in decision_plane_data.pending_requests
        ]

        actionable_outside_top10_count = sum(
            1 for item in actionable_candidates if not item["is_in_top10"]
        )
        pending_outside_top10_count = sum(1 for item in pending_requests if not item["is_in_top10"])

        overview = {
            "top_ranked_count": len(enriched_top_stocks),
            "actionable_count": len(actionable_candidates),
            "actionable_total_count": decision_plane_data.alpha_actionable_count,
            "pending_count": len(pending_requests),
            "top10_actionable_count": top10_actionable_count,
            "top10_pending_count": top10_pending_count,
            "top10_rank_only_count": top_rank_only_count,
            "actionable_outside_top10_count": actionable_outside_top10_count,
            "pending_outside_top10_count": pending_outside_top10_count,
            "actionable_conversion_pct": (
                round((top10_actionable_count / len(enriched_top_stocks) * 100), 1)
                if enriched_top_stocks
                else 0.0
            ),
            "pending_conversion_pct": (
                round((top10_pending_count / len(enriched_top_stocks) * 100), 1)
                if enriched_top_stocks
                else 0.0
            ),
            "requested_trade_date": alpha_visualization_data.stock_scores_meta.get(
                "requested_trade_date"
            ),
            "effective_asof_date": alpha_visualization_data.stock_scores_meta.get(
                "effective_asof_date"
            ),
        }

        return AlphaDecisionChainData(
            overview=overview,
            top_stocks=enriched_top_stocks,
            actionable_candidates=actionable_candidates,
            pending_requests=pending_requests,
        )

    def _build_code_aliases(self, code: str) -> set[str]:
        """为关系匹配构建代码别名。"""
        normalized = str(code or "").strip().upper()
        if not normalized:
            return set()

        aliases = {normalized}
        base_code = normalized.split(".")[0]
        if base_code:
            aliases.add(base_code)
        return aliases

    def _normalize_code(self, code: str) -> str:
        """统一比较时的 canonical code。"""
        normalized = str(code or "").strip().upper()
        return normalized

    def _build_top_match_index(self, top_stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """构建 Top N 股票的代码别名索引。"""
        index: dict[str, dict[str, Any]] = {}
        for stock in top_stocks:
            for alias in self._build_code_aliases(stock.get("code", "")):
                index[alias] = stock
        return index

    def _match_top_stock(
        self,
        top_match_index: dict[str, dict[str, Any]],
        code: str,
    ) -> dict[str, Any] | None:
        """根据候选/请求代码匹配当前 Top N 股票。"""
        for alias in self._build_code_aliases(code):
            matched = top_match_index.get(alias)
            if matched:
                return matched
        return None

    def _build_top_lookup_codes(self, top_stocks: list[dict[str, Any]]) -> list[str]:
        """构建 Top N 对应的数据库查询代码集合。"""
        lookup_codes: set[str] = set()
        for stock in top_stocks:
            lookup_codes.update(self._build_code_aliases(stock.get("code", "")))
        return sorted(lookup_codes)

    def _build_pending_matches(
        self,
        top_stocks: list[dict[str, Any]],
        pending_requests: list[Any],
    ) -> dict[str, dict[str, Any]]:
        """基于已加载的待执行请求构建 Top N 命中关系。"""
        if not top_stocks or not pending_requests:
            return {}

        top_match_index = self._build_top_match_index(top_stocks)
        matched: dict[str, dict[str, Any]] = {}
        for item in pending_requests:
            top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
            if not top_stock:
                continue
            canonical_code = self._normalize_code(top_stock.get("code", ""))
            if canonical_code in matched:
                continue
            matched[canonical_code] = {
                "request_id": getattr(item, "request_id", ""),
                "execution_status": getattr(item, "execution_status", ""),
            }
        return matched

    def _build_actionable_matches(
        self,
        top_stocks: list[dict[str, Any]],
        actionable_candidates: list[Any],
        *,
        pending_matches: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """基于已加载的可行动候选构建 Top N 命中关系。"""
        if not top_stocks or not actionable_candidates:
            return {}

        pending_codes = set(pending_matches.keys())
        top_match_index = self._build_top_match_index(top_stocks)
        matched: dict[str, dict[str, Any]] = {}
        for item in actionable_candidates:
            top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
            if not top_stock:
                continue
            canonical_code = self._normalize_code(top_stock.get("code", ""))
            if canonical_code in matched or canonical_code in pending_codes:
                continue
            matched[canonical_code] = {
                "candidate_id": getattr(item, "candidate_id", ""),
                "direction": getattr(item, "direction", ""),
                "confidence": getattr(item, "confidence", None),
            }
        return matched

    def _serialize_actionable_candidate(
        self,
        item: Any,
        top_match_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """序列化可行动候选并补充当前 Top N 关系。"""
        top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
        return {
            "candidate_id": getattr(item, "candidate_id", ""),
            "asset_code": getattr(item, "asset_code", ""),
            "asset_name": getattr(item, "asset_name", ""),
            "direction": getattr(item, "direction", ""),
            "confidence": getattr(item, "confidence", None),
            "asset_class": getattr(item, "asset_class", ""),
            "valuation_repair": getattr(item, "valuation_repair", None),
            "is_in_top10": bool(top_stock),
            "current_top_rank": top_stock.get("rank") if top_stock else None,
            "current_top_score": top_stock.get("score") if top_stock else None,
            "current_top_source": top_stock.get("source") if top_stock else None,
            "origin_stage_label": (
                f"当前 Top 10 第 #{top_stock.get('rank')}" if top_stock else "当前不在 Top 10"
            ),
            "chain_stage": "actionable",
            "chain_stage_label": "可行动候选",
        }

    def _serialize_pending_request(
        self,
        item: Any,
        top_match_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """序列化待执行请求并补充当前 Top N 关系。"""
        top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
        return {
            "request_id": getattr(item, "request_id", ""),
            "asset_code": getattr(item, "asset_code", ""),
            "asset_name": getattr(item, "asset_name", ""),
            "direction": getattr(item, "direction", ""),
            "execution_status": getattr(item, "execution_status", ""),
            "is_in_top10": bool(top_stock),
            "current_top_rank": top_stock.get("rank") if top_stock else None,
            "current_top_score": top_stock.get("score") if top_stock else None,
            "current_top_source": top_stock.get("source") if top_stock else None,
            "origin_stage_label": (
                f"当前 Top 10 第 #{top_stock.get('rank')}" if top_stock else "当前不在 Top 10"
            ),
            "chain_stage": "pending",
            "chain_stage_label": "待执行队列",
        }


# ============================================================================
# Regime Summary Query Service
# ============================================================================


@dataclass(frozen=True)
class RegimeSummaryData:
    """Regime 摘要数据"""

    current_regime: str
    regime_date: date | None
    regime_confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    pmi_value: float | None
    cpi_value: float | None
    regime_distribution: dict[str, int]
    regime_data_health: bool
    regime_warnings: list[str]


class RegimeSummaryQuery:
    """
    Regime 摘要查询服务

    聚合当前 Regime 状态和宏观指标数据。

    Example:
        >>> query = RegimeSummaryQuery()
        >>> data = query.execute()
        >>> print(data.current_regime)
    """

    def execute(self, user_id: int | None = None) -> RegimeSummaryData:
        """
        执行查询

        Args:
            user_id: 用户 ID（用于某些个性化数据）

        Returns:
            RegimeSummaryData
        """
        try:
            from apps.regime.application.repository_provider import get_regime_repository

            regime_repo = get_regime_repository()
            current_state = regime_repo.get_current_regime()

            if current_state:
                return RegimeSummaryData(
                    current_regime=current_state.dominant_regime or "Unknown",
                    regime_date=current_state.observed_at,
                    regime_confidence=float(current_state.confidence or 0.0),
                    growth_momentum_z=float(current_state.growth_momentum_z),
                    inflation_momentum_z=float(current_state.inflation_momentum_z),
                    pmi_value=self._get_latest_macro_value("PMI"),
                    cpi_value=self._get_latest_macro_value("CPI"),
                    regime_distribution={},
                    regime_data_health=True,
                    regime_warnings=[],
                )

            # 返回默认值
            return RegimeSummaryData(
                current_regime="Unknown",
                regime_date=None,
                regime_confidence=0.0,
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                pmi_value=None,
                cpi_value=None,
                regime_distribution={},
                regime_data_health=False,
                regime_warnings=["No regime data available"],
            )

        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get regime summary: {e}")
            return RegimeSummaryData(
                current_regime="Unknown",
                regime_date=None,
                regime_confidence=0.0,
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                pmi_value=None,
                cpi_value=None,
                regime_distribution={},
                regime_data_health=False,
                regime_warnings=[str(e)],
            )

    def _get_latest_macro_value(self, indicator_code: str) -> float | None:
        """获取最新宏观指标值"""
        try:
            return get_dashboard_query_repository().get_latest_macro_indicator_value(indicator_code)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.debug(f"Failed to get macro value for {indicator_code}: {e}")
            return None


class DashboardDetailQuery:
    """Dashboard 详情查询服务。"""

    def get_position_detail(self, user_id: int, asset_code: str) -> dict[str, Any]:
        """获取持仓详情和相关信号。"""
        try:
            return get_dashboard_query_repository().get_position_detail(
                user_id=user_id,
                asset_code=asset_code,
            )
        except ValueError as e:
            position_error = str(e)
            if "position not found" in position_error.lower():
                return {
                    "position": None,
                    "related_signals": [],
                    "asset_code": asset_code,
                    "error": f"未找到持仓 {asset_code}",
                }
            logger.warning(f"Failed to get position detail for {asset_code}: {e}")
            return {
                "position": None,
                "related_signals": [],
                "asset_code": asset_code,
                "error": position_error,
            }
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as e:
            logger.warning(f"Failed to get position detail for {asset_code}: {e}")
            return {
                "position": None,
                "related_signals": [],
                "asset_code": asset_code,
                "error": str(e),
            }

    def generate_alpha_candidates(self) -> dict[str, int]:
        """批量生成 Alpha 候选并返回统计结果。"""
        from apps.alpha_trigger.application.repository_provider import (
            get_alpha_candidate_repository,
            get_alpha_trigger_repository,
        )
        from apps.alpha_trigger.application.use_cases import (
            GenerateCandidateRequest,
            GenerateCandidateUseCase,
        )
        from apps.alpha_trigger.domain.entities import CandidateStatus

        trigger_repo = get_alpha_trigger_repository()
        candidate_repo = get_alpha_candidate_repository()
        use_case = GenerateCandidateUseCase(trigger_repo, candidate_repo)
        generation_context = (
            get_dashboard_query_repository().load_alpha_candidate_generation_context()
        )
        active_triggers = generation_context["active_triggers"]
        existing_trigger_ids = generation_context["existing_trigger_ids"]

        generated = 0
        promoted = 0
        failed = 0
        skipped = 0

        for trigger in active_triggers:
            if trigger.trigger_id in existing_trigger_ids:
                skipped += 1
                continue

            resp = use_case.execute(
                GenerateCandidateRequest(
                    trigger_id=trigger.trigger_id,
                    time_window_days=90,
                )
            )
            if not resp.success or not resp.candidate:
                failed += 1
                continue

            generated += 1
            if float(resp.candidate.confidence or 0) >= 0.70:
                try:
                    candidate_repo.update_status(
                        resp.candidate.candidate_id, CandidateStatus.ACTIONABLE
                    )
                    promoted += 1
                except (DatabaseError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Failed to promote Alpha candidate %s to ACTIONABLE: %s",
                        getattr(resp.candidate, "candidate_id", None),
                        exc,
                    )

        return {
            "generated": generated,
            "promoted_to_actionable": promoted,
            "skipped_existing": skipped,
            "failed": failed,
            "active_trigger_count": len(active_triggers),
            "actionable_count": generation_context["actionable_count"],
        }


# ============================================================================
# Singleton accessors
# ============================================================================

_alpha_visualization_query: AlphaVisualizationQuery | None = None
_decision_plane_query: DecisionPlaneQuery | None = None
_alpha_decision_chain_query: AlphaDecisionChainQuery | None = None
_alpha_homepage_query = None
_regime_summary_query: RegimeSummaryQuery | None = None
_dashboard_detail_query: DashboardDetailQuery | None = None


def get_alpha_visualization_query() -> AlphaVisualizationQuery:
    """获取 Alpha 可视化查询服务单例"""
    global _alpha_visualization_query
    if _alpha_visualization_query is None:
        _alpha_visualization_query = AlphaVisualizationQuery()
    return _alpha_visualization_query


def get_decision_plane_query() -> DecisionPlaneQuery:
    """获取决策平面查询服务单例"""
    global _decision_plane_query
    if _decision_plane_query is None:
        _decision_plane_query = DecisionPlaneQuery()
    return _decision_plane_query


def get_alpha_decision_chain_query() -> AlphaDecisionChainQuery:
    """获取 Alpha 决策链查询服务单例"""
    global _alpha_decision_chain_query
    if _alpha_decision_chain_query is None:
        _alpha_decision_chain_query = AlphaDecisionChainQuery()
    return _alpha_decision_chain_query


def get_alpha_homepage_query():
    """获取 Alpha 首页候选查询服务单例。"""
    global _alpha_homepage_query
    if _alpha_homepage_query is None:
        from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery

        _alpha_homepage_query = AlphaHomepageQuery()
    return _alpha_homepage_query


def get_regime_summary_query() -> RegimeSummaryQuery:
    """获取 Regime 摘要查询服务单例"""
    global _regime_summary_query
    if _regime_summary_query is None:
        _regime_summary_query = RegimeSummaryQuery()
    return _regime_summary_query


def get_dashboard_detail_query() -> DashboardDetailQuery:
    """获取 dashboard 详情查询服务单例。"""
    global _dashboard_detail_query
    if _dashboard_detail_query is None:
        _dashboard_detail_query = DashboardDetailQuery()
    return _dashboard_detail_query
