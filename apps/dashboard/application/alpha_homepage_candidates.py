"""Candidate, factor, and actionability mapping for the Dashboard Alpha homepage."""

from __future__ import annotations

import logging
from math import isfinite
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from apps.account.application.use_cases import SizingContextOutput
from apps.alpha.domain.entities import StockScore

if TYPE_CHECKING:
    from apps.account.application.repository_provider import PortfolioRepository
    from apps.dashboard.application.repository_provider import DashboardAlphaContextRepository
    from apps.strategy.domain.services import DecisionPolicyEngine, PreTradeRiskGate, SizingEngine

logger = logging.getLogger(__name__)


class AlphaCandidateMixin:
    """Private behavior shard for AlphaHomepageQuery."""

    context_repo: DashboardAlphaContextRepository
    portfolio_repo: PortfolioRepository
    decision_engine: DecisionPolicyEngine
    sizing_engine: SizingEngine
    risk_gate: PreTradeRiskGate

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
    ) -> tuple[dict[str, float], object | None, SizingContextOutput | None]:
        if portfolio_id is None:
            return {}, None, None
        position_map: dict[str, float] = {}
        portfolio_snapshot: object | None = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
        if portfolio_snapshot is not None:
            for position in getattr(portfolio_snapshot, "positions", ()):
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
            from apps.dashboard.application import alpha_homepage

            sizing_context = alpha_homepage.GetSizingContextUseCase().execute(
                portfolio_id=portfolio_id,
                user_id=user_id,
                refresh_pulse_if_stale=refresh_pulse_if_stale,
            )
        except Exception:
            logger.warning(
                "Failed to load sizing context for portfolio %s",
                portfolio_id,
                exc_info=True,
            )
            sizing_context = None
        return position_map, portfolio_snapshot, sizing_context

    def _load_policy_state(self) -> dict[str, Any]:
        return self.context_repo.load_policy_state()

    def _build_candidate_item(
        self,
        *,
        score: StockScore,
        stock_context: dict[str, Any],
        actionable_candidate: object | None,
        pending_request: object | None,
        sizing_context: SizingContextOutput | None,
        portfolio_snapshot: object | None,
        position_map: dict[str, float],
        policy_state: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        data_quality_reasons: list[str] = []
        code = str(score.code or "").strip().upper()
        if not code:
            code = "UNKNOWN"
            data_quality_reasons.append("候选缺少有效证券代码。")

        resolved_score = self._finite_float(score.score, minimum=-1.0, maximum=1.0)
        if resolved_score is None:
            score_value = 0.0
            data_quality_reasons.append("Alpha 评分缺失、非有限或超出 [-1, 1]。")
        else:
            score_value = resolved_score

        resolved_confidence = self._finite_float(
            score.confidence,
            minimum=0.0,
            maximum=1.0,
        )
        if resolved_confidence is None:
            confidence = 0.0
            data_quality_reasons.append("Alpha 置信度缺失、非有限或超出 [0, 1]。")
        else:
            confidence = resolved_confidence

        rank = score.rank if isinstance(score.rank, int) and not isinstance(score.rank, bool) else 0
        if rank <= 0:
            rank = 0
            data_quality_reasons.append("Alpha 排名缺失或不是正整数。")

        current_price = self._finite_float(stock_context.get("close"), minimum=0.0) or 0.0
        account_equity = (
            self._finite_float(getattr(portfolio_snapshot, "total_value", None), minimum=0.0) or 0.0
        )
        resolved_position_value = self._finite_float(position_map.get(code), minimum=0.0)
        if code in position_map and resolved_position_value is None:
            data_quality_reasons.append("当前持仓市值缺失、非有限或为负数。")
        current_position_value = resolved_position_value or 0.0
        multiplier = 0.0
        if sizing_context is not None:
            resolved_multiplier = self._finite_float(
                sizing_context.multiplier_result.multiplier,
                minimum=0.0,
            )
            if resolved_multiplier is None:
                data_quality_reasons.append("宏观仓位系数缺失、非有限或为负数。")
            else:
                multiplier = resolved_multiplier
        regime_name = sizing_context.regime_name if sizing_context else "Unknown"
        regime_confidence = (
            self._finite_float(
                sizing_context.regime_confidence,
                minimum=0.0,
                maximum=1.0,
            )
            if sizing_context
            else None
        )
        if sizing_context is not None and regime_confidence is None:
            data_quality_reasons.append("Regime 置信度缺失、非有限或超出 [0, 1]。")
        regime_confidence = regime_confidence or 0.0
        pulse_composite = (
            self._finite_float(sizing_context.pulse_composite) if sizing_context else None
        )
        if sizing_context is not None and pulse_composite is None:
            data_quality_reasons.append("Pulse 综合分缺失或非有限。")
        pulse_composite = pulse_composite or 0.0
        pulse_warning = bool(sizing_context.pulse_warning) if sizing_context else False
        market_temperature_score = (
            self._finite_float(getattr(sizing_context, "market_temperature_score", None))
            if sizing_context is not None
            else None
        )
        if sizing_context is not None and market_temperature_score is None:
            data_quality_reasons.append("市场温度分缺失或非有限。")
        market_temperature_score = market_temperature_score or 0.0
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
            self._finite_float(
                getattr(
                    getattr(sizing_context, "multiplier_result", None),
                    "market_temperature_factor",
                    None,
                ),
                minimum=0.0,
            )
            if sizing_context is not None
            else None
        )
        if sizing_context is not None and market_temperature_factor is None:
            data_quality_reasons.append("市场温度仓位系数缺失、非有限或为负数。")
        market_temperature_factor = market_temperature_factor or 0.0

        reliability_reasons: list[str] = []
        metadata_blocked_reason = str(meta.get("blocked_reason") or "").strip()
        if bool(meta.get("must_not_use_for_decision", False)):
            reliability_reasons.append(metadata_blocked_reason or "Alpha 结果未通过可靠性校验。")
        if sizing_context is None and meta.get("alpha_scope") != "general":
            reliability_reasons.append("宏观仓位上下文不可用，当前候选仅供研究。")
        if market_temperature_degraded:
            reliability_reasons.append(
                market_temperature_blocked_reason or "市场温度数据已降级，当前候选仅供研究。"
            )
        critical_context_warnings = {
            "regime_unavailable",
            "pulse_unavailable",
            "snapshot_unavailable",
            "market_temperature_unavailable",
            "market_temperature_degraded",
        }
        if sizing_context is not None:
            context_warnings = {
                str(item).strip()
                for item in getattr(sizing_context, "warnings", [])
                if str(item).strip()
            }
            unavailable_warnings = sorted(context_warnings & critical_context_warnings)
            if unavailable_warnings:
                reliability_reasons.append(
                    "仓位决策上下文不完整：" + "、".join(unavailable_warnings)
                )
        reliability_reasons.extend(data_quality_reasons)

        signal_strength = max(min((score_value + 1.0) / 2.0, 1.0), 0.0)
        action, decision_codes, decision_text, _ = self.decision_engine.evaluate(
            signal_strength=signal_strength,
            signal_direction="bullish" if score_value >= 0 else "bearish",
            signal_confidence=confidence,
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
        reliability_blocked = bool(reliability_reasons)
        reliability_blocked_reason = metadata_blocked_reason or "；".join(
            dict.fromkeys(reliability_reasons)
        )

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
                "text": (
                    f"Alpha 排名第 {rank or '未知'}，评分 " f"{score_value:.3f}"
                    if resolved_score is not None
                    else f"Alpha 排名第 {rank or '未知'}，评分不可用"
                ),
            },
            {
                "code": "ALPHA_CONFIDENCE",
                "text": (
                    f"评分置信度 {confidence:.2f}"
                    if resolved_confidence is not None
                    else "评分置信度不可用"
                ),
            },
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
        workflow_thesis = str(getattr(actionable_candidate, "thesis", "") or "").strip()
        if workflow_thesis:
            buy_reasons.append({"code": "WORKFLOW_THESIS", "text": workflow_thesis})

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
            "summary": f"若跌出 Top {max(rank + 5, 10)}、政策/风控转差或评分跌破 0.55，则当前候选失效。",
            "conditions": [
                f"Alpha 评分跌出 Top {max(rank + 5, 10)}",
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
            "score": round(score_value, 4) if resolved_score is not None else None,
            "alpha_score": round(score_value, 4) if resolved_score is not None else None,
            "rank": rank,
            "source": score.source,
            "confidence": (round(confidence, 3) if resolved_confidence is not None else None),
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
                "rank": rank,
                "score": round(score_value, 4) if resolved_score is not None else None,
                "confidence": (round(confidence, 3) if resolved_confidence is not None else None),
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
            if not isfinite(value):
                basis.append(f"{key}=不可用")
                continue
            basis.append(f"{key}={value:.3f}")
        return basis

    @staticmethod
    def _finite_float(
        value: object,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        """Return a bounded finite float without inventing a numeric fallback."""

        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(cast(Any, value))
        except (TypeError, ValueError):
            return None
        if not isfinite(parsed):
            return None
        if minimum is not None and parsed < minimum:
            return None
        if maximum is not None and parsed > maximum:
            return None
        return parsed

    def _serialize_pending_request(
        self, *, request_model: object, stock_context: dict[str, Any]
    ) -> dict[str, Any]:
        code = str(getattr(request_model, "asset_code", "") or "").strip().upper()
        reason = str(getattr(request_model, "reason", "") or "")
        position_pct = self._finite_float(
            getattr(request_model, "position_pct", None),
            minimum=0.0,
        )
        notional = self._finite_float(
            getattr(request_model, "notional", None),
            minimum=0.0,
        )
        quantity = self._finite_float(
            getattr(request_model, "quantity", None),
            minimum=0.0,
        )
        return {
            "request_id": getattr(request_model, "request_id", ""),
            "code": code,
            "name": stock_context.get("name") or code,
            "stage": "pending",
            "stage_label": "待执行队列",
            "gate_status": "warn",
            "rank": 0,
            "alpha_score": None,
            "confidence": None,
            "source": "workflow",
            "buy_reasons": [{"code": "REQUEST_APPROVED", "text": "该标的已通过决策审批。"}],
            "no_buy_reasons": [{"code": "ALREADY_PENDING", "text": "当前已在待执行队列中。"}],
            "invalidation_rule": {
                "summary": "若执行失败或审批撤回，该待执行请求失效。",
                "conditions": ["审批被撤回", "执行状态转为取消/失败后未重试"],
            },
            "suggested_position_pct": position_pct,
            "suggested_notional": notional,
            "suggested_quantity": int(quantity) if quantity is not None else None,
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
