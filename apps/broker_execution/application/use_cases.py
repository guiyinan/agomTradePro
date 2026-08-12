"""Governed write use cases for broker execution."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from ..domain.rules import InvalidOrderTransitionError, target_status_for_order_action
from .authorization import require_action
from .ports import BrokerExecutionRepositoryProtocol
from .query_services import BrokerExecutionQueryService
from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionConflictError, BrokerExecutionValidationError

ADVISOR_EVIDENCE_BLOCKER = "advisor_order_intent_evidence_not_integrated"
ADVISOR_EVIDENCE_BLOCK_MESSAGE = (
    "Advisor live-order draft creation is blocked until Evidence is integrated"
)


def _request_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _finite_float(
    value: object,
    *,
    field_name: str,
    positive: bool = False,
) -> float:
    """Parse a finite numeric boundary value or fail closed."""

    try:
        numeric = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise BrokerExecutionValidationError(f"{field_name} must be numeric") from exc
    if not math.isfinite(numeric) or (numeric <= 0 if positive else numeric < 0):
        qualifier = "positive finite" if positive else "non-negative finite"
        raise BrokerExecutionValidationError(f"{field_name} must be a {qualifier} number")
    return numeric


class AccountProjectionProviderProtocol(Protocol):
    """Load the server-side account projection used for pre-trade checks."""

    def __call__(
        self,
        *,
        user_id: int,
        account_id: int,
    ) -> dict[str, Any] | None: ...


class RiskEvaluatorProtocol(Protocol):
    """Evaluate one normalized order against server-side risk policy."""

    def execute(self, **kwargs: Any) -> object: ...


class LatestQuoteProviderProtocol(Protocol):
    """Return a server-side market quote for one symbol."""

    def __call__(self, asset_code: str) -> dict[str, Any] | None: ...


class CreateLiveOrderFromExecutionPlanUseCase:
    """Create an idempotent order only from a passed, persisted plan projection."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
        *,
        account_projection_provider: AccountProjectionProviderProtocol | None = None,
        risk_evaluator: RiskEvaluatorProtocol | None = None,
        latest_quote_provider: LatestQuoteProviderProtocol | None = None,
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

            self.risk_evaluator = cast(
                RiskEvaluatorProtocol,
                EvaluatePreTradeRiskUseCase(),
            )
        else:
            self.risk_evaluator = risk_evaluator
        if latest_quote_provider is None:
            from apps.data_center.application.public import (
                get_published_latest_quote_payload,
            )

            def latest_quote_provider(asset_code: str) -> dict[str, Any] | None:
                return get_published_latest_quote_payload(asset_code)

        self.account_projection_provider = account_projection_provider
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
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if not normalized_idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
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
        account_owner_id = self.repository.get_bound_account_owner_id(account_id=account_id)
        if account_owner_id is None:
            raise BrokerExecutionValidationError("The live account has no active QMT binding")
        projection = self.account_projection_provider(
            user_id=account_owner_id,
            account_id=account_id,
        )
        if not projection:
            raise BrokerExecutionValidationError("The unified account does not exist")
        if projection.get("account_type") != "real" or not projection.get("is_active"):
            raise BrokerExecutionValidationError("Live execution requires an active real account")
        symbol = str(plan["asset_code"]).strip().upper()
        if not symbol:
            raise BrokerExecutionValidationError("asset_code is required")
        side = str(plan["side"]).strip().upper()
        if side not in {"BUY", "SELL"}:
            raise BrokerExecutionValidationError("Order side must be BUY or SELL")
        try:
            quantity_decimal = Decimal(str(plan["quantity"]))
            limit_price_decimal = Decimal(str(plan["limit_price"]))
        except (InvalidOperation, ValueError) as exc:
            raise BrokerExecutionValidationError(
                "Order quantity and limit price must be numeric"
            ) from exc
        if (
            not quantity_decimal.is_finite()
            or not limit_price_decimal.is_finite()
            or quantity_decimal <= 0
            or limit_price_decimal <= 0
        ):
            raise BrokerExecutionValidationError(
                "Order quantity and limit price must be positive finite numbers"
            )
        quantity = _finite_float(
            quantity_decimal,
            field_name="quantity",
            positive=True,
        )
        limit_price = _finite_float(
            limit_price_decimal,
            field_name="limit_price",
            positive=True,
        )
        account_equity = _finite_float(
            projection.get("total_asset"),
            field_name="account total_asset",
            positive=True,
        )
        total_position_value = _finite_float(
            projection.get("total_position_value") or 0,
            field_name="account total_position_value",
        )
        cash_balance = _finite_float(
            projection.get("cash_available") or 0,
            field_name="account cash_available",
        )

        symbol_position: dict[str, Any] = next(
            (
                row
                for row in projection.get("positions", [])
                if str(row.get("asset_code") or "").upper() == symbol
            ),
            {},
        )
        current_symbol_position_value = _finite_float(
            symbol_position.get("market_value") or 0,
            field_name="symbol market_value",
        )
        risk_result = self.risk_evaluator.execute(
            account_id=account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=limit_price,
            account_equity=account_equity,
            total_position_value=total_position_value,
            cash_balance=cash_balance,
            current_symbol_position_value=current_symbol_position_value,
        )
        risk_snapshot = (
            asdict(cast(Any, risk_result))
            if is_dataclass(risk_result) and not isinstance(risk_result, type)
            else dict(cast(dict[str, Any], risk_result))
        )
        risk_snapshot.setdefault("violations", [])
        if not isinstance(risk_snapshot["violations"], list):
            raise BrokerExecutionValidationError(
                "Risk evaluator returned an invalid violations payload"
            )
        quote = self.latest_quote_provider(symbol)
        if not quote:
            risk_snapshot["violations"].append("latest market quote is unavailable")
        elif quote.get("must_not_use_for_decision") or quote.get("is_stale"):
            risk_snapshot["violations"].append("latest market quote is stale")
        else:
            try:
                quote_price = float(cast(Any, quote.get("current_price")))
            except (TypeError, ValueError, OverflowError):
                quote_price = float("nan")
            if not math.isfinite(quote_price) or quote_price <= 0:
                risk_snapshot["violations"].append(
                    "latest market price must be positive and finite"
                )
        risk_snapshot["passed"] = (
            bool(risk_snapshot.get("passed")) and not risk_snapshot["violations"]
        )
        risk_snapshot["market_snapshot"] = quote or {}
        normalized["asset_code"] = symbol
        normalized["side"] = side
        normalized["quantity"] = str(quantity_decimal)
        normalized["limit_price"] = str(limit_price_decimal)
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
            idempotency_key=normalized_idempotency_key,
            request_digest=_request_digest(normalized),
        )


class CreateLiveOrdersFromAdvisorExecutionPlanUseCase:
    """Fail closed before an unbound advisor intent can become a live-order draft."""

    def __init__(self, order_creator: Any | None = None) -> None:
        self.order_creator = order_creator or CreateLiveOrderFromExecutionPlanUseCase()

    def execute(
        self,
        *,
        actor: Any,
        execution_plan: dict[str, Any],
        idempotency_prefix: str,
    ) -> dict[str, Any]:
        """Reject direct callers until exact Evidence binding is implemented."""

        del actor, execution_plan, idempotency_prefix
        raise BrokerExecutionConflictError(ADVISOR_EVIDENCE_BLOCK_MESSAGE)


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

    def __init__(
        self,
        *,
        sheet_provider: Any | None = None,
        order_creator: Any | None = None,
    ) -> None:
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
            "commit_allowed": False,
            "confirmation_required": True,
            "actor_role": role,
            "account_id": int(account_id),
            "plan_digest": digest,
            "orders_count": int(execution_plan.get("orders_count") or 0),
            "orders": list(execution_plan.get("orders") or []),
            "display_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "blocker_codes": [ADVISOR_EVIDENCE_BLOCKER],
            "warning": ADVISOR_EVIDENCE_BLOCK_MESSAGE,
        }
        if preview_only:
            return preview
        del expected_plan_digest, idempotency_key
        raise BrokerExecutionConflictError(ADVISOR_EVIDENCE_BLOCK_MESSAGE)


class PreviewOrMutateOrderUseCase:
    """Preview and commit one governed order lifecycle action."""

    _ROLE_ACTIONS = {
        "approve": "approve",
        "reject": "reject",
        "cancel": "cancel",
    }

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
            target_status = target_status_for_order_action(str(order["status"]), normalized_action)
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

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        payload = {
            "account_id": int(account_id),
            "active": bool(active),
            "reason": normalized_reason,
        }
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
