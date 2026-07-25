"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from django.db import IntegrityError, transaction
from django.db.models import F, Model, Q, Sum
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    is_trading_session_open,
    validate_order_transition,
)
from apps.broker_execution.domain.services import approval_digest_for_order

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerAgentNonceModel,
    BrokerCommandModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    BrokerFillModel,
    BrokerOrderEventModel,
    BrokerPositionSnapshotModel,
    LiveOrderModel,
    OrderLeaseModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class BrokerExecutionAgentRuntimeMixin(BrokerExecutionRepositoryMixinSupport):
    """Broker Agent authentication, leasing, and runtime reporting."""

    def authenticate_agent(
        self,
        *,
        credential_id: str,
        secret_hash: str,
        agent_id: str,
        required_scope: str,
        nonce_hash: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Authenticate a scoped Agent credential and atomically consume its nonce."""

        with transaction.atomic():
            credential = (
                BrokerAgentCredentialModel._default_manager.select_for_update()
                .select_related("agent")
                .filter(credential_id=credential_id)
                .first()
            )
            if credential is None or not hmac.compare_digest(credential.secret_hash, secret_hash):
                raise BrokerAgentAuthenticationError("Invalid Agent credential")
            agent = credential.agent
            if agent.agent_id != agent_id or not agent.is_active:
                raise BrokerAgentAuthenticationError("Agent identity is not active")
            now = timezone.now()
            if credential.revoked_at is not None or credential.expires_at <= now:
                raise BrokerAgentAuthenticationError("Agent credential is expired or revoked")
            if required_scope not in (credential.scopes or []):
                raise BrokerAgentAuthenticationError("Agent credential scope is insufficient")
            allowed_account_ids = sorted(
                {int(item) for item in (credential.allowed_account_ids or [])}
            )
            if not allowed_account_ids:
                raise BrokerAgentAuthenticationError("Agent credential has no account scope")
            try:
                BrokerAgentNonceModel._default_manager.create(
                    credential=credential,
                    nonce_hash=nonce_hash,
                    request_id=request_id,
                )
            except IntegrityError as exc:
                raise BrokerAgentAuthenticationError("Agent request nonce was replayed") from exc
            return {
                "agent_pk": agent.pk,
                "agent_id": agent.agent_id,
                "user_id": agent.user_id,
                "credential_id": str(credential.credential_id),
                "scopes": list(credential.scopes or []),
                "allowed_account_ids": allowed_account_ids,
                "request_id": request_id,
            }

    def heartbeat_agent(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist Agent health without trusting account ownership from the payload."""

        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        was_connected = agent.qmt_connected
        account_ids = [int(item) for item in payload.get("account_ids", [])]
        if not set(account_ids).issubset(set(allowed_account_ids)):
            raise BrokerAgentAuthenticationError("Heartbeat exceeds the credential account scope")
        allowed_ids = set(
            agent.account_bindings.filter(is_active=True).values_list("account_id", flat=True)
        )
        if not set(account_ids).issubset(allowed_ids):
            raise BrokerAgentAuthenticationError("Heartbeat contains an unbound account")
        agent.status = (
            BrokerAgentModel.STATUS_ONLINE
            if bool(payload.get("qmt_connected"))
            else BrokerAgentModel.STATUS_DEGRADED
        )
        agent.qmt_connected = bool(payload.get("qmt_connected"))
        agent.agent_version = str(payload.get("agent_version") or "")[:32]
        agent.last_heartbeat_at = timezone.now()
        agent.health_snapshot = {
            "account_ids": account_ids,
            "qmt_version": str(payload.get("qmt_version") or "")[:64],
            "dry_run": bool(payload.get("dry_run", True)),
            "message": str(payload.get("message") or "")[:500],
        }
        agent.save(
            update_fields=[
                "status",
                "qmt_connected",
                "agent_version",
                "last_heartbeat_at",
                "health_snapshot",
                "updated_at",
            ]
        )
        alerts = []
        if not agent.qmt_connected:
            for binding in agent.account_bindings.filter(is_active=True):
                already_open = BrokerExecutionAlertModel._default_manager.filter(
                    user_id=binding.user_id,
                    account_id=binding.account_id,
                    code="P1_QMT_DISCONNECTED",
                    status="open",
                ).exists()
                if already_open and not was_connected:
                    continue
                alerts.append(
                    self._upsert_operational_alert(
                        user_id=binding.user_id,
                        account_id=binding.account_id,
                        code="P1_QMT_DISCONNECTED",
                        severity="P1",
                        title="QMT 连接已断开",
                        message=f"Agent {agent.agent_id} 仍可通信，但 QMT 当前不可用。",
                        resource_key=agent.agent_id,
                        payload={"agent_id": agent.agent_id},
                    )
                )
        else:
            BrokerExecutionAlertModel._default_manager.filter(
                user_id=agent.user_id,
                account_id__in=allowed_ids,
                code__in=["P1_QMT_DISCONNECTED", "P1_QMT_AGENT_OFFLINE"],
                status="open",
            ).update(status="resolved")
        return {
            "accepted": True,
            "server_time": timezone.now().isoformat(),
            "kill_switch_active": TradingControlModel._default_manager.filter(
                user_id=agent.user_id, kill_switch_active=True
            ).exists(),
            "alerts": alerts,
        }

    def lease_agent_orders(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        limit: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        """Lease READY orders only when connection, binding, and kill switches allow it."""

        now = timezone.now()
        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        if agent.status != BrokerAgentModel.STATUS_ONLINE or not agent.qmt_connected:
            raise BrokerExecutionConflictError("Agent or QMT is not online")
        bindings = list(
            agent.account_bindings.filter(
                account_id__in=allowed_account_ids,
                is_active=True,
                auto_execution_enabled=True,
            )
        )
        local_now = timezone.localtime(now)
        bindings = [
            binding
            for binding in bindings
            if not binding.enforce_trading_session
            or is_trading_session_open(local_now, binding.allowed_trading_windows or [])
        ]
        fresh_account_ids: list[int] = []
        for binding in bindings:
            fresh_after = now - timedelta(seconds=binding.max_snapshot_age_seconds)
            if BrokerAccountSnapshotModel._default_manager.filter(
                agent=agent,
                account_id=binding.account_id,
                captured_at__gte=fresh_after,
            ).exists():
                fresh_account_ids.append(binding.account_id)
        account_ids = fresh_account_ids
        blocked_accounts = set(
            TradingControlModel._default_manager.filter(
                user_id=agent.user_id,
                kill_switch_active=True,
            ).values_list("account_id", flat=True)
        )
        if 0 in blocked_accounts:
            return {"orders": [], "total_count": 0, "stopped": True}
        account_ids = [item for item in account_ids if item not in blocked_accounts]
        if not account_ids:
            return {"orders": [], "total_count": 0, "stopped": bool(blocked_accounts)}
        leased: list[dict[str, Any]] = []
        with transaction.atomic():
            stale_leases = list(
                OrderLeaseModel._default_manager.select_for_update()
                .select_related("order")
                .filter(agent=agent, released_at__isnull=True, expires_at__lte=now)
            )
            for stale in stale_leases:
                if stale.order.status == LiveOrderStatus.LEASED.value:
                    stale.order.status = (
                        LiveOrderStatus.EXPIRED.value
                        if stale.order.expires_at and stale.order.expires_at <= now
                        else LiveOrderStatus.READY.value
                    )
                    stale.order.version += 1
                    stale.order.save(update_fields=["status", "version", "updated_at"])
                stale.released_at = now
                stale.save(update_fields=["released_at"])
            expired = LiveOrderModel._default_manager.select_for_update().filter(
                agent=agent,
                account_id__in=account_ids,
                status=LiveOrderStatus.READY.value,
                expires_at__lte=now,
            )
            expired.update(status=LiveOrderStatus.EXPIRED.value, version=F("version") + 1)
            candidates = list(
                LiveOrderModel._default_manager.select_for_update()
                .filter(
                    agent=agent,
                    account_id__in=account_ids,
                    status=LiveOrderStatus.READY.value,
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .order_by("created_at")[:limit]
            )
            for order in candidates:
                validate_order_transition(order.status, LiveOrderStatus.LEASED.value)
                raw_token = secrets.token_urlsafe(32)
                OrderLeaseModel._default_manager.update_or_create(
                    order=order,
                    defaults={
                        "agent": agent,
                        "lease_token_hash": hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                        "leased_at": now,
                        "expires_at": now + timedelta(seconds=lease_seconds),
                        "released_at": None,
                    },
                )
                order.status = LiveOrderStatus.LEASED.value
                order.version += 1
                order.save(update_fields=["status", "version", "updated_at"])
                payload = self._order_payload(order)
                payload["lease_token"] = raw_token
                payload["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
                leased.append(payload)
        return {"orders": leased, "total_count": len(leased), "stopped": False}

    def acknowledge_submitting(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        client_order_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        """Verify the lease and enter SUBMITTING before calling the broker API."""

        now = timezone.now()
        digest_invalid = False
        result: dict[str, Any] | None = None
        with transaction.atomic():
            order = (
                LiveOrderModel._default_manager.select_for_update()
                .select_related("lease")
                .filter(client_order_id=client_order_id, agent_id=agent_pk)
                .first()
            )
            if order is None:
                raise BrokerExecutionNotFoundError("Leased order does not exist")
            if order.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Order exceeds the credential account scope")
            lease = getattr(order, "lease", None)
            token_hash = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
            if (
                lease is None
                or lease.agent_id != agent_pk
                or lease.released_at is not None
                or lease.expires_at <= now
                or lease.lease_token_hash != token_hash
            ):
                raise BrokerExecutionConflictError("Order lease is invalid or expired")
            if TradingControlModel._default_manager.filter(
                user_id=order.user_id,
                account_id__in=[0, order.account_id],
                kill_switch_active=True,
            ).exists():
                raise BrokerExecutionConflictError("Trading is stopped")
            binding = BrokerAccountBindingModel._default_manager.filter(
                agent_id=agent_pk,
                account_id=order.account_id,
                is_active=True,
                auto_execution_enabled=True,
            ).first()
            if binding is None:
                raise BrokerExecutionConflictError("Live account binding is disabled")
            if order.expires_at is not None and order.expires_at <= now:
                raise BrokerExecutionConflictError("Order expired before broker submission")
            if binding.enforce_trading_session and not is_trading_session_open(
                timezone.localtime(now), binding.allowed_trading_windows or []
            ):
                raise BrokerExecutionConflictError("Trading session is closed")
            if not binding.allowed_symbols or order.asset_code not in set(binding.allowed_symbols):
                raise BrokerExecutionConflictError(
                    "Asset is no longer on the live execution allow-list"
                )
            if (
                binding.max_single_order_amount <= 0
                or order.estimated_amount > binding.max_single_order_amount
            ):
                raise BrokerExecutionConflictError("Order exceeds the current single-order limit")
            today_amount = LiveOrderModel._default_manager.filter(
                user_id=order.user_id,
                account_id=order.account_id,
                created_at__date=timezone.localdate(now),
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
                or today_amount > binding.daily_order_amount_limit
            ):
                raise BrokerExecutionConflictError(
                    "Current live orders exceed the configured daily limit"
                )
            if not BrokerAccountSnapshotModel._default_manager.filter(
                agent_id=agent_pk,
                account_id=order.account_id,
                captured_at__gte=now - timedelta(seconds=binding.max_snapshot_age_seconds),
            ).exists():
                raise BrokerExecutionConflictError("Broker account snapshot is stale")
            latest_snapshot = (
                BrokerAccountSnapshotModel._default_manager.filter(
                    agent_id=agent_pk, account_id=order.account_id
                )
                .order_by("-captured_at")
                .first()
            )
            if latest_snapshot is None:
                raise BrokerExecutionConflictError("Broker account snapshot is unavailable")
            latest_positions = BrokerPositionSnapshotModel._default_manager.filter(
                agent_id=agent_pk,
                account_id=order.account_id,
                captured_at=latest_snapshot.captured_at,
            )
            if order.side == "BUY":
                if order.quantity % Decimal("100") != 0:
                    raise BrokerExecutionConflictError(
                        "A-share buy quantity must use 100-share lots"
                    )
                if latest_snapshot.cash_available < order.estimated_amount:
                    raise BrokerExecutionConflictError("Broker available cash is insufficient")
                held_symbols = set(
                    latest_positions.filter(quantity__gt=0).values_list("asset_code", flat=True)
                )
                if (
                    order.asset_code not in held_symbols
                    and len(held_symbols) >= binding.max_position_count
                ):
                    raise BrokerExecutionConflictError("Maximum position count would be exceeded")
            else:
                available_quantity = latest_positions.filter(
                    asset_code=order.asset_code
                ).values_list("available_quantity", flat=True).first() or Decimal("0")
                if available_quantity < order.quantity:
                    raise BrokerExecutionConflictError("Broker available position is insufficient")
            current = self._order_payload(order)
            if order.approval_digest != approval_digest_for_order(current):
                order.status = LiveOrderStatus.WAITING_APPROVAL.value
                order.approval_digest = ""
                order.approved_by = None
                order.approved_at = None
                order.version += 1
                order.save()
                digest_invalid = True
            else:
                validate_order_transition(order.status, LiveOrderStatus.SUBMITTING.value)
                order.status = LiveOrderStatus.SUBMITTING.value
                order.version += 1
                order.save(update_fields=["status", "version", "updated_at"])
                result = {"accepted": True, "order": self._order_payload(order)}
        if digest_invalid:
            raise BrokerExecutionConflictError("Order approval digest is no longer valid")
        if result is None:
            raise BrokerExecutionConflictError("Order submission acknowledgement failed")
        return result

    @staticmethod
    def _parse_agent_datetime(raw: Any) -> datetime:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def report_agent_events(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply idempotent broker events and conservatively handle unknown outcomes."""

        accepted = 0
        duplicates = 0
        alerts: list[dict[str, Any]] = []
        for item in events:
            event_id = str(item.get("event_id") or "").strip()
            client_order_id = str(item.get("client_order_id") or "").strip()
            if not event_id or not client_order_id:
                raise BrokerExecutionConflictError("event_id and client_order_id are required")
            with transaction.atomic():
                order = (
                    LiveOrderModel._default_manager.select_for_update()
                    .filter(client_order_id=client_order_id, agent_id=agent_pk)
                    .first()
                )
                if order is None:
                    raise BrokerExecutionNotFoundError("Event order does not exist")
                if order.account_id not in set(allowed_account_ids):
                    raise BrokerAgentAuthenticationError(
                        "Event exceeds the credential account scope"
                    )
                if BrokerOrderEventModel._default_manager.filter(
                    agent_id=agent_pk,
                    event_id=event_id,
                ).exists():
                    duplicates += 1
                    continue
                target = str(item.get("status") or "").upper()
                if (
                    order.failure_code == "BROKER_OVERFILL"
                    and target
                    and target != LiveOrderStatus.RECONCILIATION_REQUIRED.value
                ):
                    target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                if target:
                    try:
                        validate_order_transition(order.status, target)
                    except ValueError:
                        if target not in LiveOrderStatus._value2member_map_:
                            target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        elif order.status != target:
                            target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        if (
                            order.status in {status.value for status in LiveOrderStatus}
                            and order.status != target
                        ):
                            try:
                                validate_order_transition(order.status, target)
                            except ValueError:
                                target = order.status
                BrokerOrderEventModel._default_manager.create(
                    agent_id=agent_pk,
                    order=order,
                    event_id=event_id,
                    event_type=str(item.get("event_type") or "UNKNOWN")[:64],
                    status=target,
                    payload=dict(item.get("payload") or {}),
                    occurred_at=self._parse_agent_datetime(item.get("occurred_at")),
                )
                if item.get("broker_order_id"):
                    order.broker_order_id = str(item["broker_order_id"])[:128]
                if target and target != order.status:
                    order.status = target
                if (
                    target
                    in {
                        LiveOrderStatus.SUBMITTED.value,
                        LiveOrderStatus.PARTIALLY_FILLED.value,
                        LiveOrderStatus.FILLED.value,
                        LiveOrderStatus.CANCEL_PENDING.value,
                        LiveOrderStatus.CANCELED.value,
                    }
                    and order.submitted_at is None
                ):
                    order.submitted_at = timezone.now()
                if (
                    target
                    in {
                        LiveOrderStatus.BROKER_REJECTED.value,
                        LiveOrderStatus.FAILED.value,
                        LiveOrderStatus.RECONCILIATION_REQUIRED.value,
                    }
                    and order.failure_code != "BROKER_OVERFILL"
                ):
                    event_payload = dict(item.get("payload") or {})
                    order.failure_code = str(item.get("event_type") or target)[:64]
                    order.failure_message = str(
                        event_payload.get("status_msg")
                        or event_payload.get("broker_message")
                        or event_payload.get("message")
                        or ""
                    )[:2000]
                fill = item.get("fill")
                if isinstance(fill, dict) and fill.get("broker_trade_id"):
                    quantity = Decimal(str(fill.get("quantity") or "0"))
                    price = Decimal(str(fill.get("price") or "0"))
                    if quantity <= 0 or price <= 0:
                        raise BrokerExecutionConflictError(
                            "Broker fill quantity and price must be positive"
                        )
                    binding = BrokerAccountBindingModel._default_manager.filter(
                        agent_id=agent_pk,
                        account_id=order.account_id,
                        is_active=True,
                    ).first()
                    if binding is None:
                        raise BrokerAgentAuthenticationError(
                            "Event account is not actively bound to this Agent"
                        )
                    persisted_fill, _created = BrokerFillModel._default_manager.get_or_create(
                        broker_account_ref=binding.broker_account_ref,
                        broker_trade_id=str(fill["broker_trade_id"])[:128],
                        defaults={
                            "order": order,
                            "agent_id": agent_pk,
                            "quantity": quantity,
                            "price": price,
                            "amount": quantity * price,
                            "occurred_at": self._parse_agent_datetime(
                                fill.get("occurred_at") or item.get("occurred_at")
                            ),
                            "payload": dict(fill.get("payload") or {}),
                        },
                    )
                    if persisted_fill.order_id != order.pk:
                        raise BrokerExecutionConflictError(
                            "Broker trade is already attached to another order"
                        )
                    totals = order.fills.aggregate(quantity=Sum("quantity"), amount=Sum("amount"))
                    order.filled_quantity = totals["quantity"] or Decimal("0")
                    if order.filled_quantity:
                        order.average_fill_price = (
                            totals["amount"] or Decimal("0")
                        ) / order.filled_quantity
                    if order.filled_quantity > order.quantity:
                        target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        order.status = target
                        order.failure_code = "BROKER_OVERFILL"
                        order.failure_message = (
                            "Broker cumulative fill quantity exceeds the approved order quantity"
                        )
                order.version += 1
                order.save()
                if target == LiveOrderStatus.RECONCILIATION_REQUIRED.value:
                    is_overfill = order.failure_code == "BROKER_OVERFILL"
                    alerts.append(
                        self._upsert_operational_alert(
                            user_id=order.user_id,
                            account_id=order.account_id,
                            code=(
                                "P0_BROKER_OVERFILL" if is_overfill else "P0_ORDER_OUTCOME_UNKNOWN"
                            ),
                            severity="P0",
                            title=(
                                "券商累计成交超过批准数量，已自动停止新单"
                                if is_overfill
                                else "实盘订单结果未知，已自动停止新单"
                            ),
                            message=(
                                f"订单 {order.client_order_id} 出现超额成交，必须立即核验券商事实。"
                                if is_overfill
                                else f"订单 {order.client_order_id} 必须先查询券商事实并完成对账。"
                            ),
                            resource_key=str(order.client_order_id),
                            payload={"client_order_id": str(order.client_order_id)},
                            auto_stop=True,
                        )
                    )
                accepted += 1
        return {
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "alerts": alerts,
        }

    def sync_agent_snapshot(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one account snapshot and its normalized positions."""

        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        account_id = int(payload.get("account_id") or 0)
        if account_id not in set(allowed_account_ids):
            raise BrokerAgentAuthenticationError("Snapshot exceeds the credential account scope")
        if not agent.account_bindings.filter(account_id=account_id, is_active=True).exists():
            raise BrokerAgentAuthenticationError("Snapshot account is not bound to this Agent")
        captured_at = self._parse_agent_datetime(payload.get("captured_at"))
        if captured_at > timezone.now() + timedelta(minutes=5):
            raise BrokerExecutionConflictError("Broker snapshot timestamp is too far in the future")
        with transaction.atomic():
            BrokerAccountSnapshotModel._default_manager.update_or_create(
                agent=agent,
                account_id=account_id,
                captured_at=captured_at,
                defaults={
                    "user_id": agent.user_id,
                    "cash_available": Decimal(str(payload.get("cash_available") or "0")),
                    "total_asset": Decimal(str(payload.get("total_asset") or "0")),
                    "payload": dict(payload.get("payload") or {})
                    | {
                        "orders": list(payload.get("orders") or []),
                        "trades": list(payload.get("trades") or []),
                    },
                },
            )
            for position in payload.get("positions", []):
                BrokerPositionSnapshotModel._default_manager.update_or_create(
                    agent=agent,
                    account_id=account_id,
                    asset_code=str(position.get("asset_code") or "")[:32],
                    captured_at=captured_at,
                    defaults={
                        "user_id": agent.user_id,
                        "quantity": Decimal(str(position.get("quantity") or "0")),
                        "available_quantity": Decimal(
                            str(position.get("available_quantity") or "0")
                        ),
                        "payload": dict(position.get("payload") or {}),
                    },
                )
        return {"accepted": True, "captured_at": captured_at.isoformat()}

    def lease_agent_commands(
        self, *, agent_pk: int, allowed_account_ids: list[int], limit: int
    ) -> dict[str, Any]:
        """Lease pending commands for delivery to one Agent."""

        rows: list[dict[str, Any]] = []
        now = timezone.now()
        with transaction.atomic():
            BrokerCommandModel._default_manager.filter(
                agent_id=agent_pk,
                status="leased",
                leased_at__lt=now - timedelta(minutes=2),
            ).update(status="pending", leased_at=None)
            commands = list(
                BrokerCommandModel._default_manager.select_for_update()
                .filter(agent_id=agent_pk, status="pending")
                .filter(Q(account_id=0) | Q(account_id__in=allowed_account_ids))
                .order_by("created_at")[:limit]
            )
            for command in commands:
                command.status = "leased"
                command.leased_at = now
                command.save(update_fields=["status", "leased_at"])
                rows.append(
                    {
                        "command_id": str(command.command_id),
                        "command_type": command.command_type,
                        "account_id": command.account_id,
                        "payload": command.payload or {},
                        "created_at": command.created_at.isoformat(),
                    }
                )
        return {"commands": rows, "total_count": len(rows)}

    def complete_agent_command(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        command_id: str,
        success: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Complete one leased command and normalize cancel acknowledgement."""

        with transaction.atomic():
            command = (
                BrokerCommandModel._default_manager.select_for_update()
                .filter(command_id=command_id, agent_id=agent_pk)
                .first()
            )
            if command is None:
                raise BrokerExecutionNotFoundError("Agent command does not exist")
            if command.account_id and command.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Command exceeds the credential account scope")
            if command.status in {"completed", "failed"}:
                return {
                    "accepted": True,
                    "status": command.status,
                    "idempotent_replay": True,
                }
            if command.status != "leased":
                raise BrokerExecutionConflictError("Agent command is not leased")
            command.status = "completed" if success else "failed"
            command.completed_at = timezone.now()
            command.payload = dict(command.payload or {}) | {"result": result}
            command.save(update_fields=["status", "completed_at", "payload"])
            client_order_id = str(command.payload.get("client_order_id") or "")
            audit_account_id = command.account_id
            audit_resource_type = "broker_command"
            audit_resource_id = str(command.command_id)
            audit_before: dict[str, Any] = {"status": "leased"}
            audit_after: dict[str, Any] = {
                "status": command.status,
                "result": result,
            }
            if command.command_type == "cancel" and client_order_id:
                order = (
                    LiveOrderModel._default_manager.select_for_update()
                    .filter(client_order_id=client_order_id, agent_id=agent_pk)
                    .first()
                )
                if order is not None and order.status == LiveOrderStatus.CANCEL_PENDING.value:
                    audit_account_id = order.account_id
                    audit_resource_type = "live_order"
                    audit_resource_id = str(order.client_order_id)
                    audit_before = {"status": order.status}
                    if not success:
                        target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        validate_order_transition(order.status, target)
                        order.status = target
                        order.version += 1
                        order.save(update_fields=["status", "version", "updated_at"])
                    audit_after = {
                        "status": order.status,
                        "command_status": command.status,
                        "awaiting_broker_final_status": success,
                        "result": result,
                    }
            BrokerExecutionAuditModel._default_manager.create(
                user_id=command.agent.user_id,
                actor=None,
                actor_type="agent",
                action=f"agent_command_{command.command_type}_{command.status}",
                account_id=audit_account_id,
                resource_type=audit_resource_type,
                resource_id=audit_resource_id,
                before=audit_before,
                after=audit_after,
                reason="Agent command completion",
                request_id=str(command.command_id),
            )
            return {"accepted": True, "status": command.status}
