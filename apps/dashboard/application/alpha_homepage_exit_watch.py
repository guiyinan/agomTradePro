"""Exit-watch construction for the Dashboard Alpha homepage."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Any

from apps.dashboard.application.navigation import (
    build_decision_workspace_url,
    build_exit_user_action_label,
    normalize_exit_user_action,
)
from apps.signal.application.repository_provider import get_signal_repository
from apps.simulated_trading.application.query_services import list_user_position_payloads

logger = logging.getLogger(__name__)


class AlphaExitWatchMixin:
    """Private behavior shard for AlphaHomepageQuery."""

    def _build_exit_watchlist(self, *, user_id: int, trade_date: date) -> list[dict[str, Any]]:
        positions = list_user_position_payloads(
            user_id=user_id,
            include_account_meta=True,
        )
        if not positions:
            return []

        positions_by_account: dict[int, list[dict[str, Any]]] = defaultdict(list)
        signal_ids: set[int] = set()
        for position in positions:
            account_id = self._safe_int(position.get("account_id"))
            if account_id is None:
                continue
            positions_by_account[account_id].append(position)
            signal_id = self._safe_int(position.get("signal_id"))
            if signal_id is not None:
                signal_ids.add(signal_id)

        recommendation_map_by_account: dict[int, dict[str, Any]] = {}
        transition_order_map_by_account: dict[int, dict[str, dict[str, Any]]] = {}
        for account_id in positions_by_account:
            recommendations = self._load_unified_recommendations(account_id)
            recommendation_map = self._latest_recommendations_by_security(recommendations)
            recommendation_map_by_account[account_id] = recommendation_map
            for recommendation in recommendation_map.values():
                for signal_id in getattr(recommendation, "source_signal_ids", []) or []:
                    normalized_id = self._safe_int(signal_id)
                    if normalized_id is not None:
                        signal_ids.add(normalized_id)
            transition_order_map_by_account[account_id] = self._load_transition_orders(
                account_id=account_id,
                trade_date=trade_date,
            )

        signal_payloads = self._load_signal_invalidation_payloads(sorted(signal_ids))
        watchlist = [
            self._build_exit_watch_item(
                position=position,
                recommendation_map=recommendation_map_by_account.get(account_id, {}),
                transition_order_map=transition_order_map_by_account.get(account_id, {}),
                signal_payloads=signal_payloads,
            )
            for account_id, account_positions in positions_by_account.items()
            for position in account_positions
        ]
        watchlist.sort(
            key=lambda item: (
                int(item.get("priority_rank", 99)),
                -float(item.get("market_value", 0.0) or 0.0),
                str(item.get("asset_code") or ""),
            )
        )
        return watchlist

    def _build_exit_watch_item(
        self,
        *,
        position: dict[str, Any],
        recommendation_map: dict[str, Any],
        transition_order_map: dict[str, Any],
        signal_payloads: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        asset_code = str(position.get("asset_code") or "").upper()
        recommendation = recommendation_map.get(asset_code)
        order_entry = transition_order_map.get(asset_code, {})
        order = order_entry.get("order")
        plan_id = str(order_entry.get("plan_id") or "")
        signal_id = self._safe_int(position.get("signal_id"))
        if signal_id is None and recommendation is not None:
            signal_id = self._safe_int(
                next(iter(getattr(recommendation, "source_signal_ids", []) or []), None)
            )
        signal_payload = signal_payloads.get(str(signal_id), {}) if signal_id is not None else {}

        is_invalidated = bool(position.get("is_invalidated"))
        exit_action = "HOLD"
        exit_action_label = "继续跟踪"
        exit_source = "tracking.only"
        exit_reason_code = "TRACKING_ONLY"
        exit_reason_text = "当前未触发退出或减仓条件，继续跟踪。"
        reduce_quantity: int | None = None
        priority_rank = 2

        if is_invalidated:
            exit_action = "SELL"
            exit_action_label = "立即退出"
            exit_source = "simulated_trading.position_invalidation"
            exit_reason_code = "POSITION_INVALIDATED"
            exit_reason_text = str(position.get("invalidation_reason") or "持仓已被证伪。")
            priority_rank = 0
        elif (
            order is not None
            and getattr(order, "action", "") in {"EXIT", "REDUCE"}
            and bool(getattr(order, "is_ready_for_approval", False))
        ):
            order_action = str(getattr(order, "action", "")).upper()
            exit_action = "SELL" if order_action == "EXIT" else "REDUCE"
            exit_action_label = "立即退出" if exit_action == "SELL" else "减仓"
            exit_source = "decision_rhythm.transition_plan"
            exit_reason_code = f"TRANSITION_PLAN_{order_action}"
            exit_reason_text = str(
                getattr(order, "invalidation_description", "") or f"调仓计划建议 {order_action}"
            )
            reduce_quantity = (
                abs(int(getattr(order, "delta_qty", 0) or 0)) if exit_action == "REDUCE" else None
            )
            priority_rank = 0 if exit_action == "SELL" else 1
        elif str(getattr(recommendation, "side", "") or "").upper() == "SELL":
            exit_action = "SELL"
            exit_action_label = "立即退出"
            exit_source = "decision_rhythm.recommendation"
            exit_reason_code = "UNIFIED_RECOMMENDATION_SELL"
            exit_reason_text = str(
                getattr(recommendation, "human_rationale", "") or "统一推荐已转为 SELL。"
            )
            priority_rank = 1

        decision_side = str(getattr(recommendation, "side", "") or "HOLD").upper()
        stop_loss_price = self._normalize_decimal_string(
            getattr(order, "stop_loss_price", None)
            or getattr(recommendation, "stop_loss_price", None)
        )
        target_price_low = self._normalize_decimal_string(
            getattr(recommendation, "target_price_low", None)
        )
        target_price_high = self._normalize_decimal_string(
            getattr(recommendation, "target_price_high", None)
        )
        invalidation_summary = (
            str(position.get("invalidation_description") or "").strip()
            or str(getattr(order, "invalidation_description", "") or "").strip()
            or str(
                signal_payload.get("invalidation_description")
                or signal_payload.get("invalidation_logic")
                or ""
            ).strip()
            or "暂无持仓级证伪摘要。"
        )
        contract_ready = bool(
            stop_loss_price is not None
            and float(stop_loss_price) > 0
            and invalidation_summary != "暂无持仓级证伪摘要。"
        )

        source_signal_ids = [
            str(item)
            for item in (getattr(recommendation, "source_signal_ids", []) or [])
            if str(item or "").strip()
        ]
        if signal_id is not None and str(signal_id) not in source_signal_ids:
            source_signal_ids.insert(0, str(signal_id))

        recommendation_id = str(getattr(recommendation, "recommendation_id", "") or "")
        account_id = self._safe_int(position.get("account_id"))
        invalidation_conditions = []
        invalidation_rule = getattr(order, "invalidation_rule", None) or signal_payload.get(
            "invalidation_rule_json", {}
        )
        if isinstance(invalidation_rule, dict):
            invalidation_conditions = [
                str(item)
                for item in (invalidation_rule.get("conditions") or [])
                if str(item or "").strip()
            ]
        recommendation_user_action = ""
        recommendation_snapshot = {}
        if recommendation is not None:
            recommendation_user_action = normalize_exit_user_action(
                getattr(
                    getattr(recommendation, "user_action", None),
                    "value",
                    getattr(recommendation, "user_action", ""),
                )
            )
            recommendation_snapshot = {
                "recommendation_id": recommendation_id,
                "side": str(getattr(recommendation, "side", "") or ""),
                "status": getattr(
                    getattr(recommendation, "status", None),
                    "value",
                    getattr(recommendation, "status", ""),
                ),
                "user_action": recommendation_user_action,
                "user_action_label": build_exit_user_action_label(recommendation_user_action),
                "is_processed": recommendation_user_action in {"ADOPTED", "IGNORED"},
                "confidence": float(getattr(recommendation, "confidence", 0.0) or 0.0),
                "composite_score": float(getattr(recommendation, "composite_score", 0.0) or 0.0),
                "alpha_model_score": float(
                    getattr(recommendation, "alpha_model_score", 0.0) or 0.0
                ),
                "human_rationale": str(getattr(recommendation, "human_rationale", "") or ""),
                "reason_codes": list(getattr(recommendation, "reason_codes", []) or []),
                "target_price_low": self._normalize_decimal_string(
                    getattr(recommendation, "target_price_low", None)
                ),
                "target_price_high": self._normalize_decimal_string(
                    getattr(recommendation, "target_price_high", None)
                ),
                "stop_loss_price": self._normalize_decimal_string(
                    getattr(recommendation, "stop_loss_price", None)
                ),
            }
        transition_plan_snapshot = {}
        if order is not None:
            transition_plan_snapshot = {
                "plan_id": plan_id,
                "action": str(getattr(order, "action", "") or ""),
                "current_qty": int(getattr(order, "current_qty", 0) or 0),
                "target_qty": int(getattr(order, "target_qty", 0) or 0),
                "delta_qty": int(getattr(order, "delta_qty", 0) or 0),
                "stop_loss_price": self._normalize_decimal_string(
                    getattr(order, "stop_loss_price", None)
                ),
                "price_band_low": self._normalize_decimal_string(
                    getattr(order, "price_band_low", None)
                ),
                "price_band_high": self._normalize_decimal_string(
                    getattr(order, "price_band_high", None)
                ),
                "invalidation_description": str(
                    getattr(order, "invalidation_description", "") or ""
                ),
                "notes": [
                    str(item)
                    for item in (getattr(order, "notes", []) or [])
                    if str(item or "").strip()
                ],
                "is_ready_for_approval": bool(getattr(order, "is_ready_for_approval", False)),
            }
        signal_contract_snapshot = {
            "signal_id": signal_id,
            "invalidation_description": str(
                signal_payload.get("invalidation_description")
                or signal_payload.get("invalidation_logic")
                or ""
            ),
            "conditions": invalidation_conditions,
        }
        user_action_label = build_exit_user_action_label(recommendation_user_action)
        is_processed = recommendation_user_action in {"ADOPTED", "IGNORED"}
        workspace_step = 5 if plan_id or exit_action in {"SELL", "REDUCE"} else 4
        decision_workspace_url = build_decision_workspace_url(
            security_code=asset_code,
            source="dashboard-exit",
            step=workspace_step,
            account_id=account_id,
            action=exit_action,
        )

        return {
            "account_id": account_id,
            "account_name": str(position.get("account_name") or "默认账户"),
            "asset_code": asset_code,
            "asset_name": str(position.get("asset_name") or asset_code),
            "shares": float(position.get("shares") or 0.0),
            "market_value": float(position.get("market_value") or 0.0),
            "avg_cost": float(position.get("avg_cost") or 0.0),
            "current_price": float(position.get("current_price") or 0.0),
            "unrealized_pnl_pct": float(position.get("unrealized_pnl_pct") or 0.0),
            "opened_at": str(position.get("opened_at") or ""),
            "signal_id": signal_id,
            "source_signal_ids": source_signal_ids,
            "decision_side": decision_side,
            "decision_side_label": {
                "BUY": "继续看多/可加仓",
                "SELL": "统一推荐 SELL",
                "HOLD": "继续持有",
            }.get(decision_side, decision_side or "未覆盖"),
            "exit_action": exit_action,
            "exit_action_label": exit_action_label,
            "exit_source": exit_source,
            "exit_reason_code": exit_reason_code,
            "exit_reason_text": exit_reason_text,
            "reduce_quantity": reduce_quantity,
            "stop_loss_price": stop_loss_price,
            "target_price_low": target_price_low,
            "target_price_high": target_price_high,
            "invalidation_summary": invalidation_summary,
            "contract_ready": contract_ready,
            "contract_status_label": "已绑定退出契约" if contract_ready else "待补退出契约",
            "is_invalidated": is_invalidated,
            "invalidation_reason": str(position.get("invalidation_reason") or ""),
            "priority_rank": priority_rank,
            "priority_label": {
                0: "立即处理",
                1: "本轮评估",
                2: "持续跟踪",
            }.get(priority_rank, "持续跟踪"),
            "recommendation_id": recommendation_id,
            "user_action": recommendation_user_action,
            "user_action_label": user_action_label,
            "is_processed": is_processed,
            "recommendation_detail_url": (
                f"/api/decision/workspace/recommendations/?recommendation_id={recommendation_id}"
                if recommendation_id
                else ""
            ),
            "transition_plan_id": plan_id,
            "transition_plan_detail_url": (
                f"/api/decision/workspace/plans/{plan_id}/" if plan_id else ""
            ),
            "recommendation_snapshot": recommendation_snapshot,
            "transition_plan_snapshot": transition_plan_snapshot,
            "signal_contract_snapshot": signal_contract_snapshot,
            "account_detail_url": (
                f"/simulated-trading/my-accounts/{account_id}/" if account_id is not None else ""
            ),
            "decision_workspace_url": decision_workspace_url,
        }

    def _load_unified_recommendations(self, account_id: int) -> list[Any]:
        try:
            return list(self.unified_recommendation_repo.get_by_account(str(account_id)) or [])
        except Exception as exc:
            logger.warning(
                "Failed to load unified recommendations for dashboard exit watchlist %s: %s",
                account_id,
                exc,
            )
            return []

    def _load_transition_orders(
        self, *, account_id: int, trade_date: date
    ) -> dict[str, dict[str, Any]]:
        try:
            plan = self.transition_plan_repo.get_latest_for_account(str(account_id))
        except Exception as exc:
            logger.warning(
                "Failed to load transition plan for dashboard exit watchlist %s: %s",
                account_id,
                exc,
            )
            return {}

        if plan is None:
            return {}

        plan_as_of = getattr(plan, "as_of", None)
        plan_date = plan_as_of.date() if plan_as_of is not None else None
        if plan_date != trade_date:
            return {}

        order_map: dict[str, dict[str, Any]] = {}
        for order in getattr(plan, "orders", []) or []:
            security_code = str(getattr(order, "security_code", "") or "").upper()
            if security_code:
                order_map[security_code] = {
                    "order": order,
                    "plan_id": str(getattr(plan, "plan_id", "") or ""),
                }
        return order_map

    def _load_signal_invalidation_payloads(
        self, signal_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        if not signal_ids:
            return {}
        try:
            return get_signal_repository().get_invalidation_payloads(signal_ids)
        except Exception as exc:
            logger.warning(
                "Failed to load signal invalidation payloads for dashboard exit watchlist: %s",
                exc,
            )
            return {}

    @staticmethod
    def _build_exit_watch_summary(watchlist: list[dict[str, Any]]) -> dict[str, Any]:
        urgent_count = sum(1 for item in watchlist if item.get("priority_rank") == 0)
        sell_count = sum(1 for item in watchlist if item.get("exit_action") == "SELL")
        reduce_count = sum(1 for item in watchlist if item.get("exit_action") == "REDUCE")
        hold_count = sum(1 for item in watchlist if item.get("exit_action") == "HOLD")
        return {
            "total": len(watchlist),
            "urgent_count": urgent_count,
            "sell_count": sell_count,
            "reduce_count": reduce_count,
            "hold_count": hold_count,
        }

    @staticmethod
    def _latest_recommendations_by_security(recommendations: list[Any]) -> dict[str, Any]:
        latest_by_security: dict[str, Any] = {}
        for recommendation in recommendations:
            security_code = str(getattr(recommendation, "security_code", "") or "").upper()
            if not security_code:
                continue

            current = latest_by_security.get(security_code)
            if current is None:
                latest_by_security[security_code] = recommendation
                continue

            current_time = getattr(current, "updated_at", None) or getattr(
                current, "created_at", None
            )
            next_time = getattr(recommendation, "updated_at", None) or getattr(
                recommendation,
                "created_at",
                None,
            )
            if next_time and (current_time is None or next_time >= current_time):
                latest_by_security[security_code] = recommendation
        return latest_by_security

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_decimal_string(value: Any) -> str | None:
        if value in (None, "", 0, "0"):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 0:
            return None
        return f"{numeric:.2f}"
