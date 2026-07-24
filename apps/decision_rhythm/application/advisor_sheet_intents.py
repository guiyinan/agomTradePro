"""Intent construction and guard helpers for the advisor decision-sheet use case."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.decision_rhythm.application.advisor_contracts import (
    EXECUTION_GUARD_BLOCKING_STATUS,
    EXPOSURE_LIMIT_BLOCKING_STATUS,
    RISK_GATE_BLOCKING_STATUS,
    RISK_POLICY_UNAVAILABLE_STATUS,
    AdvisorHoldingSnapshot,
    AdvisorOrderIntent,
    ExecutionGuardProviderProtocol,
    RiskGateProviderProtocol,
)
from apps.decision_rhythm.application.advisor_execution import (
    _confirmation_payload_for_intent,
    _exposure_guard_for_intent,
)
from apps.decision_rhythm.application.advisor_intents import (
    _data_asof_for_asset,
    _dedupe_preserve_order,
    _execution_hint,
    _floor_quantity,
    _invalidation_rule,
    _normalize_recommendation_side,
    _price_band,
    _recommendation_asset_code,
    _recommendation_id,
    _recommendation_price,
    _recommendation_reason,
    _recommended_target_weight,
    _replace_intent,
    _stable_order_intent_id,
    _target_quantity,
)
from apps.decision_rhythm.application.advisor_performance import (
    _order_tracking_payload,
)


class AdvisorSheetIntentMixin:
    """Apply decision guards and construct immutable order intents."""

    risk_gate_provider: RiskGateProviderProtocol
    execution_guard_provider: ExecutionGuardProviderProtocol

    def _apply_risk_gate(
        self,
        *,
        account: dict[str, Any],
        holdings: list[AdvisorHoldingSnapshot],
        order_intents: list[AdvisorOrderIntent],
        policy_context: dict[str, Any],
    ) -> list[AdvisorOrderIntent]:
        gated: list[AdvisorOrderIntent] = []
        for intent in order_intents:
            gate = self.risk_gate_provider.evaluate_order(
                account=account,
                intent=intent,
                holdings=holdings,
                policy_context=policy_context,
            )
            risk_gate_status = str(gate.get("status") or "NOT_CHECKED")
            if risk_gate_status == "SKIPPED" and intent.risk_gate_status != "NOT_CHECKED":
                risk_gate_status = intent.risk_gate_status
            blocking_status = intent.blocking_status
            risk_notes = list(intent.risk_notes)
            if risk_gate_status == "REVIEW":
                risk_notes.extend(str(item) for item in gate.get("messages") or [])
            if risk_gate_status == "BLOCKED" and blocking_status == "OK":
                blocking_status = (
                    RISK_POLICY_UNAVAILABLE_STATUS
                    if gate.get("code") == "risk_policy_unavailable"
                    else RISK_GATE_BLOCKING_STATUS
                )
                risk_notes.extend(str(item) for item in gate.get("messages") or [])
            gated.append(
                _replace_intent(
                    intent,
                    blocking_status=blocking_status,
                    risk_notes=_dedupe_preserve_order(risk_notes),
                    risk_gate_status=risk_gate_status,
                    risk_gate={
                        **dict(intent.risk_gate),
                        "risk_center": gate,
                    },
                )
            )
        return gated

    def _apply_execution_guard(
        self,
        *,
        intent: AdvisorOrderIntent,
        recommendation: Any | None,
        resolution: dict[str, Any] | None,
    ) -> AdvisorOrderIntent:
        if intent.blocking_status != "OK":
            return intent
        guard = self.execution_guard_provider.evaluate(
            recommendation=recommendation,
            intent=intent,
            resolution=resolution,
        )
        if guard.get("status") != "BLOCKED":
            return _replace_intent(
                intent,
                risk_gate={
                    **dict(intent.risk_gate),
                    "execution_guard": guard,
                },
            )
        return _replace_intent(
            intent,
            blocking_status=EXECUTION_GUARD_BLOCKING_STATUS,
            risk_gate_status="BLOCKED",
            risk_gate={
                **dict(intent.risk_gate),
                "execution_guard": guard,
            },
            risk_notes=_dedupe_preserve_order(
                [
                    *intent.risk_notes,
                    *(str(item) for item in guard.get("messages") or []),
                ]
            ),
        )

    def _apply_exposure_guard(
        self,
        *,
        order_intents: list[AdvisorOrderIntent],
        exposure_summary: dict[str, Any],
    ) -> list[AdvisorOrderIntent]:
        alerts_by_asset: dict[str, list[dict[str, Any]]] = {}
        for alert in exposure_summary.get("alerts") or []:
            asset_code = str(alert.get("asset_code") or "").strip().upper()
            if asset_code:
                alerts_by_asset.setdefault(asset_code, []).append(dict(alert))

        guarded: list[AdvisorOrderIntent] = []
        for intent in order_intents:
            guard = _exposure_guard_for_intent(
                intent,
                alerts_by_asset.get(intent.asset_code, []),
            )
            if guard["status"] != "BLOCKED":
                guarded.append(
                    _replace_intent(
                        intent,
                        risk_gate={
                            **dict(intent.risk_gate),
                            "exposure_guard": guard,
                        },
                    )
                )
                continue
            guarded.append(
                _replace_intent(
                    intent,
                    blocking_status=EXPOSURE_LIMIT_BLOCKING_STATUS,
                    risk_gate_status="BLOCKED",
                    risk_gate={
                        **dict(intent.risk_gate),
                        "exposure_guard": guard,
                    },
                    risk_notes=_dedupe_preserve_order(
                        [
                            *intent.risk_notes,
                            *(str(item) for item in guard.get("messages") or []),
                        ]
                    ),
                )
            )
        return guarded

    def _attach_decision_card_context(
        self,
        *,
        order_intents: list[AdvisorOrderIntent],
        data_health: dict[str, Any],
    ) -> list[AdvisorOrderIntent]:
        return [
            _replace_intent(
                intent,
                data_asof=_data_asof_for_asset(data_health, intent.asset_code),
            )
            for intent in order_intents
        ]

    def _attach_tracking_context(
        self,
        *,
        order_intents: list[AdvisorOrderIntent],
        tracking_map: dict[str, dict[str, Any]],
    ) -> list[AdvisorOrderIntent]:
        return [
            _replace_intent(
                intent,
                tracking=_order_tracking_payload(intent, tracking_map),
            )
            for intent in order_intents
        ]

    def _attach_confirmation_context(
        self,
        *,
        account: dict[str, Any],
        order_intents: list[AdvisorOrderIntent],
        data_health: dict[str, Any],
        policy_context: dict[str, Any],
    ) -> list[AdvisorOrderIntent]:
        return [
            _replace_intent(
                intent,
                confirmation=_confirmation_payload_for_intent(
                    intent=intent,
                    account=account,
                    order_intents=order_intents,
                    data_health=data_health,
                    policy_context=policy_context,
                ),
            )
            for intent in order_intents
        ]

    def _build_existing_holding_intent(
        self,
        *,
        account_id: str,
        holding: AdvisorHoldingSnapshot,
        total_asset: Decimal,
        recommendation: Any | None,
    ) -> AdvisorOrderIntent | None:
        rec_side = _normalize_recommendation_side(recommendation)
        reason_parts: list[str] = []
        target_weight = holding.current_weight
        side = "HOLD"
        priority = 90

        if rec_side in {"SELL", "EXIT"}:
            side = "EXIT"
            target_weight = Decimal("0")
            priority = 10
            reason_parts.append("已有退出/卖出推荐")
        elif rec_side == "REDUCE":
            target_weight = min(holding.current_weight, Decimal("0.15"))
            if target_weight < holding.current_weight:
                side = "REDUCE"
                priority = 20
                reason_parts.append("已有减仓推荐")
            else:
                reason_parts.append("已有减仓推荐，但当前权重已不高于 15%")
        elif holding.unrealized_pnl_pct <= Decimal("-10"):
            side = "EXIT"
            target_weight = Decimal("0")
            priority = 12
            reason_parts.append("浮亏超过 10%，优先退出复核")
        elif holding.current_weight > Decimal("0.25"):
            side = "REDUCE"
            target_weight = Decimal("0.20")
            priority = 25
            reason_parts.append("单一持仓权重超过 25%，先降到 20% 以内")
        elif rec_side == "BUY":
            target_weight = min(
                holding.current_weight + Decimal("0.03"),
                Decimal("0.20"),
            )
            if target_weight > holding.current_weight:
                side = "ADD"
                priority = 50
                reason_parts.append("已有买入推荐，当前账户已持有，转换为加仓意图")
            else:
                target_weight = holding.current_weight
                reason_parts.append("已有买入推荐，但当前权重已达到 20% 加仓上限")
        else:
            reason_parts.append("当前持仓未触发调仓条件")

        if side == "HOLD":
            return self._intent_from_values(
                account_id=account_id,
                asset_code=holding.asset_code,
                asset_name=holding.asset_name,
                side="HOLD",
                current_quantity=holding.quantity,
                target_quantity=holding.quantity,
                current_weight=holding.current_weight,
                target_weight=target_weight,
                estimated_price=holding.current_price,
                priority=priority,
                reason="；".join(reason_parts),
                risk_notes=[],
                invalidation_rule=_invalidation_rule(recommendation),
                execution_hint="无需下单，继续观察持仓和失效条件。",
                source_recommendation_id=_recommendation_id(recommendation),
                blocking_status="OK",
            )

        risk_notes: list[str] = []
        blocking_status = "OK"
        if holding.current_price is None or holding.current_price <= 0:
            blocking_status = "BLOCKED_PRICE_MISSING"
            risk_notes.append("缺少有效现价，不能计算真实订单金额。")
        target_quantity = holding.quantity
        if blocking_status == "OK":
            target_quantity = _target_quantity(
                total_asset=total_asset,
                target_weight=target_weight,
                price=holding.current_price,
            )

        return self._intent_from_values(
            account_id=account_id,
            asset_code=holding.asset_code,
            asset_name=holding.asset_name,
            side=side,
            current_quantity=holding.quantity,
            target_quantity=target_quantity,
            current_weight=holding.current_weight,
            target_weight=target_weight,
            estimated_price=holding.current_price,
            priority=priority,
            reason="；".join(reason_parts),
            risk_notes=risk_notes,
            invalidation_rule=_invalidation_rule(recommendation),
            execution_hint=_execution_hint(side),
            source_recommendation_id=_recommendation_id(recommendation),
            blocking_status=blocking_status,
        )

    def _build_buy_intent(
        self,
        *,
        account_id: str,
        recommendation: Any,
        holding: AdvisorHoldingSnapshot | None,
        total_asset: Decimal,
        available_cash: Decimal,
        asset_name: str,
        baseline: str,
    ) -> AdvisorOrderIntent | None:
        asset_code = _recommendation_asset_code(recommendation)
        price = _recommendation_price(recommendation)
        risk_notes: list[str] = []
        blocking_status = "OK"
        if price is None or price <= 0:
            blocking_status = "BLOCKED_PRICE_MISSING"
            risk_notes.append("缺少有效现价，不能计算真实下单数量。")

        if available_cash <= 0:
            blocking_status = "BLOCKED_NO_CASH"
            risk_notes.append("账户可用资金不足，不能新增买入。")

        target_weight = _recommended_target_weight(recommendation, baseline=baseline)
        budget = min(available_cash, total_asset * target_weight)
        current_quantity = holding.quantity if holding else Decimal("0")
        current_weight = holding.current_weight if holding else Decimal("0")
        target_quantity = current_quantity
        if blocking_status == "OK" and price is not None:
            target_quantity = current_quantity + _floor_quantity(budget / price)
            if target_quantity <= current_quantity:
                blocking_status = "BLOCKED_MIN_SIZE"
                risk_notes.append("按目标权重和价格计算后不足 1 单位。")

        side = "ADD" if holding else "BUY"
        reason = _recommendation_reason(recommendation)
        if baseline == "empty_positions":
            reason = f"空仓账户建仓建议；{reason}"

        return self._intent_from_values(
            account_id=account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            side=side,
            current_quantity=current_quantity,
            target_quantity=target_quantity,
            current_weight=current_weight,
            target_weight=max(current_weight, target_weight),
            estimated_price=price,
            priority=40 if holding else 60,
            reason=reason,
            risk_notes=risk_notes,
            invalidation_rule=_invalidation_rule(recommendation),
            execution_hint=_execution_hint(side),
            source_recommendation_id=_recommendation_id(recommendation),
            blocking_status=blocking_status,
        )

    def _intent_from_values(
        self,
        *,
        account_id: str,
        asset_code: str,
        asset_name: str,
        side: str,
        current_quantity: Decimal,
        target_quantity: Decimal,
        current_weight: Decimal,
        target_weight: Decimal,
        estimated_price: Decimal | None,
        priority: int,
        reason: str,
        risk_notes: list[str],
        invalidation_rule: str,
        execution_hint: str,
        source_recommendation_id: str,
        blocking_status: str,
    ) -> AdvisorOrderIntent:
        delta_quantity = target_quantity - current_quantity
        amount = abs(delta_quantity) * (estimated_price or Decimal("0"))
        return AdvisorOrderIntent(
            order_intent_id=_stable_order_intent_id(
                account_id, asset_code, side, source_recommendation_id
            ),
            account_id=account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            side=side,
            current_quantity=current_quantity,
            target_quantity=target_quantity,
            delta_quantity=delta_quantity,
            estimated_price=estimated_price,
            estimated_amount=amount,
            current_weight=current_weight,
            target_weight=target_weight,
            priority=priority,
            price_band=_price_band(estimated_price),
            reason=reason,
            risk_notes=risk_notes,
            invalidation_rule=invalidation_rule,
            execution_hint=execution_hint,
            source_recommendation_id=source_recommendation_id,
            blocking_status=blocking_status,
            source_recommendation_ids=(
                [source_recommendation_id] if source_recommendation_id else []
            ),
        )
