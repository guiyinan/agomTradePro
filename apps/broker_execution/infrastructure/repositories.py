"""Django repositories for broker execution."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from django.db import transaction
from django.db.models import Model, Sum
from django.utils import timezone

from apps.broker_execution.application.evidence_gate import (
    broker_order_evidence_integrated,
    require_broker_order_evidence,
)
from apps.broker_execution.application.execution_price_guard import require_current_execution_price
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    validate_order_transition,
)
from apps.broker_execution.order_checkpoint_composition import verify_order_checkpoint

from . import broker_order_checkpoint_queries
from .broker_repository_access import BrokerExecutionAccessMixin
from .broker_repository_agent_administration import (
    BrokerExecutionAgentAdministrationMixin,
)
from .broker_repository_agent_runtime import BrokerExecutionAgentRuntimeMixin
from .broker_repository_order_control import BrokerExecutionOrderControlMixin
from .broker_repository_reconciliation import BrokerExecutionReconciliationMixin
from .models import (
    BrokerAccountBindingModel,
    BrokerExecutionAuditModel,
    LiveOrderModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


class DjangoBrokerExecutionRepository(
    BrokerExecutionAccessMixin,
    BrokerExecutionOrderControlMixin,
    BrokerExecutionAgentRuntimeMixin,
    BrokerExecutionAgentAdministrationMixin,
    BrokerExecutionReconciliationMixin,
):
    """Compose scoped broker-execution repository responsibilities."""

    def get_signed_order_plan(
        self, *, user_id: int, account_id: int, client_order_id: UUID
    ) -> dict[str, Any]:
        """Read the source order for risk evaluation before the locked creation check."""
        return broker_order_checkpoint_queries.get_signed_order_plan(
            user_id=user_id, account_id=account_id, client_order_id=client_order_id
        )

    def create_live_order(
        self,
        *,
        user_id: int,
        is_admin: bool,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Persist one bounded order intent assigned to the account's active Agent."""

        if not broker_order_evidence_integrated():
            require_broker_order_evidence(checkpoint="create")

        action = "create_live_order"
        binding = (
            BrokerAccountBindingModel._default_manager.select_related("agent")
            .filter(account_id=int(payload["account_id"]), is_active=True, agent__is_active=True)
            .first()
        )
        if binding is None:
            raise BrokerExecutionConflictError("No active QMT Agent binding exists")
        if not is_admin and not self.has_account_access(
            user_id=user_id,
            is_admin=False,
            account_id=binding.account_id,
            action="trade",
        ):
            raise BrokerExecutionPermissionError("Account access is not authorized")
        symbol = str(payload["asset_code"]).strip().upper()
        if not binding.allowed_symbols or symbol not in set(binding.allowed_symbols):
            raise BrokerExecutionConflictError("Asset is not on the live execution allow-list")
        side = str(payload.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise BrokerExecutionConflictError("Order side must be BUY or SELL")
        source_recommendation_ids = [
            str(item)
            for item in (payload.get("source_recommendation_ids") or [])
            if str(item).strip()
        ]
        if not source_recommendation_ids:
            raise BrokerExecutionConflictError("Live order requires source recommendation evidence")
        expires_at = self._parse_agent_datetime(payload["expires_at"])
        if expires_at <= timezone.now():
            raise BrokerExecutionConflictError("Live order expiry must be in the future")
        quantity = Decimal(str(payload["quantity"]))
        price = Decimal(str(payload["limit_price"]))
        amount = (quantity * price).quantize(Decimal("0.01"))
        if quantity <= 0 or price <= 0 or quantity != quantity.to_integral_value():
            raise BrokerExecutionConflictError("Order quantity/price is invalid")
        if side == "BUY" and quantity % Decimal("100") != 0:
            raise BrokerExecutionConflictError("A-share buy quantity must use 100-share lots")
        market_snapshot = dict((payload.get("risk_snapshot") or {}).get("market_snapshot") or {})
        deviation = Decimal("0")
        if str(payload.get("initial_status")) != LiveOrderStatus.RISK_REJECTED.value:
            current_price = Decimal(str(market_snapshot.get("current_price") or "0"))
            if current_price <= 0 or market_snapshot.get("must_not_use_for_decision"):
                raise BrokerExecutionConflictError(
                    "A fresh positive server-side market quote is required"
                )
            if binding.price_deviation_limit_pct <= 0:
                raise BrokerExecutionConflictError(
                    "A positive price-deviation limit must be configured"
                )
            deviation = abs(price - current_price) / current_price
            if deviation > binding.price_deviation_limit_pct:
                raise BrokerExecutionConflictError(
                    "Order price exceeds the configured market-price deviation"
                )
        if binding.max_single_order_amount <= 0 or amount > binding.max_single_order_amount:
            raise BrokerExecutionConflictError("Order exceeds the configured single-order limit")
        with transaction.atomic():
            binding = (
                BrokerAccountBindingModel._default_manager.select_for_update()
                .select_related("agent")
                .filter(
                    pk=binding.pk,
                    is_active=True,
                    agent__is_active=True,
                    auto_execution_enabled=True,
                )
                .first()
            )
            if binding is None:
                raise BrokerExecutionConflictError(
                    "The active QMT Agent binding changed before order creation"
                )
            replay = self._replay_or_conflict(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if not is_admin and not self.has_account_access(
                user_id=user_id,
                is_admin=False,
                account_id=binding.account_id,
                action="trade",
            ):
                raise BrokerExecutionPermissionError("Account access changed before order creation")
            if not binding.allowed_symbols or symbol not in set(binding.allowed_symbols):
                raise BrokerExecutionConflictError("Asset is not on the live execution allow-list")
            if binding.max_single_order_amount <= 0 or amount > binding.max_single_order_amount:
                raise BrokerExecutionConflictError(
                    "Order exceeds the configured single-order limit"
                )
            if str(payload.get("initial_status")) != LiveOrderStatus.RISK_REJECTED.value:
                if binding.price_deviation_limit_pct <= 0:
                    raise BrokerExecutionConflictError(
                        "A positive price-deviation limit must be configured"
                    )
                if deviation > binding.price_deviation_limit_pct:
                    raise BrokerExecutionConflictError(
                        "Order price exceeds the configured market-price deviation"
                    )

            if replay is not None:
                previous = LiveOrderModel._default_manager.filter(
                    client_order_id=payload["client_order_id"],
                    user_id=user_id,
                    account_id=binding.account_id,
                ).first()
                if previous is None:
                    raise BrokerExecutionConflictError("broker_checkpoint_replay_order_unavailable")
                self._verify_order_replay(previous)
                return replay

            today_amount = LiveOrderModel._default_manager.filter(
                user_id=binding.user_id,
                account_id=binding.account_id,
                created_at__date=timezone.localdate(),
            ).exclude(
                status__in=[
                    LiveOrderStatus.RISK_REJECTED.value,
                    LiveOrderStatus.REJECTED.value,
                    LiveOrderStatus.EXPIRED.value,
                ]
            ).aggregate(
                total=Sum("estimated_amount")
            )[
                "total"
            ] or Decimal(
                "0"
            )
            if (
                binding.daily_order_amount_limit <= 0
                or today_amount + amount > binding.daily_order_amount_limit
            ):
                raise BrokerExecutionConflictError("Order exceeds the configured daily limit")
            if TradingControlModel._default_manager.filter(
                user_id=binding.user_id,
                account_id__in=[0, binding.account_id],
                kill_switch_active=True,
            ).exists():
                raise BrokerExecutionConflictError("Trading is stopped")

            final_status = str(
                payload.get("initial_status") or LiveOrderStatus.WAITING_APPROVAL.value
            )
            if final_status not in {
                LiveOrderStatus.WAITING_APPROVAL.value,
                LiveOrderStatus.RISK_REJECTED.value,
            }:
                raise BrokerExecutionConflictError("Invalid initial live-order status")
            if final_status == LiveOrderStatus.WAITING_APPROVAL.value:
                quote_deadline = require_current_execution_price(
                    asset_code=symbol,
                    limit_price=price,
                    max_deviation=binding.price_deviation_limit_pct,
                )
                if expires_at <= timezone.now():
                    raise BrokerExecutionConflictError("Order expired before creation")
            try:
                client_order_id = UUID(str(payload.get("client_order_id", "")))
            except ValueError as error:
                raise BrokerExecutionConflictError(
                    "broker_checkpoint_signed_order_required"
                ) from error
            if user_id != binding.user_id or final_status != LiveOrderStatus.WAITING_APPROVAL.value:
                raise BrokerExecutionConflictError("broker_checkpoint_owner_or_trade_risk_rejected")
            checked = verify_order_checkpoint(
                client_order_id=client_order_id,
                account_id=binding.account_id,
                owner_user_id=binding.user_id,
                using="default",
            )
            if LiveOrderModel._default_manager.filter(client_order_id=client_order_id).exists():
                raise BrokerExecutionConflictError("broker_checkpoint_order_already_created")
            order = LiveOrderModel._default_manager.create(
                client_order_id=client_order_id,
                authority_pin=checked.pin(),
                user_id=binding.user_id,
                account_id=binding.account_id,
                agent=binding.agent,
                asset_code=symbol,
                market=str(payload.get("market") or "CN")[:16],
                side=side,
                order_type="LIMIT",
                quantity=quantity,
                limit_price=price,
                estimated_amount=amount,
                source_recommendation_ids=source_recommendation_ids,
                source_signal_ids=list(payload.get("source_signal_ids") or []),
                risk_policy_version=checked.intent.snapshot.risk_policy_version,
                risk_snapshot=json.loads(checked.intent.snapshot.risk_snapshot_json),
                expires_at=expires_at,
                status=LiveOrderStatus.DRAFT.value,
            )
            # Compare after database conversion, including stored price/quantity precision.
            order.refresh_from_db()
            checked.require_order(self._order_payload(order))
            checked.require_unexpired(timezone.now())
            if timezone.now() >= min(quote_deadline, expires_at):
                raise BrokerExecutionConflictError("broker_checkpoint_quote_or_order_expired")
            validate_order_transition(order.status, final_status)
            order.status = final_status
            order.version += 1
            order.save(update_fields=["status", "version", "updated_at"])
            order_payload = self._order_payload(order)
            result = {"success": True, "order": order_payload}
            BrokerExecutionAuditModel._default_manager.create(
                user_id=binding.user_id,
                actor_id=user_id,
                action=(
                    "order_risk_rejected"
                    if final_status == LiveOrderStatus.RISK_REJECTED.value
                    else action
                ),
                account_id=binding.account_id,
                resource_type="live_order",
                resource_id=str(order.client_order_id),
                after=order_payload
                | {"authority_pin": order.authority_pin, "clock_source": "server"},
                request_id=idempotency_key,
            )
            self._save_idempotent_result(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result
