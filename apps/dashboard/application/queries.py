"""
Dashboard Query Services.

Application 层查询服务，为 Dashboard 视图提供数据聚合。

重构说明 (2026-03-11):
- 将跨模块数据获取逻辑从 views.py 移至 Query Services
- 隐藏 ORM 实现细节
- 提供简化的 API 给视图层使用
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as django_timezone

from apps.alpha.domain.entities import AlphaResult
from apps.dashboard.application.detail_queries import DashboardDetailQuery as DashboardDetailQuery
from apps.dashboard.application.detail_queries import RegimeSummaryData as RegimeSummaryData
from apps.dashboard.application.detail_queries import RegimeSummaryQuery as RegimeSummaryQuery
from apps.dashboard.application.query_value_helpers import (
    DEGRADED_DASHBOARD_QUERY_EXCEPTIONS,
    _bounded_text,
    _string_keyed_mapping,
)
from apps.dashboard.application.repository_provider import (
    get_dashboard_alpha_context_repository,
    get_dashboard_query_repository,
)
from apps.regime.application.current_regime import resolve_current_regime as resolve_current_regime

if TYPE_CHECKING:
    from apps.dashboard.application.alpha_decision_chain_query import (
        AlphaDecisionChainQuery as AlphaDecisionChainQuery,
    )
    from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery

logger = logging.getLogger(__name__)

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
            attempts: list[tuple[str, AlphaResult]] = []
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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get alpha stock scores: error_type=%s", type(exc).__name__)
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
        result: AlphaResult,
        *,
        selected_provider: str,
        attempts: list[tuple[str, AlphaResult]],
    ) -> AlphaResult:
        """Attach dashboard-specific freshness hints when the page falls back from realtime qlib."""
        metadata = _string_keyed_mapping(result.metadata)
        qlib_attempt = next(
            (candidate for provider, candidate in attempts if provider == "qlib"), None
        )
        if (
            selected_provider != "qlib"
            and qlib_attempt is not None
            and not getattr(qlib_attempt, "success", False)
        ):
            qlib_metadata = _string_keyed_mapping(qlib_attempt.metadata)
            qlib_notice = _string_keyed_mapping(qlib_metadata.get("reliability_notice"))
            refresh_triggered = bool(qlib_metadata.get("async_task_triggered"))
            stable_reason = (
                "实时 Qlib 结果尚未就绪，系统已触发异步推理任务"
                if refresh_triggered
                else "实时 Qlib 结果尚未就绪"
            )
            fallback_reason = _bounded_text(
                qlib_notice.get("message"),
                default=stable_reason,
            )
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

    def _build_stock_scores_meta(self, result: AlphaResult) -> dict[str, Any]:
        """Build template/API-friendly metadata for Alpha score reliability."""
        metadata = _string_keyed_mapping(result.metadata)
        notice = _string_keyed_mapping(metadata.get("reliability_notice"))
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
        except (ImportError, ImproperlyConfigured) as exc:
            logger.debug("Failed to import asset name resolver: error_type=%s", type(exc).__name__)
            return {}

        lookup_codes = sorted({alias for aliases in code_aliases.values() for alias in aliases})
        try:
            resolved_lookup_map = resolve_asset_names(lookup_codes)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.debug("Failed to resolve security names: error_type=%s", type(exc).__name__)
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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get alpha provider status: error_type=%s", type(exc).__name__)
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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning(
                "Failed to get lightweight alpha provider status: error_type=%s",
                type(exc).__name__,
            )
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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning(
                "Failed to get alpha coverage metrics: error_type=%s", type(exc).__name__
            )
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

        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get alpha IC trends: error_type=%s", type(exc).__name__)
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
    quota_available: bool = True


@dataclass(frozen=True)
class DecisionQuotaData:
    """Consistent weekly decision-quota snapshot."""

    total: int
    used: int
    remaining: int
    usage_percent: float
    available: bool


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

    def execute(
        self,
        max_candidates: int = 5,
        max_pending: int = 10,
        user_id: int | None = None,
    ) -> DecisionPlaneData:
        """
        执行查询

        Args:
            max_candidates: 最大候选数量
            max_pending: 最大待处理请求数量
            user_id: 用户 ID；提供时仅返回该用户账户的待执行请求

        Returns:
            DecisionPlaneData
        """
        all_actionable_candidates = self._get_actionable_candidates(
            max_count=None,
            user_id=user_id,
        )
        listed_actionable_candidates = (
            all_actionable_candidates[:max_candidates]
            if max_candidates > 0
            else all_actionable_candidates
        )
        quota = self._get_quota_usage()

        return DecisionPlaneData(
            beta_gate_visible_classes=self._get_beta_gate_visible_classes(),
            alpha_watch_count=self._get_alpha_status_count("WATCH"),
            alpha_candidate_count=self._get_alpha_status_count("CANDIDATE"),
            alpha_actionable_count=len(all_actionable_candidates),
            quota_total=quota.total,
            quota_used=quota.used,
            quota_remaining=quota.remaining,
            quota_usage_percent=quota.usage_percent,
            actionable_candidates=listed_actionable_candidates,
            pending_requests=self._get_pending_requests(max_pending, user_id=user_id),
            quota_available=quota.available,
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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning(
                "Failed to get beta gate visible classes: error_type=%s", type(exc).__name__
            )
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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get alpha status count: error_type=%s", type(exc).__name__)
            return 0

    def _get_quota_total(self) -> int:
        """获取决策配额总数"""
        return self._get_quota_usage().total

    def _get_quota_used(self) -> int:
        """获取已使用的决策配额"""
        return self._get_quota_usage().used

    def _get_quota_remaining(self) -> int:
        """获取剩余决策配额"""
        return self._get_quota_usage().remaining

    def _get_quota_usage_percent(self) -> float:
        """获取决策配额使用百分比"""
        return self._get_quota_usage().usage_percent

    def _get_quota_usage(self) -> DecisionQuotaData:
        """Load and validate one coherent weekly quota snapshot."""

        unavailable = DecisionQuotaData(
            total=0,
            used=0,
            remaining=0,
            usage_percent=0.0,
            available=False,
        )
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            quota = get_decision_rhythm_global_alert_service().get_weekly_quota_usage()
            if not isinstance(quota, dict):
                return unavailable
            total = self._non_negative_int(quota.get("quota_total"))
            used = self._non_negative_int(quota.get("quota_used"))
            remaining = self._non_negative_int(quota.get("quota_remaining"))
            if (
                total is None
                or used is None
                or remaining is None
                or used > total
                or remaining != total - used
            ):
                logger.warning("Decision quota snapshot is incomplete or inconsistent")
                return unavailable
            return DecisionQuotaData(
                total=total,
                used=used,
                remaining=remaining,
                usage_percent=round(used / total * 100, 1) if total > 0 else 0.0,
                available=True,
            )
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get decision quota snapshot: %s", exc)
            return unavailable

    @staticmethod
    def _non_negative_int(value: object) -> int | None:
        """Return an exact non-negative integer without coercing fractions or booleans."""

        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.isdigit():
                return int(normalized)
        return None

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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning(
                "Failed to resolve asset names for workflow panel: error_type=%s",
                type(exc).__name__,
            )
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

    def _get_actionable_candidates(
        self,
        max_count: int | None,
        *,
        user_id: int | None = None,
    ) -> list[Any]:
        """获取可操作候选列表，并按用户账户范围排除待执行标的。"""
        try:
            context_repo = get_dashboard_alpha_context_repository()
            if user_id is None:
                candidates = context_repo.load_actionable_candidates(max_count=max_count)
            else:
                candidates = context_repo.load_actionable_candidates(
                    max_count=max_count,
                    user_id=user_id,
                )
            return self._attach_asset_names(candidates)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get actionable candidates: error_type=%s", type(exc).__name__)
            return []

    def _get_pending_requests(
        self,
        max_count: int | None,
        *,
        user_id: int | None = None,
    ) -> list[Any]:
        """获取待处理请求列表；用户页面必须传入 ``user_id``。"""
        try:
            if user_id is None:
                from apps.decision_rhythm.application.global_alert_service import (
                    get_decision_rhythm_global_alert_service,
                )

                requests = (
                    get_decision_rhythm_global_alert_service().list_pending_execution_requests()
                )
            else:
                requests = get_dashboard_alpha_context_repository().load_pending_requests(
                    max_count=max_count,
                    user_id=user_id,
                )

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
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get pending requests: error_type=%s", type(exc).__name__)
            return []


# ============================================================================
# Singleton accessors
# ============================================================================

_alpha_visualization_query: AlphaVisualizationQuery | None = None
_decision_plane_query: DecisionPlaneQuery | None = None
_alpha_decision_chain_query: AlphaDecisionChainQuery | None = None
_alpha_homepage_query: AlphaHomepageQuery | None = None
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
        from apps.dashboard.application.alpha_decision_chain_query import AlphaDecisionChainQuery

        _alpha_decision_chain_query = AlphaDecisionChainQuery()
    return _alpha_decision_chain_query


def get_alpha_homepage_query() -> AlphaHomepageQuery:
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


def __getattr__(name: str) -> Any:
    """Resolve split query classes while preserving the public import path."""

    if name == "AlphaDecisionChainQuery":
        from apps.dashboard.application.alpha_decision_chain_query import AlphaDecisionChainQuery

        return AlphaDecisionChainQuery
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
