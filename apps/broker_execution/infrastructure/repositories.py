"""Django repositories for broker execution."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypeVar

from django.db import transaction
from django.db.models import Model, Sum
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    validate_order_transition,
)

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

        action = "create_live_order"
        replay = self._replay_or_conflict(
            user_id=user_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
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
                .filter(pk=binding.pk, is_active=True, agent__is_active=True)
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
            if replay is not None:
                return replay
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
            order = LiveOrderModel._default_manager.create(
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
                risk_policy_version=str(payload.get("risk_policy_version") or "")[:128],
                risk_snapshot=dict(payload["risk_snapshot"]),
                expires_at=expires_at,
                status=LiveOrderStatus.DRAFT.value,
            )
            validate_order_transition(order.status, final_status)
            order.status = final_status
            order.version += 1
            order.save(update_fields=["status", "version", "updated_at"])
            result = {"success": True, "order": self._order_payload(order)}
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
                after=result["order"],
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
