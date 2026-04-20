"""Dashboard Alpha homepage query services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.account.application.use_cases import GetSizingContextUseCase
from apps.account.infrastructure.repositories import PortfolioRepository
from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver
from apps.alpha.application.services import AlphaService
from apps.dashboard.infrastructure.repositories import (
    AlphaRecommendationHistoryRepository,
    DashboardAlphaContextRepository,
)
from apps.strategy.domain.services import DecisionPolicyEngine, PreTradeRiskGate, SizingEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlphaHomepageData:
    """Homepage Alpha payload."""

    pool: dict[str, Any]
    meta: dict[str, Any]
    top_candidates: list[dict[str, Any]]
    actionable_candidates: list[dict[str, Any]]
    pending_requests: list[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    history_run_id: int | None


class AlphaHomepageQuery:
    """Build the homepage Alpha candidate/ranking view."""

    def __init__(
        self,
        *,
        history_repo: AlphaRecommendationHistoryRepository | None = None,
        context_repo: DashboardAlphaContextRepository | None = None,
    ) -> None:
        self.history_repo = history_repo or AlphaRecommendationHistoryRepository()
        self.context_repo = context_repo or DashboardAlphaContextRepository()
        self.portfolio_repo = PortfolioRepository()
        self.alpha_service = AlphaService()
        self.decision_engine = DecisionPolicyEngine()
        self.sizing_engine = SizingEngine()
        self.risk_gate = PreTradeRiskGate()

    def execute(
        self,
        *,
        user,
        top_n: int = 10,
        portfolio_id: int | None = None,
        pool_mode: str | None = None,
    ) -> AlphaHomepageData:
        today = date.today()
        resolved_pool = PortfolioAlphaPoolResolver().resolve(
            user_id=user.id,
            portfolio_id=portfolio_id,
            trade_date=today,
            pool_mode=pool_mode,
        )
        scope = resolved_pool.scope

        alpha_result = self._fetch_alpha_result(
            user=user,
            scope=scope,
            trade_date=today,
            top_n=top_n,
        )
        meta = self._build_meta(alpha_result=alpha_result, scope=scope)

        top_scores = list(alpha_result.scores[:top_n]) if alpha_result.success else []
        stock_context = self._load_stock_context([score.code for score in top_scores])
        actionable_map = self._load_actionable_map()
        pending_map = self._load_pending_map()
        position_map, portfolio_snapshot, sizing_context = self._load_portfolio_context(
            user_id=user.id,
            portfolio_id=resolved_pool.portfolio_id,
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
                "portfolio_id": resolved_pool.portfolio_id,
                "portfolio_name": resolved_pool.portfolio_name,
                "label": scope.display_label,
                "pool_type": scope.pool_type,
                "market": scope.market,
                "pool_mode": scope.pool_mode,
                "pool_size": scope.pool_size,
                "selection_reason": scope.selection_reason,
                "scope_hash": scope.scope_hash,
            },
            meta=meta,
            top_candidates=top_candidates,
            actionable_candidates=actionable_candidates,
            pending_requests=pending_requests,
            recent_runs=recent_runs,
            history_run_id=history_run_id,
        )

    def list_history(
        self,
        *,
        user_id: int,
        portfolio_id: int | None = None,
        stock_code: str | None = None,
        stage: str | None = None,
        source: str | None = None,
        trade_date: date | None = None,
    ) -> list[dict[str, Any]]:
        runs = self.history_repo.filter_runs(
            user_id=user_id,
            portfolio_id=portfolio_id,
            stock_code=stock_code,
            stage=stage,
            source=source,
            trade_date=trade_date,
        )
        return self._serialize_recent_runs(runs)

    def get_history_detail(self, *, user_id: int, run_id: int) -> dict[str, Any] | None:
        run = self.history_repo.get_run_detail(user_id=user_id, run_id=run_id)
        if run is None:
            return None
        snapshot_codes = [str(snapshot.stock_code or "").strip().upper() for snapshot in run.snapshots.all()]
        stock_context = self.context_repo.load_stock_context(snapshot_codes)
        snapshots = []
        for snapshot in run.snapshots.all():
            snapshot_code = str(snapshot.stock_code or "").strip().upper()
            fallback_name = (stock_context.get(snapshot_code) or {}).get("name") or snapshot_code
            stock_name = str(snapshot.stock_name or "").strip() or fallback_name
            if stock_name.upper() == snapshot_code:
                stock_name = fallback_name
            snapshots.append(
                {
                    "code": snapshot_code,
                    "name": stock_name,
                    "stage": snapshot.stage,
                    "gate_status": snapshot.gate_status,
                    "rank": snapshot.rank,
                    "alpha_score": snapshot.alpha_score,
                    "confidence": snapshot.confidence,
                    "source": snapshot.source,
                    "buy_reasons": snapshot.buy_reasons,
                    "no_buy_reasons": snapshot.no_buy_reasons,
                    "invalidation_rule": snapshot.invalidation_rule,
                    "risk_snapshot": snapshot.risk_snapshot,
                    "suggested_position_pct": snapshot.suggested_position_pct,
                    "suggested_notional": snapshot.suggested_notional,
                    "suggested_quantity": snapshot.suggested_quantity,
                    "extra_payload": snapshot.extra_payload,
                }
            )
        return {
            "id": run.id,
            "portfolio_id": run.portfolio_id,
            "portfolio_name": run.portfolio_name,
            "trade_date": run.trade_date.isoformat(),
            "scope_label": run.scope_label,
            "source": run.source,
            "provider_source": run.provider_source,
            "uses_cached_data": run.uses_cached_data,
            "cache_reason": run.cache_reason,
            "fallback_reason": run.fallback_reason,
            "requested_trade_date": (
                run.requested_trade_date.isoformat() if run.requested_trade_date else None
            ),
            "effective_asof_date": (
                run.effective_asof_date.isoformat() if run.effective_asof_date else None
            ),
            "meta": run.meta,
            "snapshots": snapshots,
        }

    def _fetch_alpha_result(self, *, user, scope, trade_date: date, top_n: int):
        result = None
        for provider_name in ("cache",):
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
                return candidate
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

            from apps.alpha.application.tasks import qlib_predict_scores

            task = qlib_predict_scores.delay(
                scope.universe_id,
                trade_date.isoformat(),
                top_n,
                scope_payload=scope.to_dict(),
            )
            return {
                "refresh_triggered": True,
                "refresh_status": "queued",
                "async_task_id": getattr(task, "id", ""),
                "poll_after_ms": 5000,
                "message": "账户池暂无可信 Alpha cache，已自动触发后台 Qlib 推理。",
            }
        except Exception as exc:
            logger.warning("Failed to auto trigger scoped Alpha inference: %s", exc, exc_info=True)
            return {
                "refresh_triggered": False,
                "refresh_status": "failed",
                "auto_refresh_error": str(exc),
                "message": "账户池 Alpha 推理自动触发失败，请手动重试。",
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

    def _build_meta(self, *, alpha_result, scope) -> dict[str, Any]:
        metadata = dict(getattr(alpha_result, "metadata", {}) or {})
        scope_metadata = scope.to_dict() if hasattr(scope, "to_dict") else {}
        return {
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
            "scope_hash": scope.scope_hash,
            "scope_label": scope.display_label,
            "scope_metadata": scope_metadata,
            "model_hash": metadata.get("model_artifact_hash", ""),
        }

    def _load_stock_context(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        return self.context_repo.load_stock_context(codes)

    def _load_actionable_map(self) -> dict[str, Any]:
        return self.context_repo.load_actionable_map()

    def _load_pending_map(self) -> dict[str, Any]:
        return self.context_repo.load_pending_map()

    def _load_portfolio_context(
        self,
        *,
        user_id: int,
        portfolio_id: int | None,
    ) -> tuple[dict[str, float], Any | None, Any | None]:
        if portfolio_id is None:
            return {}, None, None
        position_map: dict[str, float] = {}
        portfolio_snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
        if portfolio_snapshot is not None:
            for position in portfolio_snapshot.positions:
                position_map[str(position.asset_code).upper()] = float(position.market_value)
        try:
            sizing_context = GetSizingContextUseCase().execute(
                portfolio_id=portfolio_id, user_id=user_id
            )
        except Exception as exc:
            logger.warning("Failed to load sizing context for portfolio %s: %s", portfolio_id, exc)
            sizing_context = None
        return position_map, portfolio_snapshot, sizing_context

    def _load_policy_state(self) -> dict[str, Any]:
        return self.context_repo.load_policy_state()

    def _build_candidate_item(
        self,
        *,
        score,
        stock_context: dict[str, Any],
        actionable_candidate,
        pending_request,
        sizing_context,
        portfolio_snapshot,
        position_map: dict[str, float],
        policy_state: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        code = str(score.code).upper()
        current_price = float(stock_context.get("close") or 0.0)
        account_equity = float(getattr(portfolio_snapshot, "total_value", 0.0) or 0.0)
        current_position_value = float(position_map.get(code, 0.0))
        multiplier = (
            float(sizing_context.multiplier_result.multiplier)
            if sizing_context is not None
            else 1.0
        )
        regime_name = sizing_context.regime_name if sizing_context else "Unknown"
        regime_confidence = float(sizing_context.regime_confidence) if sizing_context else 0.0
        pulse_composite = float(sizing_context.pulse_composite) if sizing_context else 0.0
        pulse_warning = bool(sizing_context.pulse_warning) if sizing_context else False
        signal_strength = max(min((float(score.score) + 1.0) / 2.0, 1.0), 0.0)
        action, decision_codes, decision_text, _ = self.decision_engine.evaluate(
            signal_strength=signal_strength,
            signal_direction="bullish" if float(score.score) >= 0 else "bearish",
            signal_confidence=float(score.confidence),
            regime=regime_name,
            regime_confidence=regime_confidence,
            daily_pnl_pct=0.0,
            daily_trade_count=0,
            target_regime=None,
        )

        suggested_notional = 0.0
        suggested_quantity = 0.0
        suggested_position_pct = 0.0
        sizing_explain = "账户或价格上下文不足，未生成建议仓位。"
        if account_equity > 0 and current_price > 0:
            target_notional, qty, _, _, sizing_explain = self.sizing_engine.calculate(
                method="fixed_fraction",
                account_equity=account_equity,
                current_price=current_price,
                current_position_value=current_position_value,
            )
            suggested_notional = float(target_notional) * multiplier
            suggested_quantity = int(suggested_notional / current_price) if current_price else 0
            suggested_position_pct = (
                (suggested_notional / account_equity * 100) if account_equity else 0.0
            )

        passed, violations, warnings, details = self.risk_gate.check(
            symbol=code,
            side="buy",
            qty=int(suggested_quantity or 0),
            price=current_price or 0.0,
            account_equity=account_equity or 0.0,
            current_position_value=current_position_value,
            daily_trade_count=0,
            daily_pnl_pct=0.0,
            avg_volume=float(stock_context.get("volume") or 0.0) or None,
        )

        stage = "top_ranked"
        gate_status = "blocked"
        if pending_request is not None:
            stage = "pending"
            gate_status = "warn"
        elif passed and action == "allow" and suggested_position_pct > 0:
            stage = "actionable"
            gate_status = "passed"
        elif passed and action == "watch":
            gate_status = "warn"

        buy_reasons = [
            {
                "code": "MODEL_SOURCE",
                "text": (
                    f"来源 {meta.get('provider_source') or score.source}，"
                    f"评分日 {score.asof_date.isoformat() if score.asof_date else meta.get('effective_asof_date') or '未知'}，"
                    f"账户池 {meta.get('scope_hash') or '未标记'}"
                ),
            },
            {
                "code": "ALPHA_TOP_RANK",
                "text": f"Alpha 排名第 {score.rank}，评分 {float(score.score):.3f}",
            },
            {"code": "ALPHA_CONFIDENCE", "text": f"评分置信度 {float(score.confidence):.2f}"},
            {
                "code": "REGIME_CONTEXT",
                "text": f"当前 Regime {regime_name}，置信度 {regime_confidence:.0%}",
            },
            {"code": "PULSE_CONTEXT", "text": f"Pulse 综合分 {pulse_composite:+.2f}"},
        ]
        factor_basis = self._build_factor_basis(getattr(score, "factors", {}) or {})
        if factor_basis:
            buy_reasons.append(
                {
                    "code": "FACTOR_EVIDENCE",
                    "text": "因子依据：" + "；".join(factor_basis[:3]),
                }
            )
        if actionable_candidate is not None and getattr(actionable_candidate, "thesis", ""):
            buy_reasons.append({"code": "WORKFLOW_THESIS", "text": actionable_candidate.thesis})

        no_buy_reasons = []
        if pending_request is not None:
            no_buy_reasons.append(
                {"code": "ALREADY_PENDING", "text": "已进入待执行队列，避免重复下单。"}
            )
        if policy_state.get("gate_level") in {"L2", "L3"}:
            no_buy_reasons.append(
                {
                    "code": "POLICY_GATE_TIGHT",
                    "text": f"当前政策闸门 {policy_state.get('gate_level')}，新仓需要更严格审查。",
                }
            )
        if meta.get("uses_cached_data"):
            no_buy_reasons.append(
                {
                    "code": "CACHE_FALLBACK",
                    "text": f"当前展示为缓存结果，原因：{meta.get('cache_reason') or '实时结果未就绪'}",
                }
            )
        if action == "watch":
            no_buy_reasons.append({"code": "DECISION_WATCH", "text": decision_text})
        if action == "deny":
            no_buy_reasons.append({"code": "DECISION_DENY", "text": decision_text})
        for violation in violations:
            no_buy_reasons.append({"code": "RISK_BLOCK", "text": violation})
        for warning in warnings:
            no_buy_reasons.append({"code": "RISK_WARN", "text": warning})
        if suggested_position_pct <= 0:
            no_buy_reasons.append(
                {"code": "NO_POSITION_SIZE", "text": "当前账户上下文未形成正向建议仓位。"}
            )

        invalidation_rule = {
            "summary": f"若跌出 Top {max(score.rank + 5, 10)}、政策/风控转差或评分跌破 0.55，则当前候选失效。",
            "conditions": [
                f"Alpha 评分跌出 Top {max(score.rank + 5, 10)}",
                "政策闸门提升至 L2/L3",
                "预交易风控由通过变为阻断",
                "当前候选进入待执行队列或被 workflow 显式否决",
            ],
        }

        return {
            "code": code,
            "name": stock_context.get("name") or code,
            "sector": stock_context.get("sector") or "",
            "market": stock_context.get("market") or "",
            "score": round(float(score.score), 4),
            "alpha_score": round(float(score.score), 4),
            "rank": int(score.rank),
            "source": score.source,
            "confidence": round(float(score.confidence), 3),
            "factors": score.factors,
            "asof_date": score.asof_date.isoformat() if score.asof_date else None,
            "trade_date": stock_context.get("trade_date"),
            "stage": stage,
            "stage_label": {
                "top_ranked": "Alpha Top 候选/排名",
                "actionable": "可行动候选",
                "pending": "待执行队列",
            }.get(stage, "Alpha Top 候选/排名"),
            "gate_status": gate_status,
            "gate_reasons": violations or warnings or decision_codes,
            "suggested_position_pct": round(suggested_position_pct, 2),
            "suggested_notional": round(suggested_notional, 2),
            "suggested_quantity": int(suggested_quantity or 0),
            "risk_snapshot": {
                "policy_gate_level": policy_state.get("gate_level"),
                "regime_name": regime_name,
                "regime_confidence": regime_confidence,
                "pulse_composite": pulse_composite,
                "pulse_warning": pulse_warning,
                "risk_checks": details,
                "sizing_explain": sizing_explain,
            },
            "buy_reasons": buy_reasons,
            "buy_reason_summary": "；".join(reason["text"] for reason in buy_reasons[:3]),
            "recommendation_basis": {
                "provider_source": meta.get("provider_source") or score.source,
                "score_source": score.source,
                "scope_hash": meta.get("scope_hash"),
                "scope_label": meta.get("scope_label"),
                "asof_date": score.asof_date.isoformat() if score.asof_date else None,
                "requested_trade_date": meta.get("requested_trade_date"),
                "effective_asof_date": meta.get("effective_asof_date"),
                "rank": int(score.rank),
                "score": round(float(score.score), 4),
                "confidence": round(float(score.confidence), 3),
                "factor_basis": factor_basis,
            },
            "no_buy_reasons": no_buy_reasons,
            "no_buy_reason_summary": "；".join(reason["text"] for reason in no_buy_reasons[:3]),
            "invalidation_rule": invalidation_rule,
            "invalidation_summary": invalidation_rule["summary"],
            "source_candidate_id": getattr(actionable_candidate, "id", None),
            "source_recommendation_id": getattr(pending_request, "id", None),
            "extra_payload": {
                "decision_action": action,
                "decision_codes": decision_codes,
                "decision_text": decision_text,
            },
        }

    def _build_factor_basis(self, factors: dict[str, Any]) -> list[str]:
        basis: list[str] = []
        for key, raw_value in factors.items():
            if raw_value in (None, ""):
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                basis.append(f"{key}={raw_value}")
                continue
            basis.append(f"{key}={value:.3f}")
        return basis

    def _serialize_pending_request(
        self, *, request_model, stock_context: dict[str, Any]
    ) -> dict[str, Any]:
        code = str(request_model.asset_code).upper()
        reason = str(getattr(request_model, "reason", "") or "")
        return {
            "request_id": getattr(request_model, "request_id", ""),
            "code": code,
            "name": stock_context.get("name") or code,
            "stage": "pending",
            "stage_label": "待执行队列",
            "gate_status": "warn",
            "rank": 0,
            "alpha_score": 0.0,
            "confidence": 0.0,
            "source": "workflow",
            "buy_reasons": [{"code": "REQUEST_APPROVED", "text": "该标的已通过决策审批。"}],
            "no_buy_reasons": [{"code": "ALREADY_PENDING", "text": "当前已在待执行队列中。"}],
            "invalidation_rule": {
                "summary": "若执行失败或审批撤回，该待执行请求失效。",
                "conditions": ["审批被撤回", "执行状态转为取消/失败后未重试"],
            },
            "suggested_position_pct": float(getattr(request_model, "position_pct", 0.0) or 0.0),
            "suggested_notional": float(getattr(request_model, "notional", 0.0) or 0.0),
            "suggested_quantity": float(getattr(request_model, "quantity", 0.0) or 0.0),
            "source_recommendation_id": getattr(request_model, "id", None),
            "reason_summary": reason,
            "risk_snapshot": {
                "execution_status": getattr(request_model, "execution_status", ""),
                "reason": reason,
            },
            "extra_payload": {
                "execution_status": getattr(request_model, "execution_status", ""),
            },
        }

    def _persist_history(
        self,
        *,
        user_id: int,
        portfolio_id: int | None,
        portfolio_name: str,
        scope,
        alpha_result,
        meta: dict[str, Any],
        snapshots: list[dict[str, Any]],
    ) -> int | None:
        try:
            run = self.history_repo.upsert_run(
                user_id=user_id,
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
                trade_date=date.today(),
                scope_hash=scope.scope_hash,
                scope_label=scope.display_label,
                scope_metadata=scope.to_dict(),
                model_hash=meta.get("model_hash", ""),
                source=meta.get("source", "none"),
                provider_source=meta.get("provider_source", ""),
                requested_trade_date=(
                    date.fromisoformat(meta["requested_trade_date"])
                    if meta.get("requested_trade_date")
                    else None
                ),
                effective_asof_date=(
                    date.fromisoformat(meta["effective_asof_date"])
                    if meta.get("effective_asof_date")
                    else None
                ),
                uses_cached_data=bool(meta.get("uses_cached_data", False)),
                cache_reason=str(meta.get("cache_reason") or ""),
                fallback_reason=str(meta.get("fallback_reason") or ""),
                meta=dict(getattr(alpha_result, "metadata", {}) or {}),
            )
            self.history_repo.replace_snapshots(
                run=run,
                snapshots=[
                    {
                        "stock_code": item["code"],
                        "stock_name": item.get("name", ""),
                        "stage": item.get("stage", "top_ranked"),
                        "gate_status": item.get("gate_status", "blocked"),
                        "rank": item.get("rank", 0),
                        "alpha_score": item.get("alpha_score", 0.0),
                        "confidence": item.get("confidence", 0.0),
                        "source": item.get("source", ""),
                        "buy_reasons": item.get("buy_reasons", []),
                        "no_buy_reasons": item.get("no_buy_reasons", []),
                        "invalidation_rule": item.get("invalidation_rule", {}),
                        "risk_snapshot": item.get("risk_snapshot", {}),
                        "suggested_position_pct": item.get("suggested_position_pct", 0.0),
                        "suggested_notional": item.get("suggested_notional", 0.0),
                        "suggested_quantity": item.get("suggested_quantity", 0.0),
                        "source_candidate_id": item.get("source_candidate_id"),
                        "source_recommendation_id": item.get("source_recommendation_id"),
                        "extra_payload": item.get("extra_payload", {}),
                    }
                    for item in snapshots
                ],
            )
            return run.id
        except Exception as exc:
            logger.warning("Failed to persist alpha homepage history: %s", exc, exc_info=True)
            return None

    def _serialize_recent_runs(self, runs) -> list[dict[str, Any]]:
        payload = []
        for run in runs:
            cache_reason = str(run.cache_reason or "")
            meta = dict(getattr(run, "meta", {}) or {})
            legacy_hardcoded_fallback = (
                meta.get("fallback_mode") == "homepage_market_cache_fallback"
                or "csi300 全局缓存" in cache_reason
                or "全局缓存排名" in cache_reason
            )
            payload.append(
                {
                    "id": run.id,
                    "portfolio_id": run.portfolio_id,
                    "portfolio_name": run.portfolio_name,
                    "trade_date": run.trade_date.isoformat(),
                    "scope_label": run.scope_label,
                    "source": run.source,
                    "provider_source": run.provider_source,
                    "uses_cached_data": run.uses_cached_data,
                    "effective_asof_date": (
                        run.effective_asof_date.isoformat() if run.effective_asof_date else None
                    ),
                    "cache_reason": cache_reason,
                    "legacy_hardcoded_fallback": legacy_hardcoded_fallback,
                    "reliability_note": (
                        "旧版硬编码回退记录，仅用于审计回溯，不作为当前推荐依据。"
                        if legacy_hardcoded_fallback
                        else ""
                    ),
                }
            )
        return payload
