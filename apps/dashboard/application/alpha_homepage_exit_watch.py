"""Exit-watch construction for the Dashboard Alpha homepage."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

from apps.dashboard.application.navigation import (
    build_decision_workspace_url,
    build_exit_user_action_label,
    normalize_exit_user_action,
)
from apps.decision_rhythm.application.exit_advisors import (
    PortfolioTransitionPlanRepositoryProtocol,
    UnifiedRecommendationRepositoryProtocol,
)
from apps.signal.application.repository_provider import get_signal_repository
from apps.simulated_trading.application.query_services import list_user_position_payloads
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

_SECURITY_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,19}$")
_DETAIL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_DATABASE_ID = 2_147_483_647
_MAX_QUANTITY = 9_007_199_254_740_991
_EXIT_WATCH_SOURCE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class AlphaExitWatchMixin:
    """Private behavior shard for AlphaHomepageQuery."""

    unified_recommendation_repo: UnifiedRecommendationRepositoryProtocol
    transition_plan_repo: PortfolioTransitionPlanRepositoryProtocol

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
            if not isinstance(position, dict):
                continue
            account_id = self._safe_int(position.get("account_id"))
            asset_code = self._normalize_security_code(position.get("asset_code"))
            if account_id is None or asset_code is None:
                continue
            normalized_position = dict(position)
            normalized_position["asset_code"] = asset_code
            positions_by_account[account_id].append(normalized_position)
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
                self._safe_quantity(
                    item.get("priority_rank"),
                    minimum=0,
                    maximum=99,
                    default=99,
                ),
                -(self._exit_watch_float(item.get("market_value"), minimum=0.0) or 0.0),
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
        asset_code = self._normalize_security_code(position.get("asset_code")) or ""
        recommendation = recommendation_map.get(asset_code)
        order_entry = transition_order_map.get(asset_code, {})
        order = order_entry.get("order")
        plan_id = self._normalize_detail_id(order_entry.get("plan_id")) or ""
        signal_id = self._safe_int(position.get("signal_id"))
        if signal_id is None and recommendation is not None:
            signal_id = self._safe_int(
                next(iter(getattr(recommendation, "source_signal_ids", []) or []), None)
            )
        raw_signal_payload = (
            signal_payloads.get(str(signal_id), {}) if signal_id is not None else {}
        )
        signal_payload = raw_signal_payload if isinstance(raw_signal_payload, Mapping) else {}

        is_invalidated = position.get("is_invalidated") is True
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
            exit_reason_text = self._bounded_text(
                position.get("invalidation_reason"),
                default="持仓已被证伪。",
            )
            priority_rank = 0
        elif (
            order is not None
            and self._normalized_choice(getattr(order, "action", ""), {"EXIT", "REDUCE"})
            is not None
            and getattr(order, "is_ready_for_approval", False) is True
        ):
            order_action = (
                self._normalized_choice(getattr(order, "action", ""), {"EXIT", "REDUCE"}) or ""
            )
            exit_action = "SELL" if order_action == "EXIT" else "REDUCE"
            exit_action_label = "立即退出" if exit_action == "SELL" else "减仓"
            exit_source = "decision_rhythm.transition_plan"
            exit_reason_code = f"TRANSITION_PLAN_{order_action}"
            exit_reason_text = self._bounded_text(
                getattr(order, "invalidation_description", ""),
                default=f"调仓计划建议 {order_action}",
            )
            delta_quantity = self._safe_quantity(
                getattr(order, "delta_qty", 0),
                minimum=-_MAX_QUANTITY,
                maximum=_MAX_QUANTITY,
                default=0,
            )
            reduce_quantity = abs(delta_quantity) if exit_action == "REDUCE" else None
            priority_rank = 0 if exit_action == "SELL" else 1
        elif (
            self._normalized_choice(getattr(recommendation, "side", ""), {"BUY", "HOLD", "SELL"})
            == "SELL"
        ):
            exit_action = "SELL"
            exit_action_label = "立即退出"
            exit_source = "decision_rhythm.recommendation"
            exit_reason_code = "UNIFIED_RECOMMENDATION_SELL"
            exit_reason_text = self._bounded_text(
                getattr(recommendation, "human_rationale", ""),
                default="统一推荐已转为 SELL。",
            )
            priority_rank = 1

        decision_side = (
            self._normalized_choice(getattr(recommendation, "side", ""), {"BUY", "HOLD", "SELL"})
            or "HOLD"
        )
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
            self._bounded_text(position.get("invalidation_description"), default="")
            or self._bounded_text(getattr(order, "invalidation_description", ""), default="")
            or self._bounded_text(
                signal_payload.get("invalidation_description")
                or signal_payload.get("invalidation_logic"),
                default="",
            )
            or "暂无持仓级证伪摘要。"
        )
        contract_ready = bool(
            stop_loss_price is not None and invalidation_summary != "暂无持仓级证伪摘要。"
        )

        source_signal_ids: list[str] = []
        raw_source_signal_ids = getattr(recommendation, "source_signal_ids", []) or []
        if isinstance(raw_source_signal_ids, (list, tuple, set)):
            for item in raw_source_signal_ids:
                normalized_id = self._safe_int(item)
                if normalized_id is not None and str(normalized_id) not in source_signal_ids:
                    source_signal_ids.append(str(normalized_id))
        if signal_id is not None and str(signal_id) not in source_signal_ids:
            source_signal_ids.insert(0, str(signal_id))

        recommendation_id = (
            self._normalize_detail_id(getattr(recommendation, "recommendation_id", "")) or ""
        )
        account_id = self._safe_int(position.get("account_id"))
        invalidation_conditions = []
        invalidation_rule = getattr(order, "invalidation_rule", None) or signal_payload.get(
            "invalidation_rule_json", {}
        )
        if isinstance(invalidation_rule, dict):
            invalidation_conditions = self._bounded_text_list(
                invalidation_rule.get("conditions"),
                max_items=20,
                max_length=500,
            )
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
                "side": self._normalized_choice(
                    getattr(recommendation, "side", ""), {"BUY", "HOLD", "SELL"}
                )
                or "",
                "status": self._bounded_text(
                    getattr(
                        getattr(recommendation, "status", None),
                        "value",
                        getattr(recommendation, "status", ""),
                    ),
                    default="",
                    max_length=64,
                ),
                "user_action": recommendation_user_action,
                "user_action_label": build_exit_user_action_label(recommendation_user_action),
                "is_processed": recommendation_user_action in {"ADOPTED", "IGNORED"},
                "confidence": self._exit_watch_float(
                    getattr(recommendation, "confidence", 0.0),
                    minimum=0.0,
                    maximum=1.0,
                )
                or 0.0,
                "composite_score": self._exit_watch_float(
                    getattr(recommendation, "composite_score", 0.0),
                    minimum=-1.0,
                    maximum=1.0,
                )
                or 0.0,
                "alpha_model_score": self._exit_watch_float(
                    getattr(recommendation, "alpha_model_score", 0.0),
                    minimum=-1.0,
                    maximum=1.0,
                )
                or 0.0,
                "human_rationale": self._bounded_text(
                    getattr(recommendation, "human_rationale", ""), default=""
                ),
                "reason_codes": self._bounded_text_list(
                    getattr(recommendation, "reason_codes", []),
                    max_items=30,
                    max_length=128,
                ),
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
                "action": self._normalized_choice(
                    getattr(order, "action", ""), {"BUY", "EXIT", "HOLD", "REDUCE"}
                )
                or "",
                "current_qty": self._safe_quantity(
                    getattr(order, "current_qty", 0),
                    minimum=0,
                    maximum=_MAX_QUANTITY,
                    default=0,
                ),
                "target_qty": self._safe_quantity(
                    getattr(order, "target_qty", 0),
                    minimum=0,
                    maximum=_MAX_QUANTITY,
                    default=0,
                ),
                "delta_qty": self._safe_quantity(
                    getattr(order, "delta_qty", 0),
                    minimum=-_MAX_QUANTITY,
                    maximum=_MAX_QUANTITY,
                    default=0,
                ),
                "stop_loss_price": self._normalize_decimal_string(
                    getattr(order, "stop_loss_price", None)
                ),
                "price_band_low": self._normalize_decimal_string(
                    getattr(order, "price_band_low", None)
                ),
                "price_band_high": self._normalize_decimal_string(
                    getattr(order, "price_band_high", None)
                ),
                "invalidation_description": self._bounded_text(
                    getattr(order, "invalidation_description", ""), default=""
                ),
                "notes": self._bounded_text_list(
                    getattr(order, "notes", []),
                    max_items=30,
                    max_length=500,
                ),
                "is_ready_for_approval": getattr(order, "is_ready_for_approval", False) is True,
            }
        signal_contract_snapshot = {
            "signal_id": signal_id,
            "invalidation_description": self._bounded_text(
                signal_payload.get("invalidation_description")
                or signal_payload.get("invalidation_logic"),
                default="",
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
            "account_name": self._bounded_text(
                position.get("account_name"), default="默认账户", max_length=120
            ),
            "asset_code": asset_code,
            "asset_name": self._bounded_text(
                position.get("asset_name"), default=asset_code, max_length=120
            ),
            "shares": self._exit_watch_float(position.get("shares"), minimum=0.0) or 0.0,
            "market_value": self._exit_watch_float(position.get("market_value"), minimum=0.0)
            or 0.0,
            "avg_cost": self._exit_watch_float(position.get("avg_cost"), minimum=0.0) or 0.0,
            "current_price": self._exit_watch_float(position.get("current_price"), minimum=0.0)
            or 0.0,
            "unrealized_pnl_pct": self._exit_watch_float(position.get("unrealized_pnl_pct")) or 0.0,
            "opened_at": self._bounded_text(position.get("opened_at"), default="", max_length=64),
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
            "invalidation_reason": self._bounded_text(
                position.get("invalidation_reason"), default=""
            ),
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
        except _EXIT_WATCH_SOURCE_EXCEPTIONS:
            logger.warning(
                "Failed to load unified recommendations for dashboard exit watchlist %s",
                account_id,
            )
            return []

    def _load_transition_orders(
        self, *, account_id: int, trade_date: date
    ) -> dict[str, dict[str, Any]]:
        try:
            plan = self.transition_plan_repo.get_latest_for_account(str(account_id))
        except _EXIT_WATCH_SOURCE_EXCEPTIONS:
            logger.warning(
                "Failed to load transition plan for dashboard exit watchlist %s",
                account_id,
            )
            return {}

        if plan is None:
            return {}

        plan_as_of = getattr(plan, "as_of", None)
        if not isinstance(plan_as_of, datetime) or self._aware_datetime(plan_as_of) is None:
            return {}
        plan_date = plan_as_of.date()
        if plan_date != trade_date:
            return {}

        order_map: dict[str, dict[str, Any]] = {}
        for order in getattr(plan, "orders", []) or []:
            security_code = self._normalize_security_code(getattr(order, "security_code", ""))
            if security_code is not None:
                order_map[security_code] = {
                    "order": order,
                    "plan_id": self._normalize_detail_id(getattr(plan, "plan_id", "")) or "",
                }
        return order_map

    def _load_signal_invalidation_payloads(
        self, signal_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        if not signal_ids:
            return {}
        try:
            return get_signal_repository().get_invalidation_payloads(signal_ids)
        except _EXIT_WATCH_SOURCE_EXCEPTIONS:
            logger.warning(
                "Failed to load signal invalidation payloads for dashboard exit watchlist"
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
            security_code = AlphaExitWatchMixin._normalize_security_code(
                getattr(recommendation, "security_code", "")
            )
            if security_code is None:
                continue

            current = latest_by_security.get(security_code)
            if current is None:
                latest_by_security[security_code] = recommendation
                continue

            current_time = AlphaExitWatchMixin._aware_datetime(
                getattr(current, "updated_at", None) or getattr(current, "created_at", None)
            )
            next_time = AlphaExitWatchMixin._aware_datetime(
                getattr(recommendation, "updated_at", None)
                or getattr(recommendation, "created_at", None)
            )
            if next_time is not None and (current_time is None or next_time >= current_time):
                latest_by_security[security_code] = recommendation
        return latest_by_security

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            normalized = value
        elif isinstance(value, str):
            candidate = value.strip()
            if not candidate or not candidate.isascii() or not candidate.isdecimal():
                return None
            normalized = int(candidate)
        else:
            return None
        return normalized if 1 <= normalized <= _MAX_DATABASE_ID else None

    @staticmethod
    def _normalize_decimal_string(value: Any) -> str | None:
        numeric = AlphaExitWatchMixin._exit_watch_float(value, minimum=0.0)
        if numeric is None or numeric <= 0:
            return None
        return f"{numeric:.2f}"

    @staticmethod
    def _exit_watch_float(
        value: object,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        """Return a finite bounded float from an exit-watch provider value."""

        if isinstance(value, bool):
            return None
        numeric = safe_float(value)
        if numeric is None:
            return None
        if minimum is not None and numeric < minimum:
            return None
        if maximum is not None and numeric > maximum:
            return None
        return numeric

    @staticmethod
    def _safe_quantity(
        value: object,
        *,
        minimum: int,
        maximum: int,
        default: int,
    ) -> int:
        """Return an exact bounded integer without coercing bool or floats."""

        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            normalized = value
        elif isinstance(value, str):
            candidate = value.strip()
            digits = candidate[1:] if candidate.startswith("-") else candidate
            if not digits or not digits.isascii() or not digits.isdecimal():
                return default
            normalized = int(candidate)
        else:
            return default
        return normalized if minimum <= normalized <= maximum else default

    @staticmethod
    def _normalize_security_code(value: object) -> str | None:
        """Return a canonical bounded security code for lookups and links."""

        if not isinstance(value, str):
            return None
        normalized = value.strip().upper()
        return normalized if _SECURITY_CODE_PATTERN.fullmatch(normalized) else None

    @staticmethod
    def _normalize_detail_id(value: object) -> str | None:
        """Return a path/query-safe recommendation or transition-plan identifier."""

        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized if _DETAIL_ID_PATTERN.fullmatch(normalized) else None

    @staticmethod
    def _normalized_choice(value: object, choices: set[str]) -> str | None:
        """Return an uppercase provider token only when it is explicitly supported."""

        if not isinstance(value, str):
            return None
        normalized = value.strip().upper()
        return normalized if normalized in choices else None

    @staticmethod
    def _bounded_text(value: object, *, default: str, max_length: int = 500) -> str:
        """Return bounded single-line provider text or a stable fallback."""

        if not isinstance(value, str):
            return default
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > max_length
            or "\n" in normalized
            or "\r" in normalized
        ):
            return default
        return normalized

    @staticmethod
    def _bounded_text_list(
        value: object,
        *,
        max_items: int,
        max_length: int,
    ) -> list[str]:
        """Return a bounded list of single-line provider strings."""

        if not isinstance(value, (list, tuple, set)):
            return []
        normalized: list[str] = []
        for item in value:
            text = AlphaExitWatchMixin._bounded_text(
                item,
                default="",
                max_length=max_length,
            )
            if text:
                normalized.append(text)
            if len(normalized) >= max_items:
                break
        return normalized

    @staticmethod
    def _aware_datetime(value: object) -> datetime | None:
        """Return an aware UTC datetime for safe ordering."""

        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(UTC)
