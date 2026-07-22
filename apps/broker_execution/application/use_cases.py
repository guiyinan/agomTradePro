"""Governed write use cases for broker execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from ..domain.rules import InvalidOrderTransitionError, target_status_for_order_action
from .authorization import require_action
from .query_services import BrokerExecutionQueryService
from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionValidationError


def _request_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CreateLiveOrderFromExecutionPlanUseCase:
    """Create an idempotent order only from a passed, persisted plan projection."""

    def __init__(
        self,
        repository=None,
        *,
        account_projection_provider=None,
        risk_evaluator=None,
        latest_quote_provider=None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()
        if account_projection_provider is None:
            from apps.simulated_trading.application.query_services import (
                get_account_execution_projection,
            )

            account_projection_provider = get_account_execution_projection
        if risk_evaluator is None:
            from apps.risk_center.application.trade_guard import (
                EvaluatePreTradeRiskUseCase,
            )

            risk_evaluator = EvaluatePreTradeRiskUseCase()
        if latest_quote_provider is None:
            from apps.data_center.application.dtos import LatestQuoteRequest
            from apps.data_center.application.interface_services import (
                make_query_latest_quote_use_case,
            )

            def latest_quote_provider(asset_code: str) -> dict[str, Any] | None:
                response = make_query_latest_quote_use_case().execute(
                    LatestQuoteRequest(asset_code=asset_code)
                )
                return response.to_dict() if response else None

        self.account_projection_provider = account_projection_provider
        self.risk_evaluator = risk_evaluator
        self.latest_quote_provider = latest_quote_provider

    def execute(
        self,
        *,
        actor: Any,
        plan: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Validate source/risk evidence before creating WAITING_APPROVAL."""

        user_id, role, is_admin = require_action(actor, "create_draft")
        required = {
            "account_id",
            "asset_code",
            "side",
            "quantity",
            "limit_price",
            "expires_at",
            "source_recommendation_ids",
        }
        missing = sorted(required - set(plan))
        if missing:
            raise BrokerExecutionValidationError(f"Execution plan missing fields: {missing}")
        if not plan.get("source_recommendation_ids"):
            raise BrokerExecutionValidationError("A source recommendation is required")
        account_id = int(plan["account_id"])
        if not self.repository.has_account_access(
            user_id=user_id,
            is_admin=is_admin,
            account_id=account_id,
            action="trade",
        ):
            from .use_case_errors import BrokerExecutionPermissionError

            self.repository.record_permission_denial(
                user_id=user_id,
                action="account:create_draft",
                role=role,
            )
            raise BrokerExecutionPermissionError("Account access is not authorized")
        normalized = dict(plan)
        normalized["account_id"] = account_id
        account_owner_id = self.repository.get_bound_account_owner_id(
            account_id=account_id
        )
        if account_owner_id is None:
            raise BrokerExecutionValidationError(
                "The live account has no active QMT binding"
            )
        projection = self.account_projection_provider(
            user_id=account_owner_id,
            account_id=account_id,
        )
        if not projection:
            raise BrokerExecutionValidationError("The unified account does not exist")
        if projection.get("account_type") != "real" or not projection.get("is_active"):
            raise BrokerExecutionValidationError("Live execution requires an active real account")
        symbol = str(plan["asset_code"]).strip().upper()
        symbol_position = next(
            (
                row
                for row in projection.get("positions", [])
                if str(row.get("asset_code") or "").upper() == symbol
            ),
            {},
        )
        risk_result = self.risk_evaluator.execute(
            account_id=account_id,
            symbol=symbol,
            side=str(plan["side"]),
            quantity=float(plan["quantity"]),
            price=float(plan["limit_price"]),
            account_equity=float(projection.get("total_asset") or 0),
            total_position_value=float(projection.get("total_position_value") or 0),
            cash_balance=float(projection.get("cash_available") or 0),
            current_symbol_position_value=float(symbol_position.get("market_value") or 0),
        )
        risk_snapshot = asdict(risk_result) if is_dataclass(risk_result) else dict(risk_result)
        risk_snapshot.setdefault("violations", [])
        quote = self.latest_quote_provider(symbol)
        if not quote:
            risk_snapshot["violations"].append("latest market quote is unavailable")
        elif quote.get("must_not_use_for_decision") or quote.get("is_stale"):
            risk_snapshot["violations"].append("latest market quote is stale")
        elif float(quote.get("current_price") or 0) <= 0:
            risk_snapshot["violations"].append("latest market price must be positive")
        risk_snapshot["passed"] = not risk_snapshot["violations"]
        risk_snapshot["market_snapshot"] = quote or {}
        normalized["asset_code"] = symbol
        normalized["risk_snapshot"] = risk_snapshot
        normalized["initial_status"] = (
            "WAITING_APPROVAL" if risk_snapshot.get("passed") else "RISK_REJECTED"
        )
        normalized["risk_policy_version"] = str(
            (risk_snapshot.get("effective_policy") or {}).get("version")
            or (risk_snapshot.get("effective_policy") or {}).get("policy_version")
            or ""
        )
        return self.repository.create_live_order(
            user_id=user_id,
            is_admin=is_admin,
            payload=normalized,
            idempotency_key=str(idempotency_key),
            request_digest=_request_digest(normalized),
        )


class CreateLiveOrdersFromAdvisorExecutionPlanUseCase:
    """Convert the auto-advisor's read-only plan into governed approval drafts."""

    def __init__(self, order_creator=None) -> None:
        self.order_creator = order_creator or CreateLiveOrderFromExecutionPlanUseCase()

    def execute(
        self,
        *,
        actor: Any,
        execution_plan: dict[str, Any],
        idempotency_prefix: str,
    ) -> dict[str, Any]:
        """Create only actionable advisor intents; every draft is risk-checked again."""

        if execution_plan.get("status") != "READY_FOR_CONFIRMATION":
            raise BrokerExecutionValidationError("Advisor execution plan is not actionable")
        prefix = str(idempotency_prefix or "").strip()
        if not prefix:
            raise BrokerExecutionValidationError("idempotency_prefix is required")
        created: list[dict[str, Any]] = []
        for item in execution_plan.get("orders") or []:
            side = str(item.get("side") or "").upper()
            normalized_side = "BUY" if side in {"BUY", "ADD"} else "SELL" if side in {"REDUCE", "EXIT"} else ""
            if not normalized_side:
                continue
            price = item.get("estimated_price")
            if price in (None, ""):
                price_band = item.get("price_band") or {}
                price = price_band.get("high") if normalized_side == "BUY" else price_band.get("low")
            if price in (None, ""):
                raise BrokerExecutionValidationError("Advisor order has no executable limit price")
            valid_until = item.get("valid_until")
            try:
                expires_at = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                expires_at = datetime.now(UTC) + timedelta(minutes=30)
            order_intent_id = str(item.get("order_intent_id") or "").strip()
            if not order_intent_id:
                raise BrokerExecutionValidationError("Advisor order_intent_id is required")
            source_recommendation_ids = list(item.get("source_recommendation_ids") or [])
            if not source_recommendation_ids:
                raise BrokerExecutionValidationError(
                    "Advisor order requires source recommendation evidence"
                )
            created.append(
                self.order_creator.execute(
                    actor=actor,
                    plan={
                        "account_id": int(item["account_id"]),
                        "asset_code": item["asset_code"],
                        "side": normalized_side,
                        "quantity": item["suggested_quantity"],
                        "limit_price": price,
                        "expires_at": expires_at.isoformat(),
                        "source_recommendation_ids": source_recommendation_ids,
                        "source_signal_ids": list(item.get("source_signal_ids") or []),
                    },
                    idempotency_key=f"{prefix}:{order_intent_id}",
                )
            )
        return {"created_orders": created, "created_count": len(created)}


def _advisor_plan_digest(execution_plan: dict[str, Any]) -> str:
    """Bind confirmation to the executable advisor facts, excluding display copy."""

    orders = []
    for item in execution_plan.get("orders") or []:
        orders.append(
            {
                key: item.get(key)
                for key in (
                    "order_intent_id",
                    "account_id",
                    "asset_code",
                    "side",
                    "suggested_quantity",
                    "suggested_amount",
                    "estimated_price",
                    "price_band",
                    "source_recommendation_ids",
                    "source_signal_ids",
                    "pre_trade_checks",
                )
            }
        )
    payload = {
        "status": execution_plan.get("status"),
        "execution_mode": execution_plan.get("execution_mode"),
        "orders": sorted(orders, key=lambda row: str(row.get("order_intent_id") or "")),
    }
    return _request_digest(payload)


class PreviewOrCreateAdvisorLiveOrdersUseCase:
    """Generate the current server-side advisor sheet and create governed drafts."""

    def __init__(self, *, sheet_provider=None, order_creator=None) -> None:
        if sheet_provider is None:
            from apps.decision_rhythm.application.advisor_services import (
                AdvisorAccessError,
                GenerateAdvisorDecisionSheetUseCase,
            )

            generator = GenerateAdvisorDecisionSheetUseCase()

            def sheet_provider(*, account_id: int, actor: Any) -> dict[str, Any]:
                try:
                    return generator.execute(account_id=str(account_id), user=actor)
                except AdvisorAccessError as exc:
                    from .use_case_errors import BrokerExecutionPermissionError

                    raise BrokerExecutionPermissionError(str(exc)) from exc

        self.sheet_provider = sheet_provider
        self.order_creator = order_creator or CreateLiveOrdersFromAdvisorExecutionPlanUseCase()

    def execute(
        self,
        *,
        actor: Any,
        account_id: int,
        preview_only: bool,
        expected_plan_digest: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Preview or create drafts without accepting caller-authored order fields."""

        _user_id, role, _is_admin = require_action(actor, "create_draft")
        sheet = self.sheet_provider(account_id=int(account_id), actor=actor)
        execution_plan = dict(sheet.get("execution_plan") or {})
        if execution_plan.get("status") != "READY_FOR_CONFIRMATION":
            raise BrokerExecutionValidationError(
                "The current advisor sheet has no executable orders"
            )
        if execution_plan.get("execution_mode") != "real_confirm_only":
            raise BrokerExecutionValidationError(
                "Only a real-account advisor plan can create live-order drafts"
            )
        digest = _advisor_plan_digest(execution_plan)
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "actor_role": role,
            "account_id": int(account_id),
            "plan_digest": digest,
            "orders_count": int(execution_plan.get("orders_count") or 0),
            "orders": list(execution_plan.get("orders") or []),
            "warning": "Commit creates risk-checked drafts; every order still requires approval.",
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        if not expected_plan_digest or expected_plan_digest != digest:
            raise BrokerExecutionValidationError(
                "The advisor execution plan changed after preview; preview it again"
            )
        result = self.order_creator.execute(
            actor=actor,
            execution_plan=execution_plan,
            idempotency_prefix=str(idempotency_key),
        )
        return {
            "preview_only": False,
            "plan_digest": digest,
            **result,
        }


class PreviewOrMutateOrderUseCase:
    """Preview and commit one governed order lifecycle action."""

    _ROLE_ACTIONS = {
        "approve": "approve",
        "reject": "reject",
        "cancel": "cancel",
    }

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        client_order_id: str,
        action: str,
        reason: str,
        preview_only: bool,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Preview or commit approve, reject, or cancel."""

        normalized_action = str(action or "").strip().lower()
        client_order_id_text = str(client_order_id)
        permission_action = self._ROLE_ACTIONS.get(normalized_action)
        if permission_action is None:
            raise BrokerExecutionValidationError(f"Unsupported order action: {action}")
        user_id, role, is_admin = require_action(actor, permission_action)
        order = self.repository.get_order(
            user_id=user_id,
            is_admin=is_admin,
            client_order_id=client_order_id_text,
        )
        if order is None:
            from .use_case_errors import BrokerExecutionNotFoundError

            raise BrokerExecutionNotFoundError("Live order does not exist")
        if not self.repository.has_account_access(
            user_id=user_id,
            is_admin=is_admin,
            account_id=int(order["account_id"]),
            action=normalized_action,
        ):
            from .use_case_errors import BrokerExecutionPermissionError

            self.repository.record_permission_denial(
                user_id=user_id,
                action=f"account:{normalized_action}",
                role=role,
            )
            raise BrokerExecutionPermissionError("Account access is not authorized")
        normalized_reason = str(reason or "").strip()
        try:
            target_status = target_status_for_order_action(
                str(order["status"]), normalized_action
            )
        except InvalidOrderTransitionError as exc:
            if preview_only:
                from .use_case_errors import BrokerExecutionConflictError

                raise BrokerExecutionConflictError(str(exc)) from exc
            target_status = None
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "action": normalized_action,
            "actor_role": role,
            "order": order,
            "summary": {
                "account_id": order["account_id"],
                "asset_code": order["asset_code"],
                "side": order["side"],
                "quantity": order["quantity"],
                "limit_price": order["limit_price"],
                "current_status": order["status"],
                "target_status": target_status.value if target_status else None,
                "cancellable_quantity": (
                    str(
                        max(
                            Decimal("0"),
                            Decimal(str(order["quantity"]))
                            - Decimal(str(order.get("filled_quantity") or "0")),
                        )
                    )
                    if normalized_action == "cancel"
                    else None
                ),
            },
        }
        if preview_only:
            return preview
        if not idempotency_key or not str(idempotency_key).strip():
            raise BrokerExecutionValidationError("idempotency_key is required")
        if expected_version is None:
            raise BrokerExecutionValidationError("expected_version is required")
        payload = {
            "client_order_id": client_order_id_text,
            "action": normalized_action,
            "reason": normalized_reason,
            "expected_version": int(expected_version),
        }
        return self.repository.mutate_order(
            user_id=user_id,
            is_admin=is_admin,
            client_order_id=client_order_id_text,
            action=normalized_action,
            reason=normalized_reason,
            expected_version=int(expected_version),
            idempotency_key=str(idempotency_key).strip(),
            request_digest=_request_digest(payload),
        )


class PreviewOrSetKillSwitchUseCase:
    """Preview and commit account-scoped trading stop or resume."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        account_id: int,
        active: bool,
        reason: str,
        preview_only: bool,
        idempotency_key: str | None = None,
        reauth: dict[str, Any] | None = None,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Preview or set the account kill switch."""

        permission_action = "kill_switch" if active else "resume"
        user_id, role, is_admin = require_action(actor, permission_action)
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise BrokerExecutionValidationError("reason is required")
        if int(account_id) > 0 and not self.repository.has_account_access(
            user_id=user_id,
            is_admin=is_admin,
            account_id=int(account_id),
            action="trade",
        ):
            from .use_case_errors import BrokerExecutionPermissionError

            self.repository.record_permission_denial(
                user_id=user_id,
                action="account:kill_switch" if active else "account:resume",
                role=role,
                request_context=request_context,
            )
            raise BrokerExecutionPermissionError("Account access is not authorized")
        kill_switch_targets = self.repository.list_kill_switch_targets(
            user_id=user_id,
            is_admin=is_admin,
            account_id=int(account_id),
        )
        if not kill_switch_targets:
            from .use_case_errors import BrokerExecutionNotFoundError

            raise BrokerExecutionNotFoundError(
                "No active broker account binding is available for this action"
            )
        overview = BrokerExecutionQueryService(self.repository).overview(actor=actor)
        resume_blockers: list[str] = []
        if not active:
            if int(overview.get("connections", {}).get("online", 0)) < 1:
                resume_blockers.append("No online QMT Agent connection")
            if int(overview.get("execution_exceptions", {}).get("count", 0)) > 0:
                resume_blockers.append("Execution exceptions remain unresolved")
            if int(overview.get("reconciliation_differences", {}).get("runs", 0)) > 0:
                resume_blockers.append("Reconciliation differences remain unresolved")
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "action": "trigger_kill_switch" if active else "resume_trading",
            "account_id": int(account_id),
            "actor_role": role,
            "reason": normalized_reason,
            "affected_accounts": kill_switch_targets,
            "affected_account_count": len(kill_switch_targets),
            "current_overview": overview,
            "resume_blockers": resume_blockers,
            "reauthentication_required": not active,
            "reauthentication_method": "password" if not active else None,
        }
        if preview_only:
            return preview
        if not idempotency_key or not str(idempotency_key).strip():
            raise BrokerExecutionValidationError("idempotency_key is required")
        if not active and resume_blockers:
            raise BrokerExecutionValidationError(
                "Trading cannot resume: " + "; ".join(resume_blockers)
            )
        if not active:
            method = str((reauth or {}).get("method") or "").strip().lower()
            credential = str((reauth or {}).get("credential") or "")
            checker = getattr(actor, "check_password", None)
            if (
                method != "password"
                or not credential
                or not callable(checker)
                or not bool(checker(credential))
            ):
                from .use_case_errors import BrokerExecutionPermissionError

                self.repository.record_permission_denial(
                    user_id=user_id,
                    action="resume:reauthentication",
                    role=role,
                    request_context=request_context,
                )
                raise BrokerExecutionPermissionError(
                    "Password reauthentication is required to resume live trading"
                )
        payload = {"account_id": int(account_id), "active": bool(active), "reason": normalized_reason}
        return self.repository.set_kill_switch(
            user_id=user_id,
            is_admin=is_admin,
            account_id=int(account_id),
            active=bool(active),
            reason=normalized_reason,
            idempotency_key=str(idempotency_key).strip(),
            request_digest=_request_digest(payload),
            request_context=request_context,
        )
