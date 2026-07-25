"""Django repositories for broker execution."""

from __future__ import annotations

from typing import Any, TypeVar

from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    target_status_for_order_action,
)
from apps.broker_execution.domain.services import approval_digest_for_order

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountBindingModel,
    BrokerCommandModel,
    BrokerExecutionAuditModel,
    BrokerExecutionIdempotencyModel,
    LiveOrderModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


class BrokerExecutionOrderControlMixin(BrokerExecutionRepositoryMixinSupport):
    """Idempotent operator order and kill-switch mutations."""

    @staticmethod
    def _replay_or_conflict(
        *, user_id: int, action: str, idempotency_key: str, request_digest: str
    ) -> dict[str, Any] | None:
        existing = BrokerExecutionIdempotencyModel._default_manager.filter(
            user_id=user_id,
            action=action,
            idempotency_key=idempotency_key,
        ).first()
        if existing is None:
            return None
        if existing.request_digest != request_digest:
            raise BrokerExecutionConflictError("idempotency_key was reused with different input")
        return dict(existing.response_payload) | {"idempotent_replay": True}

    @staticmethod
    def _save_idempotent_result(
        *,
        user_id: int,
        action: str,
        idempotency_key: str,
        request_digest: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            BrokerExecutionIdempotencyModel._default_manager.create(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                response_payload=payload,
            )
        except IntegrityError as exc:
            raise BrokerExecutionConflictError("Concurrent idempotent write conflict") from exc

    def mutate_order(
        self,
        *,
        user_id: int,
        is_admin: bool,
        client_order_id: str,
        action: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        idempotency_action = f"order:{action}"
        replay = self._replay_or_conflict(
            user_id=user_id,
            action=idempotency_action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            queryset = LiveOrderModel._default_manager.select_for_update()
            order = queryset.filter(client_order_id=client_order_id).first()
            if order is None:
                raise BrokerExecutionNotFoundError("Live order does not exist")
            if order.version != int(expected_version):
                raise BrokerExecutionConflictError(
                    "Order changed after preview; preview the current version again"
                )
            if not self.has_account_access(
                user_id=user_id,
                is_admin=is_admin,
                account_id=order.account_id,
                action=action,
            ):
                raise BrokerExecutionPermissionError("Account access is not authorized")
            before = self._order_payload(order)
            target_status = target_status_for_order_action(order.status, action)
            if action == "approve":
                if TradingControlModel._default_manager.filter(
                    user_id=order.user_id,
                    account_id__in=[0, order.account_id],
                    kill_switch_active=True,
                ).exists():
                    raise BrokerExecutionConflictError(
                        "Trading is stopped; the order cannot be approved"
                    )
                order.approval_digest = approval_digest_for_order(before)
                order.approved_by_id = user_id
                order.approved_at = timezone.now()
            target = target_status.value
            order.status = target
            order.version += 1
            order.save()
            if target == LiveOrderStatus.CANCEL_PENDING.value and order.agent_id is not None:
                BrokerCommandModel._default_manager.create(
                    agent_id=order.agent_id,
                    command_type="cancel",
                    account_id=order.account_id,
                    payload={
                        "client_order_id": str(order.client_order_id),
                        "broker_order_id": order.broker_order_id,
                    },
                )
            after = self._order_payload(order)
            BrokerExecutionAuditModel._default_manager.create(
                user=order.user,
                actor_id=user_id,
                action=f"order_{action}",
                account_id=order.account_id,
                resource_type="live_order",
                resource_id=str(order.client_order_id),
                before=before,
                after=after,
                reason=reason,
                request_id=idempotency_key,
            )
            result = {"success": True, "preview_only": False, "action": action, "order": after}
            self._save_idempotent_result(
                user_id=user_id,
                action=idempotency_action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result

    def set_kill_switch(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
        active: bool,
        reason: str,
        idempotency_key: str,
        request_digest: str,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = "kill_switch_on" if active else "kill_switch_off"
        replay = self._replay_or_conflict(
            user_id=user_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            target_rows = self.list_kill_switch_targets(
                user_id=user_id,
                is_admin=is_admin,
                account_id=account_id,
            )
            if not target_rows:
                raise BrokerExecutionNotFoundError("Active broker account binding does not exist")

            target_account_ids = sorted({int(target["account_id"]) for target in target_rows})
            locked_account_ids = set(
                BrokerAccountBindingModel._default_manager.select_for_update()
                .filter(account_id__in=target_account_ids, is_active=True)
                .order_by("account_id")
                .values_list("account_id", flat=True)
            )
            if locked_account_ids != set(target_account_ids):
                raise BrokerExecutionConflictError(
                    "Broker account bindings changed before the kill switch was applied"
                )
            replay = self._replay_or_conflict(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay

            controls: list[dict[str, Any]] = []
            for target in target_rows:
                owner_id = int(target["user_id"])
                target_account_id = int(target["account_id"])
                (
                    control,
                    _created,
                ) = TradingControlModel._default_manager.select_for_update().get_or_create(
                    user_id=owner_id,
                    account_id=target_account_id,
                    defaults={"changed_by_id": user_id},
                )
                before = {
                    "kill_switch_active": control.kill_switch_active,
                    "reason": control.reason,
                }
                control.kill_switch_active = active
                control.reason = reason
                control.changed_by_id = user_id
                control.save()
                after = {
                    "user_id": owner_id,
                    "account_id": target_account_id,
                    "kill_switch_active": control.kill_switch_active,
                    "reason": control.reason,
                    "changed_at": control.changed_at.isoformat(),
                }
                controls.append(after)
                BrokerExecutionAuditModel._default_manager.create(
                    user_id=owner_id,
                    actor_id=user_id,
                    action=action,
                    account_id=target_account_id,
                    resource_type="trading_control",
                    resource_id=f"{owner_id}:{target_account_id}",
                    before=before,
                    after=after | {"request_context": dict(request_context or {})},
                    reason=reason,
                    request_id=idempotency_key,
                )
            result = {
                "success": True,
                "preview_only": False,
                "action": action,
                "account_id": account_id,
                "affected_account_count": len(controls),
                "controls": controls,
                "control": (
                    controls[0]
                    if len(controls) == 1
                    else {
                        "kill_switch_active": active,
                        "affected_account_count": len(controls),
                    }
                ),
            }
            self._save_idempotent_result(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result
