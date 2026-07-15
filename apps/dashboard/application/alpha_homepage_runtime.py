"""Alpha runtime, refresh, and readiness behavior for the Dashboard homepage."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult
from core.integration.runtime_imports import get_celery_health_checker, record_pending_task

logger = logging.getLogger(__name__)

ALPHA_SCOPE_GENERAL = "general"
ALPHA_SCOPE_PORTFOLIO = "portfolio"


class AlphaRuntimeMixin:
    """Private behavior shard for AlphaHomepageQuery."""

    def _fetch_general_alpha_result(self, *, user, trade_date: date, top_n: int):
        result = None
        for provider_name in ("qlib", "cache", "simple", "etf"):
            candidate = self.alpha_service.get_stock_scores(
                universe_id="csi300",
                intended_trade_date=trade_date,
                top_n=top_n,
                user=user,
                provider_filter=provider_name,
            )
            result = candidate
            if candidate.success and candidate.scores:
                return candidate
        return result or AlphaResult(
            success=False,
            scores=[],
            source="none",
            timestamp=trade_date.isoformat(),
            status="unavailable",
            error_message="general_alpha_unavailable",
            metadata={},
        )

    def _mark_general_research_only(self, *, result, trade_date: date) -> None:
        metadata = dict(getattr(result, "metadata", {}) or {})
        metadata.update(
            {
                "alpha_scope": ALPHA_SCOPE_GENERAL,
                "research_only": True,
                "must_not_use_for_decision": True,
                "recommendation_ready": False,
                "requested_trade_date": metadata.get("requested_trade_date")
                or trade_date.isoformat(),
                "reliability_notice": {
                    "level": "info",
                    "code": "general_alpha_research_only",
                    "title": "通用 Alpha 仅供研究",
                    "message": "通用 Alpha 使用 broader/universe 级结果，只展示研究排名，不作为账户专属可执行建议。",
                },
            }
        )
        result.metadata = metadata

    @staticmethod
    def _build_general_scope(*, trade_date: date, instrument_codes: list[str]) -> AlphaPoolScope:
        return AlphaPoolScope(
            pool_type="general_universe",
            market="CN",
            pool_mode="general",
            instrument_codes=tuple(instrument_codes),
            selection_reason="通用市场研究股票池，不绑定任何账户、组合或仓位约束。",
            trade_date=trade_date,
            display_label="通用 Alpha 研究池",
            portfolio_id=None,
            portfolio_name="通用研究池",
        )

    def _fetch_alpha_result(self, *, user, scope, trade_date: date, top_n: int):
        result = None
        broader_cache_candidate = None
        for provider_name in ("cache", "simple"):
            candidate = self.alpha_service.get_stock_scores(
                universe_id=scope.universe_id,
                intended_trade_date=trade_date,
                top_n=top_n,
                user=user,
                provider_filter=provider_name,
                pool_scope=scope,
            )
            result = candidate
            if candidate.success and candidate.scores:
                metadata = dict(getattr(candidate, "metadata", {}) or {})
                if metadata.get("derived_from_broader_cache"):
                    broader_cache_candidate = candidate
                    async_status = self._trigger_async_inference_if_needed(
                        user=user,
                        scope=scope,
                        trade_date=trade_date,
                        top_n=top_n,
                    )
                    metadata.update(
                        {
                            "refresh_triggered": bool(async_status.get("refresh_triggered", False)),
                            "refresh_status": async_status.get("refresh_status", ""),
                            "async_task_id": async_status.get("async_task_id", ""),
                            "poll_after_ms": async_status.get("poll_after_ms", 5000),
                            "auto_refresh_message": async_status.get("message", ""),
                            "auto_refresh_error": async_status.get("auto_refresh_error", ""),
                        }
                    )
                    candidate.metadata = metadata
                    continue
                return candidate
        if broader_cache_candidate is not None:
            return broader_cache_candidate
        if result is not None:
            async_status = self._trigger_async_inference_if_needed(
                user=user,
                scope=scope,
                trade_date=trade_date,
                top_n=top_n,
            )
            self._mark_no_verified_recommendation(
                result=result,
                scope=scope,
                async_status=async_status,
            )
        return result

    def _trigger_async_inference_if_needed(
        self,
        *,
        user,
        scope,
        trade_date: date,
        top_n: int,
    ) -> dict[str, Any]:
        """Queue scoped Qlib inference once per short window when verified cache is missing."""
        if user is not None and not getattr(user, "is_authenticated", False):
            return {"refresh_status": "skipped", "message": "匿名用户不自动触发账户池推理。"}

        celery_health = self._get_async_refresh_celery_health()
        if not bool(celery_health.get("available", False)):
            reason = str(celery_health.get("reason") or "unavailable")
            return {
                "refresh_triggered": False,
                "refresh_status": "skipped",
                "poll_after_ms": 5000,
                "auto_refresh_error": reason,
                "message": "未检测到可用 Celery worker，首页不自动触发后台推理；请手动点击“立即推理刷新”。",
            }

        lock_key = ""
        lock_acquired = False
        try:
            from django.core.cache import cache

            lock_key = (
                "dashboard:alpha:auto-refresh:"
                f"{getattr(scope, 'scope_hash', '')}:{trade_date.isoformat()}:{top_n}"
            )
            if not cache.add(lock_key, "queued", timeout=300):
                return {
                    "refresh_triggered": False,
                    "refresh_status": "recently_queued",
                    "poll_after_ms": 5000,
                    "message": "账户池 Alpha 推理已在后台排队，请稍后刷新。",
                }
            lock_acquired = True

            from apps.alpha.application.tasks import qlib_predict_scores

            task = qlib_predict_scores.delay(
                scope.universe_id,
                trade_date.isoformat(),
                top_n,
                scope_payload=scope.to_dict(),
            )
            record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_predict_scores",
                args=(scope.universe_id, trade_date.isoformat(), top_n),
                kwargs={"scope_payload": scope.to_dict()},
            )
            return {
                "refresh_triggered": True,
                "refresh_status": "queued",
                "async_task_id": getattr(task, "id", ""),
                "poll_after_ms": 5000,
                "message": "账户池暂无可信 Alpha cache，已自动触发后台 Qlib 推理。",
            }
        except Exception as exc:
            if lock_acquired and lock_key:
                try:
                    cache.delete(lock_key)
                except Exception:
                    logger.debug(
                        "Failed to release homepage alpha auto-refresh lock after error.",
                        exc_info=True,
                    )
            logger.warning("Failed to auto trigger scoped Alpha inference: %s", exc, exc_info=True)
            return {
                "refresh_triggered": False,
                "refresh_status": "failed",
                "auto_refresh_error": str(exc),
                "message": "账户池 Alpha 推理自动触发失败，请手动重试。",
            }

    @staticmethod
    def _get_async_refresh_celery_health() -> dict[str, Any]:
        """Return whether homepage auto-refresh currently has a live Celery worker."""
        try:
            health = get_celery_health_checker().check_health()
            active_workers = list(getattr(health, "active_workers", []) or [])
            if active_workers and bool(getattr(health, "is_healthy", False)):
                return {"available": True, "active_workers": active_workers, "reason": "healthy"}
            if not active_workers:
                return {"available": False, "active_workers": [], "reason": "no_active_workers"}
            return {"available": False, "active_workers": active_workers, "reason": "unhealthy"}
        except Exception as exc:
            logger.warning(
                "Failed to inspect Celery health for homepage alpha auto refresh: %s", exc
            )
            return {
                "available": False,
                "active_workers": [],
                "reason": "health_check_failed",
                "error": str(exc),
            }

    def _mark_no_verified_recommendation(
        self,
        *,
        result,
        scope,
        async_status: dict[str, Any] | None = None,
    ) -> None:
        metadata = dict(getattr(result, "metadata", {}) or {})
        async_status = dict(async_status or {})
        scope_label = getattr(scope, "display_label", "") or "账户驱动 Alpha 池"
        reason = (
            f"{scope_label} 暂无真实账户池 Alpha 推理或缓存结果；系统未使用硬编码股票池、"
            "默认 ETF 或静态名单生成推荐。请触发实时推理后再查看。"
        )
        metadata.update(
            {
                "is_degraded": True,
                "uses_cached_data": False,
                "fallback_mode": "none",
                "fallback_reason": "",
                "no_recommendation_reason": reason,
                "hardcoded_fallback_used": False,
                "refresh_triggered": bool(async_status.get("refresh_triggered", False)),
                "refresh_status": async_status.get("refresh_status", ""),
                "async_task_id": async_status.get("async_task_id", ""),
                "poll_after_ms": async_status.get("poll_after_ms", 5000),
                "auto_refresh_message": async_status.get("message", ""),
                "auto_refresh_error": async_status.get("auto_refresh_error", ""),
                "scope_hash": getattr(scope, "scope_hash", ""),
                "scope_label": scope_label,
                "scope_metadata": scope.to_dict() if hasattr(scope, "to_dict") else {},
                "reliability_notice": {
                    "level": "warning",
                    "code": "no_verified_alpha_recommendation",
                    "title": "暂无可信 Alpha 推荐",
                    "message": reason,
                },
            }
        )
        result.metadata = metadata
        result.status = "unavailable"

    def _attach_scope_resolution_metadata(self, *, result, resolved_pool) -> None:
        metadata = dict(getattr(result, "metadata", {}) or {})
        metadata.update(
            {
                "requested_pool_mode": resolved_pool.requested_pool_mode,
                "requested_pool_size": resolved_pool.requested_pool_size,
                "effective_pool_mode": resolved_pool.scope.pool_mode,
                "effective_pool_size": resolved_pool.scope.pool_size,
                "scope_fallback": resolved_pool.scope_fallback,
                "scope_fallback_reason": resolved_pool.fallback_reason,
                "scope_fallback_universe_id": resolved_pool.scope.universe_id,
            }
        )
        if resolved_pool.scope_fallback and not metadata.get("reliability_notice"):
            metadata["reliability_notice"] = {
                "level": "warning",
                "code": "account_scope_widened",
                "title": "Alpha 已自动扩大账户池范围",
                "message": resolved_pool.fallback_reason,
            }
        result.metadata = metadata

    @staticmethod
    def _parse_meta_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    def _build_readiness_fields(
        self, *, alpha_result, scope, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        requested_trade_date = self._parse_meta_date(metadata.get("requested_trade_date"))
        effective_asof_date = self._parse_meta_date(metadata.get("effective_asof_date"))
        result_age_days = getattr(alpha_result, "staleness_days", None)
        if result_age_days is None and requested_trade_date and effective_asof_date:
            result_age_days = max((requested_trade_date - effective_asof_date).days, 0)

        derived_from_broader_cache = bool(metadata.get("derived_from_broader_cache", False))
        scope_fallback = bool(metadata.get("scope_fallback", False))
        trade_date_adjusted = bool(metadata.get("trade_date_adjusted", False))
        latest_available_qlib_result = bool(metadata.get("latest_available_qlib_result", False))
        adjusted_to_latest_completed_session = (
            trade_date_adjusted
            and requested_trade_date is not None
            and effective_asof_date is not None
            and requested_trade_date.weekday() >= 5
            and 0 <= (requested_trade_date - effective_asof_date).days <= 3
        )
        hardcoded_fallback_used = bool(metadata.get("hardcoded_fallback_used", False))
        is_degraded = bool(metadata.get("is_degraded", False))
        research_only = bool(metadata.get("research_only", False)) or (
            metadata.get("alpha_scope") == ALPHA_SCOPE_GENERAL
        )
        broad_pool_research_only = not research_only and getattr(scope, "pool_mode", "") in {
            "market",
            "price_covered",
        }
        no_recommendation_reason = str(metadata.get("no_recommendation_reason") or "")
        fallback_mode = str(metadata.get("fallback_mode") or "")
        scores = list(getattr(alpha_result, "scores", []) or [])
        provider_source = (
            str(metadata.get("provider_source") or getattr(alpha_result, "source", ""))
            .strip()
            .lower()
        )
        data_driven_simple_result = (
            provider_source == "simple"
            and str(metadata.get("factor_basis") or "") in {"quote_momentum", ""}
            and bool(scores)
        )

        scope_verification_status = "verified"
        if not scores:
            scope_verification_status = "unavailable"
        elif research_only:
            scope_verification_status = "general_universe"
        elif derived_from_broader_cache:
            scope_verification_status = "derived_from_broader_cache"
        elif scope_fallback:
            scope_verification_status = "scope_fallback"

        freshness_status = "fresh"
        if not scores:
            freshness_status = "unavailable"
        elif adjusted_to_latest_completed_session:
            freshness_status = "latest_completed_session"
        elif trade_date_adjusted:
            freshness_status = "trade_date_adjusted"
        elif fallback_mode == "forward_fill_latest_qlib_cache":
            freshness_status = "forward_filled_cache"
        elif result_age_days not in (None, 0):
            freshness_status = "stale"
        elif data_driven_simple_result:
            freshness_status = "fresh"
        elif is_degraded or not latest_available_qlib_result:
            freshness_status = "degraded"

        blocked_reason = ""
        readiness_status = "ready"
        recommendation_ready = bool(scores)
        if no_recommendation_reason:
            readiness_status = "blocked_no_verified_result"
            blocked_reason = no_recommendation_reason
            recommendation_ready = False
        elif research_only:
            readiness_status = "research_only"
            blocked_reason = "通用 Alpha 仅用于研究排名；未绑定账户 scope，不能作为真实交易决策。"
            recommendation_ready = False
        elif hardcoded_fallback_used:
            readiness_status = "blocked_hardcoded_fallback"
            blocked_reason = "当前结果仍含硬编码回退痕迹，不能作为真实 Alpha 推荐。"
            recommendation_ready = False
        elif derived_from_broader_cache:
            readiness_status = "blocked_broader_scope_cache"
            blocked_reason = (
                "当前结果来自 broader-scope cache 映射，账户专属 scoped Alpha 推理尚未完成。"
            )
            recommendation_ready = False
        elif scope_fallback:
            readiness_status = "blocked_scope_fallback"
            blocked_reason = str(
                metadata.get("scope_fallback_reason")
                or "当前 Alpha 股票池已扩大到回退范围，不能视为原始账户池推荐。"
            )
            recommendation_ready = False
        elif trade_date_adjusted and not adjusted_to_latest_completed_session:
            readiness_status = "blocked_trade_date_adjusted"
            blocked_reason = str(
                ((metadata.get("reliability_notice") or {}).get("message"))
                or "请求交易日的 Alpha 数据尚未落地，当前只拿到了最新可用交易日结果。"
            )
            recommendation_ready = False
        elif broad_pool_research_only:
            readiness_status = "blocked_broad_pool_research_only"
            blocked_reason = (
                "当前 Alpha 股票池仅为市场/价格覆盖研究池，不含账户特异约束；"
                "系统不会把这类 broad pool 排名包装成账户推荐。"
            )
            recommendation_ready = False
        elif fallback_mode == "forward_fill_latest_qlib_cache":
            readiness_status = "blocked_forward_filled_cache"
            blocked_reason = str(
                metadata.get("fallback_reason")
                or "当前结果为前推缓存，尚未通过当期 Alpha 实时推理验证。"
            )
            recommendation_ready = False
        elif result_age_days not in (None, 0) and not adjusted_to_latest_completed_session:
            readiness_status = "blocked_stale"
            blocked_reason = f"当前 Alpha 结果相对请求交易日已陈旧 {result_age_days} 天。"
            recommendation_ready = False
        elif is_degraded:
            readiness_status = "blocked_degraded"
            blocked_reason = str(
                ((metadata.get("reliability_notice") or {}).get("message"))
                or "当前 Alpha 结果处于 degraded 状态，不能作为决策推荐。"
            )
            recommendation_ready = False
        elif not latest_available_qlib_result and not data_driven_simple_result:
            readiness_status = "blocked_unverified_delivery"
            blocked_reason = "当前 Alpha 输出尚未验证为请求交易日的最新 scoped Qlib 结果。"
            recommendation_ready = False

        verified_scope_hash = ""
        verified_asof_date = None
        if scores and scope_verification_status == "verified":
            verified_scope_hash = getattr(scope, "scope_hash", "") or ""
            verified_asof_date = (
                effective_asof_date.isoformat() if effective_asof_date is not None else None
            )

        return {
            "result_age_days": result_age_days,
            "freshness_status": freshness_status,
            "is_stale": result_age_days not in (None, 0)
            and not adjusted_to_latest_completed_session,
            "scope_verification_status": scope_verification_status,
            "is_scope_verified": scope_verification_status == "verified",
            "latest_available_qlib_result": latest_available_qlib_result,
            "derived_from_broader_cache": derived_from_broader_cache,
            "trade_date_adjusted": trade_date_adjusted,
            "latest_completed_session_result": adjusted_to_latest_completed_session,
            "effective_trade_date": metadata.get("effective_trade_date"),
            "recommendation_ready": recommendation_ready,
            "must_not_use_for_decision": not recommendation_ready,
            "blocked_reason": blocked_reason,
            "readiness_status": readiness_status,
            "verified_scope_hash": verified_scope_hash,
            "verified_asof_date": verified_asof_date,
        }

    def _build_meta(self, *, alpha_result, scope, resolved_pool=None) -> dict[str, Any]:
        metadata = dict(getattr(alpha_result, "metadata", {}) or {})
        scope_metadata = scope.to_dict() if hasattr(scope, "to_dict") else {}
        requested_pool_mode = metadata.get("requested_pool_mode")
        requested_pool_size = metadata.get("requested_pool_size")
        if resolved_pool is not None:
            requested_pool_mode = requested_pool_mode or resolved_pool.requested_pool_mode
            requested_pool_size = requested_pool_size or resolved_pool.requested_pool_size
        if requested_pool_mode is None:
            requested_pool_mode = getattr(scope, "pool_mode", "")
        if requested_pool_size is None:
            requested_pool_size = getattr(scope, "pool_size", 0)
        meta = {
            "alpha_scope": metadata.get("alpha_scope") or ALPHA_SCOPE_PORTFOLIO,
            "research_only": bool(metadata.get("research_only", False)),
            "status": getattr(alpha_result, "status", "unavailable"),
            "source": getattr(alpha_result, "source", "none"),
            "provider_source": metadata.get("provider_source")
            or getattr(alpha_result, "source", "none"),
            "is_degraded": bool(metadata.get("is_degraded", False)),
            "uses_cached_data": bool(metadata.get("uses_cached_data", False)),
            "requested_trade_date": metadata.get("requested_trade_date"),
            "effective_asof_date": metadata.get("effective_asof_date"),
            "cache_date": metadata.get("cache_date"),
            "cache_created_at": metadata.get("created_at"),
            "cache_reason": metadata.get("fallback_reason")
            or metadata.get("warning_message")
            or "",
            "fallback_reason": metadata.get("fallback_reason") or "",
            "fallback_from": metadata.get("fallback_from"),
            "scope_fallback": bool(metadata.get("scope_fallback", False)),
            "scope_fallback_reason": metadata.get("scope_fallback_reason") or "",
            "scope_fallback_universe_id": metadata.get("scope_fallback_universe_id"),
            "no_recommendation_reason": metadata.get("no_recommendation_reason") or "",
            "hardcoded_fallback_used": bool(metadata.get("hardcoded_fallback_used", False)),
            "refresh_status": metadata.get("refresh_status") or "",
            "async_task_id": metadata.get("async_task_id") or "",
            "poll_after_ms": metadata.get("poll_after_ms") or 5000,
            "auto_refresh_message": metadata.get("auto_refresh_message") or "",
            "auto_refresh_error": metadata.get("auto_refresh_error") or "",
            "warning_title": (metadata.get("reliability_notice") or {}).get("title"),
            "warning_message": (metadata.get("reliability_notice") or {}).get("message"),
            "warning_level": (metadata.get("reliability_notice") or {}).get("level"),
            "refresh_triggered": bool(metadata.get("refresh_triggered", False)),
            "requested_pool_mode": requested_pool_mode,
            "requested_pool_size": requested_pool_size,
            "effective_pool_mode": metadata.get("effective_pool_mode")
            or getattr(scope, "pool_mode", ""),
            "effective_pool_size": metadata.get("effective_pool_size")
            or getattr(scope, "pool_size", 0),
            "scope_hash": getattr(scope, "scope_hash", ""),
            "scope_label": getattr(scope, "display_label", ""),
            "scope_metadata": scope_metadata,
            "universe_id": getattr(scope, "universe_id", ""),
            "pool_mode": getattr(scope, "pool_mode", ""),
            "model_hash": metadata.get("model_artifact_hash", ""),
        }
        meta.update(
            self._build_readiness_fields(
                alpha_result=alpha_result,
                scope=scope,
                metadata={**metadata, **meta},
            )
        )
        return meta
