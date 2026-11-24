"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from django.db import IntegrityError, transaction
from django.db.models import F, Model, Q, Sum
from django.utils import timezone

from apps.broker_execution.application.evidence_gate import (
    blocked_lease_result,
    broker_order_evidence_integrated,
    require_broker_order_evidence,
)
from apps.broker_execution.application.execution_contract_capabilities import (
    parse_agent_execution_contracts,
)
from apps.broker_execution.application.execution_price_guard import require_current_execution_price
from apps.broker_execution.application.ports import PartialBatchAlertHandler
from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.domain.connection_freshness import heartbeat_times_are_fresh
from apps.broker_execution.domain.entities import TERMINAL_ORDER_STATUSES, LiveOrderStatus
from apps.broker_execution.domain.rules import (
    is_prior_broker_status,
    is_trading_session_open,
    validate_order_transition,
)
from apps.broker_execution.domain.services import approval_digest_for_order
from apps.broker_execution.order_checkpoint_composition import verify_existing_order

from . import broker_agent_account_reports, broker_agent_commands
from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .broker_trade_receipt import _TRADE_EVENTS, _read_trade_receipt, _receipt_clock, _receipt_time
from .models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerAgentNonceModel,
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


def _require_agent_submission_contract(agent: BrokerAgentModel | None) -> None:
    """Block new submission on missing, malformed, or unsupported capability data."""

    if agent is None:
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED")
    snapshot: object = agent.health_snapshot
    if not isinstance(snapshot, dict):
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED")
    try:
        capabilities = parse_agent_execution_contracts(
            snapshot.get("execution_constraint_schemas", [])
        )
    except BrokerExecutionValidationError as error:
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED") from error
    if not capabilities.supports_submission_v2:
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED")


def _require_online_agent(agent: BrokerAgentModel, evaluated_at: datetime) -> None:
    _require_agent_submission_contract(agent)
    if (
        not agent.is_active
        or agent.status != BrokerAgentModel.STATUS_ONLINE
        or not agent.qmt_connected
    ):
        raise BrokerExecutionConflictError("Agent or QMT is not online")
    try:
        observed_at = datetime.fromisoformat(
            str((agent.health_snapshot or {}).get("source_observed_at") or "").replace(
                "Z", "+00:00"
            )
        )
    except ValueError:
        observed_at = None
    if not heartbeat_times_are_fresh(
        source_observed_at=observed_at,
        received_at=agent.last_heartbeat_at,
        evaluated_at=evaluated_at,
    ):
        raise BrokerExecutionConflictError("Agent heartbeat source or receipt is stale")


def _require_submitting_window(
    *,
    agent: BrokerAgentModel,
    binding: BrokerAccountBindingModel,
    order: LiveOrderModel,
    lease: OrderLeaseModel,
    evaluated_at: datetime,
) -> None:
    _require_online_agent(agent, evaluated_at)
    if lease.expires_at <= evaluated_at:
        raise BrokerExecutionConflictError("Order lease is invalid or expired")
    if order.expires_at is not None and order.expires_at <= evaluated_at:
        raise BrokerExecutionConflictError("Order expired before broker submission")
    if binding.enforce_trading_session and not is_trading_session_open(
        timezone.localtime(evaluated_at), binding.allowed_trading_windows or []
    ):
        raise BrokerExecutionConflictError("Trading session is closed")


_ORDER_REPORTS = frozenset({"QMT_ORDER_STATUS", "FAKE_ORDER_STATUS", "AGENT_RECOVERY_QUERY"})
_BROKER_ORDER_STATES = frozenset(
    {
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELED",
        "BROKER_REJECTED",
        "RECONCILIATION_REQUIRED",
    }
)
_TRADE_COMPATIBLE_STATES = frozenset(
    {
        "SUBMITTING",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELED",
        "RECONCILIATION_REQUIRED",
    }
)
_AGENT_OUTCOMES = {
    "DRY_RUN_VALIDATED": "",
    "ORDER_SUBMITTED": "SUBMITTED",
    "BROKER_REJECTED": "BROKER_REJECTED",
    "LOCAL_SUBMIT_VALIDATION_FAILED": "FAILED",
    "SERVER_ACK_OUTCOME_UNKNOWN": "RECONCILIATION_REQUIRED",
    "SUBMIT_OUTCOME_UNKNOWN": "RECONCILIATION_REQUIRED",
    "QMT_ORDER_IDENTITY_CONFLICT": "RECONCILIATION_REQUIRED",
    "QMT_ORDER_STATUS_UNKNOWN": "RECONCILIATION_REQUIRED",
}


def _record_agent_checkpoint(order: LiveOrderModel, action: str) -> None:
    """Archive one server transition without exposing the lease credential."""
    BrokerExecutionAuditModel._default_manager.create(
        user_id=order.user_id,
        actor_type="agent",
        action=action,
        account_id=order.account_id,
        resource_type="live_order",
        resource_id=str(order.client_order_id),
        request_id=f"{order.client_order_id}:{order.version}",
        after={
            "version": order.version,
            "status": order.status,
            "authority_pin": order.authority_pin,
            "agent_pk": order.agent_id,
            "clock_source": "server",
        },
    )


def _event_target(
    order: LiveOrderModel, reported: str, event_type: str, broker_id: str
) -> tuple[str, bool]:
    """Return the resulting order state and any discrepancy requiring a stop."""

    if (
        event_type == "UNKNOWN"
        or (event_type in _AGENT_OUTCOMES and reported != _AGENT_OUTCOMES[event_type])
        or (event_type in _ORDER_REPORTS and reported not in _BROKER_ORDER_STATES)
        or (
            event_type in _TRADE_EVENTS
            and (reported or order.status not in _TRADE_COMPATIBLE_STATES)
        )
    ):
        reported = LiveOrderStatus.RECONCILIATION_REQUIRED.value
    if order.failure_code == "BROKER_OVERFILL":
        return LiveOrderStatus.RECONCILIATION_REQUIRED.value, True
    if not reported or reported == order.status:
        return reported, reported == LiveOrderStatus.RECONCILIATION_REQUIRED.value
    same_broker = bool(broker_id and order.broker_order_id == broker_id)
    if same_broker and is_prior_broker_status(order.status, reported):
        return order.status, False
    if (
        same_broker
        and order.status == "SUBMITTING"
        and event_type in _ORDER_REPORTS
        and (
            (reported == "PARTIALLY_FILLED" and 0 < order.filled_quantity < order.quantity)
            or (reported == "FILLED" and order.filled_quantity == order.quantity)
        )
    ):
        # A broker fill and aggregate report may both reach the server before the ACK.
        return reported, False
    try:
        validate_order_transition(order.status, reported)
    except ValueError:
        if order.status in TERMINAL_ORDER_STATUSES:
            return order.status, True
        return LiveOrderStatus.RECONCILIATION_REQUIRED.value, True
    return reported, reported == LiveOrderStatus.RECONCILIATION_REQUIRED.value


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

        return broker_agent_account_reports.heartbeat_agent(
            self, agent_pk=agent_pk, allowed_account_ids=allowed_account_ids, payload=payload
        )

    def lease_agent_orders(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        limit: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        """Lease READY orders only when connection, binding, and kill switches allow it."""

        if not broker_order_evidence_integrated():
            return blocked_lease_result()

        now = timezone.now()
        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        _require_online_agent(agent, now)
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
        for candidate_binding in bindings:
            fresh_after = now - timedelta(seconds=candidate_binding.max_snapshot_age_seconds)
            if BrokerAccountSnapshotModel._default_manager.filter(
                agent=agent,
                account_id=candidate_binding.account_id,
                captured_at__gte=fresh_after,
                captured_at__lte=now,
            ).exists():
                fresh_account_ids.append(candidate_binding.account_id)
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
            agent = BrokerAgentModel._default_manager.select_for_update().get(pk=agent_pk)
            now = timezone.now()
            _require_online_agent(agent, now)
            stale_leases = list(
                OrderLeaseModel._default_manager.select_for_update()
                .select_related("order")
                .filter(
                    agent=agent,
                    order__account_id__in=account_ids,
                    released_at__isnull=True,
                    expires_at__lte=now,
                )
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
                LiveOrderModel._default_manager.select_for_update(of=("self",))
                .filter(
                    agent=agent,
                    account_id__in=account_ids,
                    status=LiveOrderStatus.READY.value,
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .order_by("created_at")[:limit]
            )
            for order in candidates:
                # Serialize advancement with a disable or kill switch on this account.
                binding = (
                    BrokerAccountBindingModel._default_manager.select_for_update()
                    .filter(
                        agent=agent,
                        user_id=order.user_id,
                        account_id=order.account_id,
                        is_active=True,
                        auto_execution_enabled=True,
                    )
                    .first()
                )
                if binding is None:
                    continue
                if TradingControlModel._default_manager.filter(
                    user_id=order.user_id,
                    account_id__in=[0, order.account_id],
                    kill_switch_active=True,
                ).exists():
                    continue
                try:
                    checked = verify_existing_order(
                        client_order_id=order.client_order_id,
                        account_id=order.account_id,
                        owner_user_id=order.user_id,
                        authority_pin=order.authority_pin,
                        payload=self._order_payload(order),
                    )
                    if order.approval_digest != checked.intent.sources.order.approval_digest:
                        continue
                    quote_deadline = require_current_execution_price(
                        asset_code=order.asset_code,
                        limit_price=order.limit_price,
                        max_deviation=binding.price_deviation_limit_pct,
                    )
                except BrokerExecutionConflictError:
                    continue
                now = timezone.now()
                _require_online_agent(agent, now)
                if order.expires_at is not None and order.expires_at <= now:
                    continue
                if binding.enforce_trading_session and not is_trading_session_open(
                    timezone.localtime(now), binding.allowed_trading_windows or []
                ):
                    continue
                if not BrokerAccountSnapshotModel._default_manager.filter(
                    agent=agent,
                    account_id=order.account_id,
                    captured_at__lte=now,
                    captured_at__gte=now - timedelta(seconds=binding.max_snapshot_age_seconds),
                ).exists():
                    continue
                if timezone.now() >= min(checked.valid_until, quote_deadline):
                    continue
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
                _record_agent_checkpoint(order, "order_lease")
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

        if not broker_order_evidence_integrated():
            require_broker_order_evidence(checkpoint="submitting")

        digest_invalid = False
        result: dict[str, Any] | None = None
        with transaction.atomic():
            agent = BrokerAgentModel._default_manager.select_for_update().get(pk=agent_pk)
            order = (
                LiveOrderModel._default_manager.select_for_update(of=("self",))
                .select_related("lease", "agent")
                .filter(client_order_id=client_order_id, agent_id=agent_pk)
                .first()
            )
            if order is None:
                raise BrokerExecutionNotFoundError("Leased order does not exist")
            if order.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Order exceeds the credential account scope")
            _require_online_agent(agent, timezone.now())
            binding = (
                BrokerAccountBindingModel._default_manager.select_for_update()
                .filter(
                    agent_id=agent_pk,
                    user_id=order.user_id,
                    account_id=order.account_id,
                    is_active=True,
                    auto_execution_enabled=True,
                )
                .first()
            )
            if binding is None:
                raise BrokerExecutionConflictError("Live account binding is disabled")
            lease = getattr(order, "lease", None)
            token_hash = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
            if (
                lease is None
                or lease.agent_id != agent_pk
                or lease.released_at is not None
                or not hmac.compare_digest(lease.lease_token_hash, token_hash)
            ):
                raise BrokerExecutionConflictError("Order lease is invalid or expired")
            if TradingControlModel._default_manager.filter(
                user_id=order.user_id,
                account_id__in=[0, order.account_id],
                kill_switch_active=True,
            ).exists():
                raise BrokerExecutionConflictError("Trading is stopped")
            quote_deadline = require_current_execution_price(
                asset_code=order.asset_code,
                limit_price=order.limit_price,
                max_deviation=binding.price_deviation_limit_pct,
            )
            now = timezone.now()
            _require_submitting_window(
                agent=agent, binding=binding, order=order, lease=lease, evaluated_at=now
            )
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
            latest_snapshot = (
                BrokerAccountSnapshotModel._default_manager.filter(
                    agent_id=agent_pk,
                    account_id=order.account_id,
                    captured_at__lte=now,
                    captured_at__gte=now - timedelta(seconds=binding.max_snapshot_age_seconds),
                )
                .order_by("-captured_at")
                .first()
            )
            if latest_snapshot is None:
                raise BrokerExecutionConflictError(
                    "Broker account snapshot is stale or unavailable"
                )
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
                checked = verify_existing_order(
                    client_order_id=order.client_order_id,
                    account_id=order.account_id,
                    owner_user_id=order.user_id,
                    authority_pin=order.authority_pin,
                    payload=current,
                )
                write_at = timezone.now()
                checked.require_unexpired(write_at)
                _require_submitting_window(
                    agent=agent, binding=binding, order=order, lease=lease, evaluated_at=write_at
                )
                if write_at >= quote_deadline:
                    raise BrokerExecutionConflictError("execution_quote_stale")
                if (
                    not write_at - timedelta(seconds=binding.max_snapshot_age_seconds)
                    <= latest_snapshot.captured_at
                    <= write_at
                ):
                    raise BrokerExecutionConflictError(
                        "Broker account snapshot is stale or unavailable"
                    )
                order.status = LiveOrderStatus.SUBMITTING.value
                order.version += 1
                order.save(update_fields=["status", "version", "updated_at"])
                _record_agent_checkpoint(order, "order_submitting")
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
        on_partial_alerts: PartialBatchAlertHandler | None = None,
    ) -> dict[str, Any]:
        """Apply broker receipts and deliver earlier committed alerts if a later receipt fails."""

        alerts: list[dict[str, Any]] = []
        try:
            return self._apply_agent_event_batch(
                agent_pk=agent_pk,
                allowed_account_ids=allowed_account_ids,
                events=events,
                alerts=alerts,
            )
        except Exception:
            if alerts and on_partial_alerts is not None:

                def forward_committed_prefix() -> None:
                    on_partial_alerts(alerts)

                transaction.on_commit(forward_committed_prefix, robust=True)
            raise

    def _apply_agent_event_batch(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        events: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        accepted = 0
        duplicates = 0
        reported_orders: set[int] = set()
        for item in events:
            event_id = str(item.get("event_id") or "").strip()
            client_order_id = str(item.get("client_order_id") or "").strip()
            if not event_id or not client_order_id:
                raise BrokerExecutionConflictError("event_id and client_order_id are required")
            committed_alert: dict[str, Any] | None = None
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
                reported_orders.add(order.pk)
                broker_id = str(item.get("broker_order_id") or "")
                reported = str(item.get("status") or "").upper()
                raw_type = str(item.get("event_type") or "UNKNOWN")
                event_type = (
                    raw_type
                    if (
                        raw_type in _TRADE_EVENTS
                        or raw_type in _ORDER_REPORTS
                        or raw_type in _AGENT_OUTCOMES
                    )
                    else "UNKNOWN"
                )
                if event_type != "UNKNOWN" and reported in {
                    "DRAFT",
                    "WAITING_APPROVAL",
                    "READY",
                    "LEASED",
                    "SUBMITTING",
                }:
                    raise BrokerExecutionConflictError(
                        "Broker report cannot advance a server authorization checkpoint"
                    )
                event_payload = dict(item.get("payload") or {})
                received_at = timezone.now()
                occurred_at = _receipt_time(item.get("occurred_at"))
                clock, source = _receipt_clock(event_payload, occurred_at, received_at)
                if source is not None and event_type not in {"QMT_TRADE", "UNKNOWN"}:
                    raise BrokerExecutionConflictError(
                        "This broker event has no broker source clock"
                    )
                event_payload.update(clock_source=clock, broker_source_at=source)
                fill = _read_trade_receipt(
                    item.get("fill"), event_type, occurred_at, received_at, event_payload
                )
                identity: dict[str, object] = {
                    "broker_order_id": broker_id,
                    "event_type": raw_type,
                    "reported_status": reported,
                    "clock_source": clock,
                    "broker_source_at": source,
                }
                if fill is not None:
                    identity.update(
                        broker_trade_id=fill.trade_id,
                        quantity=str(fill.quantity.normalize()),
                        price=str(fill.price.normalize()),
                    )
                    if fill.account_ref is not None:
                        # Preserve account identity on replay without copying the vendor account into the timeline.
                        identity["broker_account_ref_hash"] = hashlib.sha256(
                            fill.account_ref.encode()
                        ).hexdigest()
                elif isinstance(item.get("fill"), dict):
                    # An unknown sender's claim is retained for review and never posted as a fill.
                    claimed = item["fill"]
                    identity.update(
                        broker_trade_id=str(claimed.get("broker_trade_id") or ""),
                        quantity=str(claimed.get("quantity")),
                        price=str(claimed.get("price")),
                    )
                target, needs_review = _event_target(order, reported, event_type, broker_id)
                event, created = BrokerOrderEventModel._default_manager.get_or_create(
                    agent_id=agent_pk,
                    event_id=event_id,
                    defaults={
                        "order": order,
                        "event_type": event_type,
                        "status": target,
                        "payload": event_payload
                        | {
                            "reported_event_type": raw_type,
                            "reported_status": reported,
                            "order_version": order.version + 1,
                            "authority_pin": order.authority_pin,
                            "receipt_identity_v1": identity,
                        },
                        "occurred_at": occurred_at,
                    },
                )
                if not created:
                    previous = event.payload or {}
                    stored_identity = previous.get("receipt_identity_v1")
                    if stored_identity is None:
                        # Legacy rows did not store the original broker or fill selector.
                        matches = (
                            event.event_type == raw_type
                            and previous.get("reported_status", reported) == reported
                        )
                    else:
                        matches = stored_identity == identity
                    if event.order_id != order.pk or not matches:
                        raise BrokerExecutionConflictError(
                            "Broker event identity conflicts with its first report"
                        )
                    duplicates += 1
                    continue
                binding: BrokerAccountBindingModel | None = None
                if event_type.startswith(("QMT_", "FAKE_")):
                    binding = (
                        BrokerAccountBindingModel._default_manager.select_for_update()
                        .filter(
                            agent_id=agent_pk,
                            user_id=order.user_id,
                            account_id=order.account_id,
                        )
                        .first()
                    )
                    if binding is None or (fill is not None and not binding.is_active):
                        raise BrokerAgentAuthenticationError(
                            "Event account is not bound to this Agent"
                        )
                    # The fake adapter identifies its single vendor account as the literal "fake".
                    if event_type.startswith("FAKE_") != (binding.broker_account_ref == "fake"):
                        raise BrokerExecutionConflictError(
                            "Broker account and report source disagree"
                        )
                    if (
                        fill is not None
                        and fill.account_ref is not None
                        and fill.account_ref != binding.broker_account_ref
                    ):
                        raise BrokerExecutionConflictError(
                            "Broker trade account differs from the order binding"
                        )
                if event_type == "UNKNOWN":
                    logging.getLogger(__name__).warning("Unknown broker event type %r", raw_type)
                elif broker_id and order.broker_order_id and broker_id != order.broker_order_id:
                    raise BrokerExecutionConflictError("Broker order identity changed")
                elif broker_id:
                    order.broker_order_id = broker_id
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
                    and not needs_review
                    and order.submitted_at is None
                ):
                    order.submitted_at = received_at
                if (
                    target
                    in {
                        LiveOrderStatus.BROKER_REJECTED.value,
                        LiveOrderStatus.FAILED.value,
                        LiveOrderStatus.RECONCILIATION_REQUIRED.value,
                    }
                    and order.failure_code != "BROKER_OVERFILL"
                ):
                    order.failure_code = event_type
                    order.failure_message = str(
                        event_payload.get("status_msg")
                        or event_payload.get("broker_message")
                        or event_payload.get("message")
                        or ""
                    )[:2000]
                if fill is not None and binding is not None:
                    persisted_fill, _created = BrokerFillModel._default_manager.get_or_create(
                        broker_account_ref=binding.broker_account_ref,
                        broker_trade_id=fill.trade_id,
                        defaults={
                            "order": order,
                            "agent_id": agent_pk,
                            "quantity": fill.quantity,
                            "price": fill.price,
                            "amount": fill.quantity * fill.price,
                            "occurred_at": fill.occurred_at,
                            "payload": fill.payload
                            | {
                                "event_id": event_id,
                                "order_version": order.version + 1,
                                "authority_pin": order.authority_pin,
                            },
                        },
                    )
                    if persisted_fill.order_id != order.pk:
                        raise BrokerExecutionConflictError(
                            "Broker trade is already attached to another order"
                        )
                    if (
                        persisted_fill.quantity != fill.quantity
                        or persisted_fill.price != fill.price
                    ):
                        raise BrokerExecutionConflictError(
                            "Broker trade identity has different fill economics"
                        )
                    first_source = (persisted_fill.payload or {}).get("broker_source_at")
                    if first_source is not None and (
                        source is None or _receipt_time(first_source) != _receipt_time(source)
                    ):
                        raise BrokerExecutionConflictError(
                            "Broker trade identity has a different source time"
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
                if needs_review or target == LiveOrderStatus.RECONCILIATION_REQUIRED.value:
                    is_overfill = order.failure_code == "BROKER_OVERFILL"
                    committed_alert = self._upsert_operational_alert(
                        user_id=order.user_id,
                        account_id=order.account_id,
                        code=("P0_BROKER_OVERFILL" if is_overfill else "P0_ORDER_OUTCOME_UNKNOWN"),
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
                accepted += 1
            if committed_alert is not None:
                alerts.append(committed_alert)
        return {
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "alerts": alerts,
            "order_states": [
                {
                    "client_order_id": str(order_id),
                    "status": status,
                    "broker_order_id": broker_id,
                    "version": version,
                }
                for order_id, status, broker_id, version in LiveOrderModel._default_manager.filter(
                    pk__in=reported_orders, agent_id=agent_pk, account_id__in=allowed_account_ids
                )
                .order_by("pk")
                .values_list("client_order_id", "status", "broker_order_id", "version")
            ],
        }

    def sync_agent_snapshot(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one account snapshot and its normalized positions."""

        return broker_agent_account_reports.sync_agent_snapshot(
            self, agent_pk=agent_pk, allowed_account_ids=allowed_account_ids, payload=payload
        )

    def lease_agent_commands(
        self, *, agent_pk: int, allowed_account_ids: list[int], limit: int
    ) -> dict[str, Any]:
        """Lease pending commands for delivery to one Agent."""

        return broker_agent_commands.lease_agent_commands(
            agent_pk=agent_pk, allowed_account_ids=allowed_account_ids, limit=limit
        )

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

        return broker_agent_commands.complete_agent_command(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            command_id=command_id,
            success=success,
            result=result,
        )
