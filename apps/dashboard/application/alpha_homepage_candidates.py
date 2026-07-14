"""Candidate, factor, and actionability mapping for the Dashboard Alpha homepage."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from apps.account.application.use_cases import GetSizingContextUseCase

logger = logging.getLogger(__name__)


class AlphaCandidateMixin:
    """Private behavior shard for AlphaHomepageQuery."""

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
        refresh_pulse_if_stale: bool,
    ) -> tuple[dict[str, float], Any | None, Any | None]:
        if portfolio_id is None:
            return {}, None, None
        position_map: dict[str, float] = {}
        portfolio_snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
        if portfolio_snapshot is not None:
            for position in portfolio_snapshot.positions:
                position_map[str(position.asset_code).upper()] = float(position.market_value)
        if (
            portfolio_snapshot is None
            or float(getattr(portfolio_snapshot, "total_value", 0.0) or 0.0) <= 0
        ):
            context_repo = getattr(self, "context_repo", None)
            account_totals = (
                context_repo.load_user_account_totals(user_id) if context_repo is not None else None
            )
            total_assets = float((account_totals or {}).get("total_assets") or 0.0)
            if total_assets > 0:
                portfolio_snapshot = SimpleNamespace(
                    total_value=total_assets,
                    positions=(
                        getattr(portfolio_snapshot, "positions", []) if portfolio_snapshot else []
                    ),
                )
        try:
            sizing_context = GetSizingContextUseCase().execute(
                portfolio_id=portfolio_id,
                user_id=user_id,
                refresh_pulse_if_stale=refresh_pulse_if_stale,
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
        market_temperature_score = (
            float(getattr(sizing_context, "market_temperature_score", 0.0) or 0.0)
            if sizing_context is not None
            else 0.0
        )
        market_temperature_band = (
            str(getattr(sizing_context, "market_temperature_band", "") or "").strip().lower()
            if sizing_context is not None
            else ""
        )
        market_temperature_degraded = (
            bool(getattr(sizing_context, "market_temperature_degraded", False))
            if sizing_context is not None
            else False
        )
        market_temperature_threshold_source = (
            str(getattr(sizing_context, "market_temperature_threshold_source", "") or "")
            if sizing_context is not None
            else ""
        )
        market_temperature_blocked_reason = (
            str(getattr(sizing_context, "market_temperature_blocked_reason", "") or "")
            if sizing_context is not None
            else ""
        )
        market_temperature_blocks_new_position = (
            bool(getattr(sizing_context, "market_temperature_blocks_new_position", False))
            if sizing_context is not None
            else False
        )
        market_temperature_factor = (
            float(
                getattr(
                    getattr(sizing_context, "multiplier_result", None),
                    "market_temperature_factor",
                    1.0,
                )
                or 1.0
            )
            if sizing_context is not None
            else 1.0
        )
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
        new_position_temperature_block = (
            market_temperature_blocks_new_position and current_position_value <= 0
        )

        stage = "top_ranked"
        gate_status = "blocked"
        reliability_blocked = bool(meta.get("must_not_use_for_decision", False))
        reliability_blocked_reason = str(meta.get("blocked_reason") or "")

        if pending_request is not None:
            stage = "pending"
            gate_status = "warn"
        elif (
            not reliability_blocked and passed and action == "allow" and suggested_position_pct > 0
        ):
            stage = "actionable"
            gate_status = "passed"
        elif passed and action == "watch":
            gate_status = "warn"
        elif reliability_blocked and passed:
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
        if market_temperature_band:
            temperature_text = (
                f"市场温度 {market_temperature_band} {market_temperature_score:.1f}"
                f"（系数 {market_temperature_factor:.2f}）"
            )
            if market_temperature_threshold_source == "user_override":
                temperature_text += "，使用个人阈值"
            if market_temperature_degraded:
                temperature_text += "，当前仅供参考"
            elif market_temperature_band in {"hot", "overheat", "extreme"}:
                temperature_text += "，已收缩建议仓位"
            buy_reasons.append({"code": "MARKET_TEMPERATURE_CONTEXT", "text": temperature_text})
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
        if reliability_blocked and reliability_blocked_reason:
            no_buy_reasons.append(
                {
                    "code": "ALPHA_RELIABILITY_BLOCK",
                    "text": reliability_blocked_reason,
                }
            )
        if new_position_temperature_block:
            no_buy_reasons.append(
                {
                    "code": "MARKET_TEMPERATURE_BLOCK",
                    "text": market_temperature_blocked_reason
                    or "市场温度已进入 extreme，新仓建议暂时关闭。",
                }
            )
        if policy_state.get("gate_level") in {"L2", "L3"}:
            no_buy_reasons.append(
                {
                    "code": "POLICY_GATE_TIGHT",
                    "text": f"当前政策闸门 {policy_state.get('gate_level')}，新仓需要更严格审查。",
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
        if stage == "actionable" and new_position_temperature_block:
            stage = "top_ranked"
            gate_status = "warn"

        recommendation_ready = (
            stage == "actionable" and not reliability_blocked and not new_position_temperature_block
        )
        decision_usable = not reliability_blocked
        not_actionable_reason = (
            "当前已在待执行队列中。"
            if pending_request is not None
            else (
                (market_temperature_blocked_reason or "市场温度已进入 extreme，新仓建议暂时关闭。")
                if new_position_temperature_block
                else reliability_blocked_reason
                or (
                    no_buy_reasons[0]["text"]
                    if no_buy_reasons
                    else "当前候选仅供研究，不构成可执行推荐。"
                )
            )
        )

        return {
            "code": code,
            "name": stock_context.get("name") or code,
            "sector": stock_context.get("sector") or "",
            "market": stock_context.get("market") or "",
            "roe": stock_context.get("roe"),
            "debt_ratio": stock_context.get("debt_ratio"),
            "revenue_growth": stock_context.get("revenue_growth"),
            "profit_growth": stock_context.get("profit_growth"),
            "pe": stock_context.get("pe"),
            "pb": stock_context.get("pb"),
            "ps": stock_context.get("ps"),
            "dividend_yield": stock_context.get("dividend_yield"),
            "report_date": stock_context.get("report_date"),
            "valuation_trade_date": stock_context.get("valuation_trade_date"),
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
                "market_temperature_score": market_temperature_score,
                "market_temperature_band": market_temperature_band,
                "market_temperature_factor": market_temperature_factor,
                "market_temperature_threshold_source": market_temperature_threshold_source,
                "market_temperature_degraded": market_temperature_degraded,
                "market_temperature_blocks_new_position": market_temperature_blocks_new_position,
                "risk_checks": details,
                "sizing_explain": sizing_explain,
            },
            "buy_reasons": buy_reasons,
            "buy_reason_summary": "；".join(reason["text"] for reason in buy_reasons[:3]),
            "recommendation_basis": {
                "alpha_scope": meta.get("alpha_scope"),
                "provider_source": meta.get("provider_source") or score.source,
                "score_source": score.source,
                "universe_id": meta.get("universe_id"),
                "pool_mode": meta.get("pool_mode"),
                "scope_hash": meta.get("scope_hash"),
                "scope_label": meta.get("scope_label"),
                "asof_date": score.asof_date.isoformat() if score.asof_date else None,
                "requested_trade_date": meta.get("requested_trade_date"),
                "effective_asof_date": meta.get("effective_asof_date"),
                "rank": int(score.rank),
                "score": round(float(score.score), 4),
                "confidence": round(float(score.confidence), 3),
                "factor_basis": factor_basis,
                "scope_verification_status": meta.get("scope_verification_status"),
                "freshness_status": meta.get("freshness_status"),
                "result_age_days": meta.get("result_age_days"),
                "verified_scope_hash": meta.get("verified_scope_hash"),
                "verified_asof_date": meta.get("verified_asof_date"),
                "latest_available_qlib_result": bool(
                    meta.get("latest_available_qlib_result", False)
                ),
                "derived_from_broader_cache": bool(meta.get("derived_from_broader_cache", False)),
                "trade_date_adjusted": bool(meta.get("trade_date_adjusted", False)),
                "research_only": bool(meta.get("research_only", False)),
                "must_not_use_for_decision": bool(meta.get("must_not_use_for_decision", False)),
                "blocked_reason": reliability_blocked_reason,
                "market_temperature_score": market_temperature_score,
                "market_temperature_band": market_temperature_band,
                "market_temperature_factor": market_temperature_factor,
                "market_temperature_threshold_source": market_temperature_threshold_source,
                "market_temperature_degraded": market_temperature_degraded,
                "market_temperature_blocked_reason": market_temperature_blocked_reason,
                "market_temperature_blocks_new_position": market_temperature_blocks_new_position,
            },
            "no_buy_reasons": no_buy_reasons,
            "no_buy_reason_summary": "；".join(reason["text"] for reason in no_buy_reasons[:3]),
            "invalidation_rule": invalidation_rule,
            "invalidation_summary": invalidation_rule["summary"],
            "source_candidate_id": getattr(actionable_candidate, "id", None),
            "source_recommendation_id": getattr(pending_request, "id", None),
            "recommendation_ready": recommendation_ready,
            "must_not_treat_as_recommendation": not recommendation_ready,
            "decision_usable": decision_usable,
            "must_not_use_for_decision": not decision_usable,
            "blocked_reason": not_actionable_reason,
            "not_actionable_reason": not_actionable_reason,
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
            "recommendation_ready": False,
            "must_not_use_for_decision": True,
            "blocked_reason": "当前已在待执行队列中。",
            "risk_snapshot": {
                "execution_status": getattr(request_model, "execution_status", ""),
                "reason": reason,
            },
            "extra_payload": {
                "execution_status": getattr(request_model, "execution_status", ""),
            },
        }
